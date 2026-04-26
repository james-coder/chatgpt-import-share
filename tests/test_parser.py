from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chatgpt_import_share.images import (
    asset_pointer_to_file_id,
    extract_generated_images,
    file_id_from_signed_url,
    resolve_generated_image_urls,
)
from chatgpt_import_share import (
    parse_share_file,
    parse_share_html,
    parse_share_source,
    parse_share_url,
)


def _build_test_html() -> str:
    items: list[object | None] = [None]

    def add(value: object) -> int:
        items.append(value)
        return len(items) - 1

    def ref_object(pairs: dict[int, int]) -> dict[str, int]:
        return {f"_{key}": value for key, value in pairs.items()}

    key_loader_data = add("loaderData")
    key_route = add("routes/share.$shareId.($action)")
    key_server_response = add("serverResponse")
    key_data = add("data")
    key_title = add("title")
    value_title = add("Example Share")
    key_conversation_id = add("conversation_id")
    value_conversation_id = add("conversation-123")
    key_create_time = add("create_time")
    value_create_time = add(1.0)
    key_update_time = add("update_time")
    value_update_time = add(2.0)
    key_linear_conversation = add("linear_conversation")
    key_mapping = add("mapping")
    key_id = add("id")
    key_message = add("message")
    key_author = add("author")
    key_role = add("role")
    key_content = add("content")
    key_content_type = add("content_type")
    key_parts = add("parts")
    key_metadata = add("metadata")
    key_status = add("status")
    value_text = add("text")
    value_finished = add("finished_successfully")
    value_user = add("user")
    value_assistant = add("assistant")
    value_system = add("system")
    value_user_id = add("msg-user")
    value_assistant_id = add("msg-assistant")
    value_system_id = add("msg-system")
    value_user_text = add("Please extract the notes.")
    value_assistant_text = add("Here are the notes.")
    value_empty_text = add("")

    empty_metadata = add({})
    user_parts = add([value_user_text])
    assistant_parts = add([value_assistant_text])
    empty_parts = add([value_empty_text])

    user_content = add(
        ref_object(
            {
                key_content_type: value_text,
                key_parts: user_parts,
            }
        )
    )
    assistant_content = add(
        ref_object(
            {
                key_content_type: value_text,
                key_parts: assistant_parts,
            }
        )
    )
    system_content = add(
        ref_object(
            {
                key_content_type: value_text,
                key_parts: empty_parts,
            }
        )
    )

    user_author = add(ref_object({key_role: value_user}))
    assistant_author = add(ref_object({key_role: value_assistant}))
    system_author = add(ref_object({key_role: value_system}))

    user_message = add(
        ref_object(
            {
                key_author: user_author,
                key_content: user_content,
                key_metadata: empty_metadata,
                key_status: value_finished,
                key_create_time: value_create_time,
            }
        )
    )
    assistant_message = add(
        ref_object(
            {
                key_author: assistant_author,
                key_content: assistant_content,
                key_metadata: empty_metadata,
                key_status: value_finished,
                key_create_time: value_update_time,
            }
        )
    )
    system_message = add(
        ref_object(
            {
                key_author: system_author,
                key_content: system_content,
                key_metadata: empty_metadata,
                key_status: value_finished,
                key_create_time: value_create_time,
            }
        )
    )

    system_node = add(ref_object({key_id: value_system_id, key_message: system_message}))
    user_node = add(ref_object({key_id: value_user_id, key_message: user_message}))
    assistant_node = add(ref_object({key_id: value_assistant_id, key_message: assistant_message}))

    linear_conversation = add([system_node, user_node, assistant_node])

    mapping_key_system = add("node-system")
    mapping_key_user = add("node-user")
    mapping_key_assistant = add("node-assistant")
    mapping = add(
        ref_object(
            {
                mapping_key_system: system_node,
                mapping_key_user: user_node,
                mapping_key_assistant: assistant_node,
            }
        )
    )

    share_data = add(
        ref_object(
            {
                key_title: value_title,
                key_conversation_id: value_conversation_id,
                key_create_time: value_create_time,
                key_update_time: value_update_time,
                key_linear_conversation: linear_conversation,
                key_mapping: mapping,
            }
        )
    )

    server_response = add(ref_object({key_data: share_data}))
    route_data = add(ref_object({key_server_response: server_response}))
    loader_data = add(ref_object({key_route: route_data}))
    items[0] = ref_object({key_loader_data: loader_data})

    payload = json.dumps(items)
    escaped_payload = json.dumps(payload)[1:-1]
    return (
        "<html><body>"
        f'<script>window.__reactRouterContext.streamController.enqueue("{escaped_payload}");</script>'
        "</body></html>"
    )


class ParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = _build_test_html()

    def test_parse_share_html_extracts_conversation(self) -> None:
        conversation = parse_share_html(self.html, share_url="https://chatgpt.com/share/test")

        self.assertEqual(conversation.title, "Example Share")
        self.assertEqual(conversation.conversation_id, "conversation-123")
        self.assertEqual([message.role for message in conversation.messages], ["system", "user", "assistant"])
        self.assertEqual(conversation.messages[1].text(), "Please extract the notes.")
        self.assertEqual(conversation.messages[2].text(), "Here are the notes.")

    def test_transcript_filters_empty_messages(self) -> None:
        conversation = parse_share_html(self.html)

        transcript = conversation.transcript()

        self.assertNotIn("[system]", transcript)
        self.assertIn("[user]", transcript)
        self.assertIn("[assistant]", transcript)

    def test_parse_share_file_reads_local_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "share.html"
            path.write_text(self.html, encoding="utf-8")

            conversation = parse_share_file(path)

        self.assertEqual(conversation.title, "Example Share")

    def test_parse_share_source_accepts_saved_html_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "share.html"
            path.write_text(self.html, encoding="utf-8")

            conversation = parse_share_source(str(path))

        self.assertEqual(conversation.title, "Example Share")

    def test_parse_share_source_accepts_raw_html(self) -> None:
        conversation = parse_share_source(self.html)

        self.assertEqual(conversation.title, "Example Share")

    def test_parse_share_url_fetches_html(self) -> None:
        class FakeResponse:
            def __init__(self, html: str) -> None:
                self._body = html.encode("utf-8")
                self.headers = self

            def get_content_charset(self, default: str) -> str:
                return default

            def read(self) -> bytes:
                return self._body

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        with patch("chatgpt_import_share.parser.urlopen", return_value=FakeResponse(self.html)):
            conversation = parse_share_url("https://chatgpt.com/share/test")

        self.assertEqual(conversation.title, "Example Share")

    def test_message_helpers_support_asset_parts(self) -> None:
        payload = [
            {
                "loaderData": {
                    "routes/share.$shareId.($action)": {
                        "serverResponse": {
                            "data": {
                                "title": "Assets",
                                "linear_conversation": [
                                    {
                                        "id": "tool-msg",
                                        "message": {
                                            "author": {"role": "tool"},
                                            "content": {
                                                "content_type": "multimodal_text",
                                                "parts": [
                                                    {
                                                        "content_type": "image_asset_pointer",
                                                        "asset_pointer": "sediment://file_123",
                                                    }
                                                ],
                                            },
                                            "metadata": {},
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        ]
        html = _payload_to_html(payload)

        conversation = parse_share_html(html)

        self.assertEqual(conversation.messages[0].image_asset_pointers(), ["sediment://file_123"])

    def test_code_content_text_is_preserved_as_message_text(self) -> None:
        payload = [
            {
                "loaderData": {
                    "routes/share.$shareId.($action)": {
                        "serverResponse": {
                            "data": {
                                "title": "Code",
                                "linear_conversation": [
                                    {
                                        "id": "assistant-msg",
                                        "message": {
                                            "author": {"role": "assistant"},
                                            "content": {
                                                "content_type": "code",
                                                "language": "json",
                                                "text": '{"size":"1024x1024"}',
                                            },
                                            "metadata": {},
                                            "status": "finished_successfully",
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        ]
        html = _payload_to_html(payload)

        conversation = parse_share_html(html)

        self.assertEqual(conversation.messages[0].text(), '{"size":"1024x1024"}')

    def test_generated_image_helpers_extract_and_match_ids(self) -> None:
        payload = [
            {
                "loaderData": {
                    "routes/share.$shareId.($action)": {
                        "serverResponse": {
                            "data": {
                                "title": "Assets",
                                "linear_conversation": [
                                    {
                                        "id": "tool-msg",
                                        "message": {
                                            "author": {"role": "tool"},
                                            "content": {
                                                "content_type": "multimodal_text",
                                                "parts": [
                                                    {
                                                        "content_type": "image_asset_pointer",
                                                        "asset_pointer": "sediment://file_00000000f6f0722fa9513c532f51a56c?shared_conversation_id=abc",
                                                        "width": 1024,
                                                        "height": 1536,
                                                        "size_bytes": 1314240,
                                                    }
                                                ],
                                            },
                                            "metadata": {
                                                "image_gen_title": "Generated image"
                                            },
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        ]
        conversation = parse_share_html(_payload_to_html(payload))

        images = extract_generated_images(conversation)

        self.assertEqual(len(images), 1)
        self.assertEqual(
            images[0].file_id,
            "00000000-f6f0-722f-a951-3c532f51a56c",
        )
        self.assertEqual(images[0].title, "Generated image")
        self.assertEqual(
            asset_pointer_to_file_id(images[0].asset_pointer),
            "00000000-f6f0-722f-a951-3c532f51a56c",
        )

    def test_resolve_generated_image_urls_uses_signed_url_matches(self) -> None:
        payload = [
            {
                "loaderData": {
                    "routes/share.$shareId.($action)": {
                        "serverResponse": {
                            "data": {
                                "title": "Assets",
                                "linear_conversation": [
                                    {
                                        "id": "tool-msg",
                                        "message": {
                                            "author": {"role": "tool"},
                                            "content": {
                                                "content_type": "multimodal_text",
                                                "parts": [
                                                    {
                                                        "content_type": "image_asset_pointer",
                                                        "asset_pointer": "sediment://file_00000000f6f0722fa9513c532f51a56c?shared_conversation_id=abc",
                                                    }
                                                ],
                                            },
                                            "metadata": {},
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        ]
        conversation = parse_share_html(_payload_to_html(payload))
        signed_url = (
            "https://sdmntprnorthcentralus.oaiusercontent.com/files/"
            "00000000-f6f0-722f-a951-3c532f51a56c/raw?sig=test"
        )

        with patch(
            "chatgpt_import_share.images._collect_generated_image_urls_via_playwright",
            return_value=[signed_url],
        ):
            images = resolve_generated_image_urls(
                "https://chatgpt.com/share/test",
                conversation=conversation,
            )

        self.assertEqual(images[0].signed_url, signed_url)
        self.assertEqual(file_id_from_signed_url(signed_url), "00000000-f6f0-722f-a951-3c532f51a56c")


def _payload_to_html(payload: list[object]) -> str:
    escaped_payload = json.dumps(json.dumps(payload))[1:-1]
    return (
        "<html><body>"
        f'<script>window.__reactRouterContext.streamController.enqueue("{escaped_payload}");</script>'
        "</body></html>"
    )


if __name__ == "__main__":
    unittest.main()
