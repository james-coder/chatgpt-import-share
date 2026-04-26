from __future__ import annotations

import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import Conversation, GeneratedImage
from .parser import ChatGPTShareError, parse_share_url

DEFAULT_PLAYWRIGHT_COMMAND = ("npx", "--yes", "playwright")

ASSET_POINTER_PATTERN = re.compile(r"sediment://file_([0-9a-fA-F]{32})")
RAW_FILE_URL_PATTERN = re.compile(r"/files/([0-9a-fA-F-]{36})/raw(?:\?|$)")
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class ShareImageResolutionError(ChatGPTShareError):
    pass


def extract_generated_images(conversation: Conversation) -> list[GeneratedImage]:
    images: list[GeneratedImage] = []
    for message in conversation.messages:
        title = _message_image_title(message.metadata)
        for part in message.asset_parts("image_asset_pointer"):
            asset_pointer = part.get("asset_pointer")
            if not isinstance(asset_pointer, str):
                continue
            images.append(
                GeneratedImage(
                    message_id=message.id,
                    asset_pointer=asset_pointer,
                    file_id=asset_pointer_to_file_id(asset_pointer),
                    title=title,
                    width=_as_int(part.get("width")),
                    height=_as_int(part.get("height")),
                    size_bytes=_as_int(part.get("size_bytes")),
                    raw_part=part,
                )
            )
    return images


def resolve_generated_image_urls(
    share_url: str,
    *,
    conversation: Conversation | None = None,
    wait_for_timeout_ms: int = 8000,
    playwright_command: Iterable[str] = DEFAULT_PLAYWRIGHT_COMMAND,
) -> list[GeneratedImage]:
    conversation = conversation or parse_share_url(share_url)
    images = extract_generated_images(conversation)
    if not images:
        return []

    signed_urls = _collect_generated_image_urls_via_playwright(
        share_url,
        wait_for_timeout_ms=wait_for_timeout_ms,
        playwright_command=playwright_command,
    )

    images_by_file_id = {image.file_id: image for image in images if image.file_id}
    for signed_url in signed_urls:
        file_id = file_id_from_signed_url(signed_url)
        if file_id in images_by_file_id:
            images_by_file_id[file_id].signed_url = signed_url
        elif file_id is not None:
            images.append(
                GeneratedImage(
                    message_id=None,
                    asset_pointer=f"resolved:{file_id}",
                    file_id=file_id,
                    signed_url=signed_url,
                )
            )

    return images


def download_generated_images(
    share_url: str,
    output_dir: str | Path,
    *,
    conversation: Conversation | None = None,
    wait_for_timeout_ms: int = 8000,
    playwright_command: Iterable[str] = DEFAULT_PLAYWRIGHT_COMMAND,
) -> list[Path]:
    resolved_images = resolve_generated_image_urls(
        share_url,
        conversation=conversation,
        wait_for_timeout_ms=wait_for_timeout_ms,
        playwright_command=playwright_command,
    )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    used_names: set[str] = set()
    for index, image in enumerate(resolved_images, start=1):
        if not image.signed_url:
            continue
        data, content_type = _download_url(image.signed_url)
        extension = mimetypes.guess_extension(content_type or "") or ".bin"
        filename = _unique_filename(
            used_names,
            f"{index:02d}-{_safe_stem(image.title or image.file_id or 'generated-image')}{extension}",
        )
        path = output_path / filename
        path.write_bytes(data)
        saved_paths.append(path)
    return saved_paths


def asset_pointer_to_file_id(asset_pointer: str) -> str | None:
    match = ASSET_POINTER_PATTERN.search(asset_pointer)
    if not match:
        return None
    raw = match.group(1).lower()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def file_id_from_signed_url(url: str) -> str | None:
    match = RAW_FILE_URL_PATTERN.search(urlparse(url).path)
    if not match:
        return None
    return match.group(1).lower()


def _collect_generated_image_urls_via_playwright(
    share_url: str,
    *,
    wait_for_timeout_ms: int,
    playwright_command: Iterable[str],
) -> list[str]:
    if shutil.which(next(iter(playwright_command), "")) is None:
        raise ShareImageResolutionError(
            f"Playwright command not found: {' '.join(playwright_command)}"
        )

    with tempfile.TemporaryDirectory(prefix="chatgpt-import-share-images-") as tmpdir:
        har_path = Path(tmpdir) / "page.har"
        screenshot_path = Path(tmpdir) / "page.png"
        command = [
            *playwright_command,
            "screenshot",
            "--browser",
            "chromium",
            "--full-page",
            "--wait-for-timeout",
            str(wait_for_timeout_ms),
            "--save-har",
            str(har_path),
            share_url,
            str(screenshot_path),
        ]
        timeout_seconds = max(90, int(wait_for_timeout_ms / 1000) + 60)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise ShareImageResolutionError(
                "Playwright failed while rendering the share page. "
                "Make sure Chromium is installed with `npx playwright install chromium`.\n"
                f"{stderr}"
            )
        return _extract_signed_urls_from_har(har_path)


def _extract_signed_urls_from_har(har_path: Path) -> list[str]:
    har = json.loads(har_path.read_text(encoding="utf-8"))
    entries = har.get("log", {}).get("entries", [])
    seen: set[str] = set()
    urls: list[str] = []
    for entry in entries:
        request = entry.get("request", {})
        response = entry.get("response", {})
        url = request.get("url")
        if not isinstance(url, str):
            continue
        if "oaiusercontent.com/files/" not in url:
            continue
        if file_id_from_signed_url(url) is None:
            continue
        mime_type = response.get("content", {}).get("mimeType", "")
        if mime_type and not str(mime_type).startswith("image/"):
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _download_url(url: str) -> tuple[bytes, str | None]:
    request = Request(url, headers={"User-Agent": "chatgpt-import-share/0.1"})
    with urlopen(request, timeout=30.0) as response:
        content_type = response.headers.get_content_type()
        return response.read(), content_type


def _message_image_title(metadata: dict[str, object]) -> str | None:
    for key in ("image_gen_title", "async_task_title"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _safe_stem(value: str) -> str:
    stem = SAFE_FILENAME_PATTERN.sub("-", value.strip().lower()).strip("-")
    return stem or "generated-image"


def _unique_filename(used_names: set[str], candidate: str) -> str:
    if candidate not in used_names:
        used_names.add(candidate)
        return candidate

    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    counter = 2
    while True:
        updated = f"{stem}-{counter}{suffix}"
        if updated not in used_names:
            used_names.add(updated)
            return updated
        counter += 1
