from __future__ import annotations

import argparse
import json

from .images import download_generated_images, resolve_generated_image_urls
from .parser import parse_share_source


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
    args = build_parser().parse_args(argv)

    conversation = parse_share_source(args.source)

    if args.images_json or args.download_images:
        if not _looks_like_url(args.source):
            raise SystemExit("Image resolution requires a live share URL, not a saved HTML file.")

        images = resolve_generated_image_urls(args.source, conversation=conversation)
        if args.images_json:
            print(json.dumps([image.to_dict() for image in images], indent=2, ensure_ascii=True))
            return 0

        saved_paths = download_generated_images(
            args.source,
            args.download_images,
            conversation=conversation,
        )
        print(json.dumps([str(path) for path in saved_paths], indent=2, ensure_ascii=True))
        return 0

    if args.json:
        print(json.dumps(conversation.to_dict(), indent=2, ensure_ascii=True))
        return 0

    if conversation.title:
        print(f"# {conversation.title}\n")
    transcript = conversation.transcript(
        roles=args.roles,
        include_empty=args.include_empty,
    )
    print(transcript)
    return 0


def _looks_like_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")
