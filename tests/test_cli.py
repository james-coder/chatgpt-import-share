from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from chatgpt_import_share.cli import main
from chatgpt_import_share.models import Conversation, Message


def _conversation(text: str = "Please extract this.\n\nHere is the answer.") -> Conversation:
    return Conversation(
        title="Example Share",
        share_url="share.html",
        conversation_id="conversation-123",
        create_time=None,
        update_time=None,
        messages=[
            Message(
                id="msg-user",
                role="user",
                create_time=None,
                status="finished_successfully",
                content_type="text",
                parts=["Please extract this."],
                metadata={},
            ),
            Message(
                id="msg-assistant",
                role="assistant",
                create_time=None,
                status="finished_successfully",
                content_type="text",
                parts=[text],
                metadata={},
            ),
        ],
    )


class CliTests(unittest.TestCase):
    def test_ai_studio_output_is_paste_ready(self) -> None:
        with patch("chatgpt_import_share.cli.parse_share_source", return_value=_conversation()):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(["share.html", "--ai-studio", "--task", "Summarize it."])

        output = stdout.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("Summarize it.", output)
        self.assertIn("Title: Example Share", output)
        self.assertIn("BEGIN CHATGPT SHARE TRANSCRIPT", output)
        self.assertIn("[user]\nPlease extract this.", output)
        self.assertIn("END CHATGPT SHARE TRANSCRIPT", output)

    def test_output_writes_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "conversation.md"
            with patch("chatgpt_import_share.cli.parse_share_source", return_value=_conversation()):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    result = main(["share.html", "--output", str(output_path)])

            self.assertEqual(result, 0)
            self.assertEqual(stdout.getvalue(), "")
            output = output_path.read_text(encoding="utf-8")

        self.assertTrue(output.startswith("# Example Share"))
        self.assertIn("[assistant]", output)

    def test_split_dir_writes_paste_chunks(self) -> None:
        long_text = " ".join(f"word{i}" for i in range(80))
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("chatgpt_import_share.cli.parse_share_source", return_value=_conversation(long_text)):
                result = main(
                    [
                        "share.html",
                        "--split-dir",
                        tmpdir,
                        "--max-chars",
                        "120",
                        "--task",
                        "List open tasks.",
                    ]
                )

            paths = sorted(Path(tmpdir).glob("chatgpt-share-part-*.md"))
            contents = [path.read_text(encoding="utf-8") for path in paths]

        self.assertEqual(result, 0)
        self.assertGreater(len(paths), 1)
        self.assertIn("wait for the remaining chunks", contents[0])
        self.assertIn("This is the final chunk", contents[-1])
        self.assertIn("List open tasks.", contents[-1])


if __name__ == "__main__":
    unittest.main()
