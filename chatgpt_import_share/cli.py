from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .images import download_generated_images, resolve_generated_image_urls
from .models import Conversation
from .parser import parse_share_source

DEFAULT_TASK = "Please read this ChatGPT conversation and summarize the key points, decisions, and open tasks."
DEFAULT_CHUNK_CHARS = 60000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chatgpt-import-share",
        description="Extract messages from a ChatGPT share page.",
    )
    parser.add_argument("source", help="ChatGPT share URL or saved HTML file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a transcript.",
    )
    parser.add_argument(
        "--ai-studio",
        action="store_true",
        help="Print a paste-ready prompt plus transcript for Google AI Studio or another LLM.",
    )
    parser.add_argument(
        "--task",
        default=DEFAULT_TASK,
        help="Task text to include with --ai-studio output.",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write output to a file instead of stdout.",
    )
    parser.add_argument(
        "--split-dir",
        metavar="DIR",
        help="Write paste-ready chunks into a directory. Implies --ai-studio.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_CHUNK_CHARS,
        help=f"Maximum transcript characters per chunk with --split-dir. Default: {DEFAULT_CHUNK_CHARS}.",
    )
    parser.add_argument(
        "--include-empty",
        action="store_true",
        help="Include messages that do not have text content.",
    )
    parser.add_argument(
        "--role",
        action="append",
        dest="roles",
        help="Filter to one or more roles, for example --role user --role assistant",
    )
    parser.add_argument(
        "--images-json",
        action="store_true",
        help="Resolve generated-image URLs and print them as JSON.",
    )
    parser.add_argument(
        "--download-images",
        metavar="DIR",
        help="Resolve and download generated images into the given directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.json and (args.ai_studio or args.split_dir):
        parser.error("--json cannot be combined with --ai-studio or --split-dir.")
    if args.output and args.split_dir:
        parser.error("--output cannot be combined with --split-dir.")
    if args.max_chars <= 0:
        parser.error("--max-chars must be greater than 0.")
    if (args.images_json or args.download_images) and (args.ai_studio or args.split_dir):
        parser.error("Image options cannot be combined with --ai-studio or --split-dir.")

    conversation = parse_share_source(args.source)

    if args.images_json or args.download_images:
        if not _looks_like_url(args.source):
            raise SystemExit("Image resolution requires a live share URL, not a saved HTML file.")

        images = resolve_generated_image_urls(args.source, conversation=conversation)
        if args.images_json:
            _write_output(
                json.dumps([image.to_dict() for image in images], indent=2, ensure_ascii=True),
                args.output,
            )
            return 0

        saved_paths = download_generated_images(
            args.source,
            args.download_images,
            conversation=conversation,
        )
        _write_output(
            json.dumps([str(path) for path in saved_paths], indent=2, ensure_ascii=True),
            args.output,
        )
        return 0

    if args.json:
        _write_output(json.dumps(conversation.to_dict(), indent=2, ensure_ascii=True), args.output)
        return 0

    transcript = conversation.transcript(
        roles=args.roles,
        include_empty=args.include_empty,
    )
    if args.split_dir:
        chunks = _split_transcript(transcript, max_chars=args.max_chars)
        paths = _write_chunk_files(
            args.split_dir,
            chunks,
            conversation=conversation,
            task=args.task,
        )
        _print_chunk_summary(paths)
        return 0

    if args.ai_studio:
        output = _format_ai_studio_prompt(conversation, transcript, task=args.task)
    else:
        output = _format_transcript(conversation, transcript)

    _write_output(output, args.output)
    return 0


def _looks_like_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _format_transcript(conversation: Conversation, transcript: str) -> str:
    if conversation.title:
        return f"# {conversation.title}\n\n{transcript}\n"
    return f"{transcript}\n"


def _format_ai_studio_prompt(conversation: Conversation, transcript: str, *, task: str) -> str:
    title = conversation.title or "Untitled ChatGPT share"
    return (
        f"{task}\n\n"
        "The transcript is exported from a ChatGPT share page. "
        "Speaker roles are shown in square brackets.\n\n"
        f"Title: {title}\n\n"
        "BEGIN CHATGPT SHARE TRANSCRIPT\n"
        f"{transcript}\n"
        "END CHATGPT SHARE TRANSCRIPT\n"
    )


def _format_ai_studio_chunk(
    chunk: str,
    *,
    conversation: Conversation,
    task: str,
    index: int,
    total: int,
) -> str:
    title = conversation.title or "Untitled ChatGPT share"
    if total == 1:
        return _format_ai_studio_prompt(conversation, chunk, task=task)

    if index < total:
        instruction = (
            "This is one chunk of a longer ChatGPT conversation. "
            "Read it and wait for the remaining chunks before summarizing."
        )
    else:
        instruction = f"This is the final chunk. After reading it, do this task: {task}"

    return (
        f"{instruction}\n\n"
        f"Title: {title}\n"
        f"Chunk: {index} of {total}\n\n"
        f"BEGIN CHATGPT SHARE TRANSCRIPT CHUNK {index} OF {total}\n"
        f"{chunk}\n"
        f"END CHATGPT SHARE TRANSCRIPT CHUNK {index} OF {total}\n"
    )


def _split_transcript(transcript: str, *, max_chars: int) -> list[str]:
    blocks = transcript.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for block in blocks:
        block_length = len(block)
        separator_length = 2 if current else 0
        if current and current_length + separator_length + block_length > max_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_length = 0

        if block_length <= max_chars:
            current.append(block)
            current_length += (2 if current_length else 0) + block_length
            continue

        wrapped = _split_long_block(block, max_chars=max_chars)
        for part in wrapped:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_length = 0
            chunks.append(part)

    if current:
        chunks.append("\n\n".join(current))
    return chunks or [""]


def _split_long_block(block: str, *, max_chars: int) -> list[str]:
    parts: list[str] = []
    start = 0
    while start < len(block):
        parts.append(block[start : start + max_chars])
        start += max_chars
    return parts


def _write_chunk_files(
    directory: str,
    chunks: list[str],
    *,
    conversation: Conversation,
    task: str,
) -> list[Path]:
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    width = max(3, len(str(len(chunks))))
    paths: list[Path] = []
    for index, chunk in enumerate(chunks, start=1):
        path = output_dir / f"chatgpt-share-part-{index:0{width}d}-of-{len(chunks):0{width}d}.md"
        path.write_text(
            _format_ai_studio_chunk(
                chunk,
                conversation=conversation,
                task=task,
                index=index,
                total=len(chunks),
            ),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def _write_output(text: str, output_path: str | None) -> None:
    if output_path is None:
        print(text, end="" if text.endswith("\n") else "\n")
        return
    path = Path(output_path)
    path.write_text(text, encoding="utf-8")
    print(f"Output file written: {path} ({path.stat().st_size} bytes)", file=sys.stderr)


def _print_chunk_summary(paths: list[Path]) -> None:
    if not paths:
        print("No chunk files were written.", file=sys.stderr)
        return

    directory = paths[0].parent
    if len(paths) == 1:
        path = paths[0]
        print(f"Output file written: {path} ({path.stat().st_size} bytes)", file=sys.stderr)
    else:
        print(f"Output files written to {directory}:", file=sys.stderr)
        for path in paths:
            print(f"  {path} ({path.stat().st_size} bytes)", file=sys.stderr)
    print("Paste the generated files into the target chat in filename order.", file=sys.stderr)
