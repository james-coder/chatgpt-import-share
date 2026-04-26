# chatgpt-import-share

Import a public ChatGPT share conversation into structured Python objects.

This is a small standalone package. Text import uses only the Python standard library. Optional generated-image URL resolution shells out to Playwright because those signed image URLs are produced while the live share page renders.

This project is unofficial and is not affiliated with OpenAI. Use it only with conversations you own, have permission to process, or that were intentionally shared publicly.

## Install

From a local checkout:

```bash
python3 -m pip install -e .[dev]
```

From git:

```bash
python3 -m pip install git+https://github.com/james-coder/chatgpt-import-share.git
```

For a Python-only agent:

```python
import subprocess
import sys

subprocess.check_call([
    sys.executable,
    "-m",
    "pip",
    "install",
    "git+https://github.com/james-coder/chatgpt-import-share.git",
])
```

## Python Usage

```python
from chatgpt_import_share import parse_share_source

conversation = parse_share_source("https://chatgpt.com/share/SHARE_ID")

print(conversation.title)
for message in conversation.iter_messages(roles=["user", "assistant"]):
    print(message.role)
    print(message.text())
```

`parse_share_source` accepts:

- a public `https://chatgpt.com/share/...` URL
- a saved share-page HTML file path
- a raw HTML string containing the share page

Machine-readable output:

```python
from chatgpt_import_share import parse_share_source

conversation = parse_share_source("share.html")
payload = conversation.to_dict()
```

Compact transcript:

```python
from chatgpt_import_share import parse_share_source

conversation = parse_share_source("share.html")
transcript = conversation.transcript(roles=["user", "assistant"])
```

If the agent cannot install packages but can see a cloned repo:

```python
import sys

sys.path.insert(0, "/path/to/chatgpt-import-share")

from chatgpt_import_share import parse_share_source
```

## Restricted Code Execution Environments

Some hosted Python code execution tools do not allow installing custom packages. The text importer has no third-party dependencies, so those tools can fetch the source files directly instead:

```python
from pathlib import Path
from urllib.request import urlopen

base_url = "https://raw.githubusercontent.com/james-coder/chatgpt-import-share/main/chatgpt_import_share"
package_dir = Path("chatgpt_import_share")
package_dir.mkdir(exist_ok=True)

for filename in ["__init__.py", "models.py", "parser.py", "images.py"]:
    data = urlopen(f"{base_url}/{filename}", timeout=30).read()
    (package_dir / filename).write_bytes(data)

from chatgpt_import_share import parse_share_source

conversation = parse_share_source("https://chatgpt.com/share/SHARE_ID")
print(conversation.transcript(roles=["user", "assistant"]))
```

## CLI

```bash
chatgpt-import-share https://chatgpt.com/share/SHARE_ID
chatgpt-import-share share.html --json
chatgpt-import-share share.html --role user --role assistant
```

Generated-image helpers:

```bash
chatgpt-import-share https://chatgpt.com/share/SHARE_ID --images-json
chatgpt-import-share https://chatgpt.com/share/SHARE_ID --download-images output-dir
```

Image URL resolution requires Node Playwright and a live share URL:

```bash
npx playwright install chromium
```

## Public API

```python
from chatgpt_import_share import (
    Conversation,
    Message,
    GeneratedImage,
    parse_share_source,
    parse_share_url,
    parse_share_file,
    parse_share_html,
    extract_generated_images,
    resolve_generated_image_urls,
    download_generated_images,
)
```

## Limits

- Only content present in the public share HTML can be recovered.
- Private sandbox files, redacted tool/plugin output, and unavailable attachments cannot be reconstructed from the share page.
- ChatGPT share-page internals can change; parser tests cover the current payload shape this package knows how to decode.

## Test

```bash
python3 -m pytest -q
```
