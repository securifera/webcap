<img src="https://github.com/user-attachments/assets/25912aba-690a-45e2-a6a9-2b0445e8218f" width="600"/>

[![Python Version](https://img.shields.io/badge/python-3.9+-8400ff)](https://www.python.org) [![License](https://img.shields.io/badge/license-GPLv3-8400ff.svg)](https://github.com/blacklanternsecurity/webcap/blob/dev/LICENSE) [![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff) [![Tests](https://github.com/blacklanternsecurity/webcap/actions/workflows/tests.yml/badge.svg?branch=stable)](https://github.com/blacklanternsecurity/webcap/actions?query=workflow%3A"tests") [![Codecov](https://codecov.io/gh/blacklanternsecurity/webcap/branch/dev/graph/badge.svg?token=IR5AZBDM5K)](https://codecov.io/gh/blacklanternsecurity/webcap) [![Discord](https://img.shields.io/discord/859164869970362439)](https://discord.com/invite/PZqkgxu5SA)

**WebCap** is an extremely lightweight headless browser tool. It doesn't require Selenium, Playwright, Puppeteer, or any other browser automation framework; all it needs is a working Chrome installation. Used by [BBOT](https://github.com/blacklanternsecurity/bbot).

### Installation

```bash
pipx install webcap
```

### Features

WebCap's most unique feature is its ability to capture not only the **fully-rendered DOM**, but also every snippet of **parsed Javascript** (regardless of inline or external), and the **full content** of every HTTP request + response (including Javascript API calls etc.). For convenience, it outputs directly to JSON:

#### Screenshots

![image](https://github.com/user-attachments/assets/c5a409ea-d068-45d7-a4c1-8a8cddf6c491)

#### Fully-rendered DOM

![image](https://github.com/user-attachments/assets/60dd2a80-f9c3-438e-8f00-f982c356625d)

#### Javascript Capture

![image](https://github.com/user-attachments/assets/6f960bbb-efb6-4294-a1f2-2c6181baa31a)

#### Requests + Responses

![image](https://github.com/user-attachments/assets/0f036384-a465-4579-b70a-b567daaa8113)

#### OCR

![image](https://github.com/user-attachments/assets/cffb268e-8b9b-490c-8949-39e73e73aa8a)

### Full feature list

- [x] Blazing fast screenshots
- [x] Fullscreen capture (entire scrollable page)
- [x] JSON output
- [x] Full DOM extraction
- [x] Javascript extraction (inline + external)
- [ ] Javascript extraction (environment dump)
- [x] Full network logs (incl. request/response bodies)
- [x] Title
- [x] Status code
- [x] Fuzzy (perception) hashing
- [ ] Technology detection
- [x] OCR text extraction
- [ ] Web interface

### Example Commands

```bash
# Capture screenshots of all URLs in urls.txt
webcap -u urls.txt -o ./my_screenshots

# Output to JSON, and include the fully-rendered DOM
webcap -u urls.txt --json --dom | jq

# Capture requests and responses
webcap -u urls.txt --json --requests --responses | jq

# Capture javascript
webcap -u urls.txt --json --javascript | jq

# Extract text from screenshots
webcap -u urls.txt --json --ocr | jq
```

### Use as a Python library

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

## CLI Usage (--help)

```
usage: webcap [-h] [-u URLS [URLS ...]] [-o OUTPUT] [-j] [-r RESOLUTION] [-f] [--no-screenshots] [-t THREADS] [--delay DELAY] [-U USER_AGENT] [-H HEADERS [HEADERS ...]] [-p PROXY] [-b]
              [-d] [-rs] [-rq] [-J] [--ignore-types IGNORE_TYPES [IGNORE_TYPES ...]] [--ocr] [-s] [--debug] [--no-color] [-c CHROME]

options:
  -h, --help            show this help message and exit
  -u URLS [URLS ...], --urls URLS [URLS ...]
                        URL(s) to capture, or file(s) containing URLs
  -o OUTPUT, --output OUTPUT
                        Output directory
  -j, --json            Output JSON

Screenshots:
  -r RESOLUTION, --resolution RESOLUTION
                        Resolution to capture
  -f, --full-page       Capture the full page (larger resolution images)
  --no-screenshots      Don't take screenshots

Performance:
  -t THREADS, --threads THREADS
                        Number of threads to use
  --delay DELAY         Delay before capturing (default: 3.0 seconds)

HTTP:
  -U USER_AGENT, --user-agent USER_AGENT
                        User agent to use
  -H HEADERS [HEADERS ...], --headers HEADERS [HEADERS ...]
                        Additional headers to send in format: 'Header-Name: Header-Value' (multiple supported)
  -p PROXY, --proxy PROXY
                        HTTP proxy to use

JSON Output:
  -b, --base64          Output each screenshot as base64
  -d, --dom             Capture the fully-rendered DOM
  -rs, --responses      Capture the full body of each HTTP response (including API calls etc.)
  -rq, --requests       Capture the full body of each HTTP request (including API calls etc.)
  -J, --javascript      Capture every snippet of Javascript (inline + external)
  --ignore-types IGNORE_TYPES [IGNORE_TYPES ...]
                        Ignore certain types of network requests (default: Image, Media, Font, Stylesheet)
  --ocr                 Extract text from screenshots

Misc:
  -s, --silent          Silent mode
  --debug               Enable debugging
  --no-color            Disable color output
  -c CHROME, --chrome CHROME
                        Path to Chrome executable
```
