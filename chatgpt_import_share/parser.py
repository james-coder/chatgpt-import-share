from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import Conversation, Message

USER_AGENT = "chatgpt-import-share/0.1"
ENQUEUE_PATTERN = re.compile(r'streamController\.enqueue\("(.*?)"\);', re.DOTALL)


class ChatGPTShareError(RuntimeError):
    pass


class ShareFetchError(ChatGPTShareError):
    pass


class ShareParseError(ChatGPTShareError):
    pass


def fetch_share_html(url: str, timeout: float = 30.0) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset("utf-8")
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise ShareFetchError(f"Failed to fetch share page: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ShareFetchError(f"Failed to fetch share page: {exc.reason}") from exc


def parse_share_url(url: str, timeout: float = 30.0) -> Conversation:
    html = fetch_share_html(url, timeout=timeout)
    return parse_share_html(html, share_url=url)


def parse_share_source(source: str | Path, timeout: float = 30.0) -> Conversation:
    """Parse a ChatGPT share URL, saved HTML file, or raw HTML string."""
    if isinstance(source, Path):
        return parse_share_file(source)

    if _looks_like_url(source):
        return parse_share_url(source, timeout=timeout)

    if _looks_like_html(source):
        return parse_share_html(source)

    return parse_share_file(source)


def parse_share_file(path: str | Path) -> Conversation:
    file_path = Path(path)
    html = file_path.read_text(encoding="utf-8")
    return parse_share_html(html, share_url=str(file_path))


def parse_share_html(html: str, share_url: str | None = None) -> Conversation:
    root = _load_root_object(html)
    share_data = _extract_share_data(root)
    messages = _extract_messages(share_data)
    return Conversation(
        title=share_data.get("title"),
        share_url=share_url,
        conversation_id=share_data.get("conversation_id"),
        create_time=_as_float(share_data.get("create_time")),
        update_time=_as_float(share_data.get("update_time")),
        messages=messages,
        raw=share_data,
    )


def _load_root_object(html: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for payload in _extract_payload_strings(html):
        try:
            array = json.loads(payload)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(array, list) or not array:
            continue
        root = _resolve_root(array)
        if isinstance(root, dict) and "loaderData" in root:
            return root
    if last_error is not None:
        raise ShareParseError(f"Found stream payload but could not decode it: {last_error}") from last_error
    raise ShareParseError("Could not find a ChatGPT share payload in the HTML.")


def _extract_payload_strings(html: str) -> list[str]:
    payloads: list[str] = []
    for match in ENQUEUE_PATTERN.finditer(html):
        raw = match.group(1)
        try:
            payloads.append(ast.literal_eval(f'"{raw}"'))
        except (SyntaxError, ValueError):
            continue
    return payloads


def _resolve_root(array: list[Any]) -> Any:
    memo: dict[int, Any] = {}
    in_progress: set[int] = set()

    def resolve_value(value: Any) -> Any:
        if isinstance(value, int):
            if value < 0:
                return None
            if value >= len(array):
                return value
            return resolve_index(value)
        if isinstance(value, list):
            return [resolve_value(item) for item in value]
        if isinstance(value, dict):
            return resolve_dict(value)
        return value

    def resolve_dict(obj: dict[str, Any]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in obj.items():
            if isinstance(key, str) and key.startswith("_") and key[1:].isdigit():
                resolved_key = resolve_index(int(key[1:]))
            else:
                resolved_key = key
            resolved[resolved_key] = resolve_value(value)
        return resolved

    def resolve_index(index: int) -> Any:
        if index in memo:
            return memo[index]
        if index in in_progress:
            return {"$ref": index}

        in_progress.add(index)
        item = array[index]
        if isinstance(item, dict):
            resolved = {}
            memo[index] = resolved
            resolved.update(resolve_dict(item))
        elif isinstance(item, list):
            resolved = []
            memo[index] = resolved
            resolved.extend(resolve_value(entry) for entry in item)
        else:
            resolved = item
            memo[index] = resolved
        in_progress.remove(index)
        return resolved

    return resolve_index(0)


def _extract_share_data(root: dict[str, Any]) -> dict[str, Any]:
    loader_data = root.get("loaderData")
    if not isinstance(loader_data, dict):
        raise ShareParseError("Decoded payload did not contain loaderData.")

    route_key = next(
        (key for key in loader_data if isinstance(key, str) and key.startswith("routes/share")),
        None,
    )
    if route_key is None:
        raise ShareParseError("Decoded payload did not contain a share route.")

    route_data = loader_data.get(route_key)
    if not isinstance(route_data, dict):
        raise ShareParseError("Share route data was not an object.")

    server_response = route_data.get("serverResponse")
    if not isinstance(server_response, dict):
        raise ShareParseError("Share route did not contain serverResponse.")

    data = server_response.get("data")
    if not isinstance(data, dict):
        raise ShareParseError("Share route did not contain conversation data.")

    return data


def _extract_messages(share_data: dict[str, Any]) -> list[Message]:
    nodes = share_data.get("linear_conversation")
    if not isinstance(nodes, list):
        mapping = share_data.get("mapping")
        if isinstance(mapping, dict):
            nodes = list(mapping.values())
        else:
            nodes = []

    messages: list[Message] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        message = _message_from_node(node)
        if message is not None:
            messages.append(message)
    return messages


def _message_from_node(node: dict[str, Any]) -> Message | None:
    message = node.get("message")
    if not isinstance(message, dict):
        return None

    author = message.get("author")
    content = message.get("content")
    metadata = message.get("metadata")

    role = author.get("role") if isinstance(author, dict) else None
    content_type = content.get("content_type") if isinstance(content, dict) else None
    normalized_parts = _extract_parts(content)

    return Message(
        id=node.get("id"),
        role=role if isinstance(role, str) else None,
        create_time=_as_float(message.get("create_time")),
        status=message.get("status") if isinstance(message.get("status"), str) else None,
        content_type=content_type if isinstance(content_type, str) else None,
        parts=normalized_parts,
        metadata=metadata if isinstance(metadata, dict) else {},
        raw=node,
    )


def _extract_parts(content: dict[str, Any] | None) -> list[Any]:
    if not isinstance(content, dict):
        return []

    parts = content.get("parts")
    if isinstance(parts, list):
        return parts
    if parts is not None:
        return [parts]

    text = content.get("text")
    if isinstance(text, str):
        return [text]

    return []


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _looks_like_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _looks_like_html(source: str) -> bool:
    stripped = source.lstrip()
    return (
        stripped.startswith("<!DOCTYPE")
        or stripped.startswith("<html")
        or "streamController.enqueue(" in source
    )
