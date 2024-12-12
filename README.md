<img src="https://github.com/user-attachments/assets/16505254-121d-4e21-9e04-270f3a46fee4" width="600"/>

[![Python Version](https://img.shields.io/badge/python-3.9+-8400ff)](https://www.python.org) [![License](https://img.shields.io/badge/license-GPLv3-8400ff.svg)](https://github.com/blacklanternsecurity/webcap/blob/dev/LICENSE) [![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff) [![Tests](https://github.com/blacklanternsecurity/webcap/actions/workflows/tests.yml/badge.svg?branch=stable)](https://github.com/blacklanternsecurity/webcap/actions?query=workflow%3A"tests") [![Codecov](https://codecov.io/gh/blacklanternsecurity/webcap/branch/dev/graph/badge.svg?token=IR5AZBDM5K)](https://codecov.io/gh/blacklanternsecurity/webcap) [![Discord](https://img.shields.io/discord/859164869970362439)](https://discord.com/invite/PZqkgxu5SA)

**WebCap** is an extremely lightweight web screenshot tool written in Python. It does not require selenium, playwright, or any other browser automation framework. It only needs a working Chrome installation.

Features:

- [x] Blazing fast screenshots
- [x] Full DOM extraction
- [x] Status code
- [x] Title
- [x] JSON output
- [x] Fuzzy hashing
- [ ] Technology detection
- [x] Javascript extraction (script text)
- [ ] Javascript extraction (environment dump)
- [ ] OCR text extraction
- [ ] Full network logs

## Example Usage - CLI

```bash
webcap -u http://example.com
```

## Example Usage - Python

```python
import base64
from webcap import Browser

async def main():
    # create a browser instance
    browser = Browser()
    # start the browser
    await browser.start()
    # take a screenshot
    webscreenshot = await browser.screenshot("http://example.com")
    # save the screenshot to a file
    with open("screenshot.png", "wb") as f:
        f.write(webscreenshot.blob)
    # stop the browser
    await browser.stop()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```
