from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(slots=True)
class Message:
    id: str | None
    role: str | None
    create_time: float | None
    status: str | None
    content_type: str | None
    parts: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def text_parts(self) -> list[str]:
        return [part for part in self.parts if isinstance(part, str) and part]

    def text(self) -> str:
        return "\n\n".join(self.text_parts())

    def asset_parts(self, content_type: str | None = None) -> list[dict[str, Any]]:
        assets = [part for part in self.parts if isinstance(part, dict)]
        if content_type is None:
            return assets
        return [part for part in assets if part.get("content_type") == content_type]

    def image_asset_pointers(self) -> list[str]:
        return [
            part["asset_pointer"]
            for part in self.asset_parts("image_asset_pointer")
            if isinstance(part.get("asset_pointer"), str)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "create_time": self.create_time,
            "status": self.status,
            "content_type": self.content_type,
            "parts": self.parts,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class GeneratedImage:
    message_id: str | None
    asset_pointer: str
    file_id: str | None
    title: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    signed_url: str | None = None
    raw_part: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "asset_pointer": self.asset_pointer,
            "file_id": self.file_id,
            "title": self.title,
            "width": self.width,
            "height": self.height,
            "size_bytes": self.size_bytes,
            "signed_url": self.signed_url,
        }


@dataclass(slots=True)
class Conversation:
    title: str | None
    share_url: str | None
    conversation_id: str | None
    create_time: float | None
    update_time: float | None
    messages: list[Message] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def iter_messages(
        self,
        roles: Iterable[str] | None = None,
        include_empty: bool = False,
    ) -> Iterable[Message]:
        wanted_roles = set(roles) if roles is not None else None
        for message in self.messages:
            if wanted_roles is not None and message.role not in wanted_roles:
                continue
            if not include_empty and not message.text_parts():
                continue
            yield message

    def transcript(
        self,
        roles: Iterable[str] | None = None,
        include_empty: bool = False,
    ) -> str:
        blocks: list[str] = []
        for message in self.iter_messages(roles=roles, include_empty=include_empty):
            text = message.text()
            if text:
                blocks.append(f"[{message.role}]\n{text}")
            else:
                blocks.append(f"[{message.role}]")
        return "\n\n".join(blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "share_url": self.share_url,
            "conversation_id": self.conversation_id,
            "create_time": self.create_time,
            "update_time": self.update_time,
            "messages": [message.to_dict() for message in self.messages],
        }
