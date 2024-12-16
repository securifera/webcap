<img src="https://github.com/user-attachments/assets/1cab9ac6-01d8-40dc-a3d4-79127efdbf1b" width="600"/>

[![Python Version](https://img.shields.io/badge/python-3.9+-8400ff)](https://www.python.org) [![License](https://img.shields.io/badge/license-GPLv3-8400ff.svg)](https://github.com/blacklanternsecurity/webcap/blob/dev/LICENSE) [![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff) [![Tests](https://github.com/blacklanternsecurity/webcap/actions/workflows/tests.yml/badge.svg?branch=stable)](https://github.com/blacklanternsecurity/webcap/actions?query=workflow%3A"tests") [![Codecov](https://codecov.io/gh/blacklanternsecurity/webcap/branch/dev/graph/badge.svg?token=IR5AZBDM5K)](https://codecov.io/gh/blacklanternsecurity/webcap) [![Discord](https://img.shields.io/discord/859164869970362439)](https://discord.com/invite/PZqkgxu5SA)

**WebCap** is an extremely lightweight headless browser tool capable of web screenshots and more. It doesn't require Selenium, Playwright, Puppeteer, or any other browser automation framework; all it needs is a working Chrome installation.

```bash
pipx install webcap
```

WebCap's most unique feature is its ability to capture not only the **fully-rendered DOM**, but also every snippet of **parsed Javascript** (regardless of inline or external), and the **full response body** of every HTTP request. For convenience, it outputs directly to JSON:

### Fully-rendered DOM

![image](https://github.com/user-attachments/assets/60dd2a80-f9c3-438e-8f00-f982c356625d)

### Javascript Capture

![image](https://github.com/user-attachments/assets/9360ea5c-bed7-4ede-94a1-49e093bf84e9)

### Requests + Responses



### All features:

- [x] Blazing fast screenshots
- [x] JSON output
- [x] Full DOM extraction
- [x] Javascript extraction (inline + external)
- [ ] Javascript extraction (environment dump)
- [x] Full network logs (incl. request/response bodies)
- [x] Status code
- [x] Title
- [x] Fuzzy hashing
- [ ] Technology detection
- [ ] OCR text extraction
- [x] Full network logs

## Example Usage - CLI

```bash
webcap -u http://example.com urls.txt -o ./my_screenshots
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

## CLI Usage (--help)

```
usage: webcap [-h] [-u URLS [URLS ...]] [-o OUTPUT] [-r RESOLUTION] [-f] [-t THREADS]
              [--delay DELAY] [-U USER_AGENT] [-H HEADERS [HEADERS ...]] [-p PROXY]
              [-b] [-j] [-d] [-Rs] [-Rq] [-J] [-s] [--debug] [--no-color] [-c CHROME]

options:
  -h, --help            show this help message and exit
  -u URLS [URLS ...], --urls URLS [URLS ...]
                        URL(s) to capture, or file(s) containing URLs

Output:
  -o OUTPUT, --output OUTPUT
                        Output directory
  -r RESOLUTION, --resolution RESOLUTION
                        Resolution to capture
  -f, --full-page       Capture the full page (larger resolution images)

Performance:
  -t THREADS, --threads THREADS
                        Number of threads to use
  --delay DELAY         Delay before capturing (default: 3.0 seconds)

HTTP:
  -U USER_AGENT, --user-agent USER_AGENT
                        User agent to use
  -H HEADERS [HEADERS ...], --headers HEADERS [HEADERS ...]
                        Additional headers to send in format: 'Header-Name: Header-
                        Value' (multiple supported)
  -p PROXY, --proxy PROXY
                        HTTP proxy to use

JSON Output:
  -b, --base64          Output each screenshot as base64
  -j, --json            Output JSON
  -d, --dom             Capture the fully-rendered DOM
  -Rs, --responses      Capture the full body of each HTTP response (including API
                        calls etc.)
  -Rq, --requests       Capture the full body of each HTTP request (including API
                        calls etc.)
  -J, --javascript      Capture every snippet of Javascript (inline + external)

Misc:
  -s, --silent          Silent mode
  --debug               Enable debugging
  --no-color            Disable color output
  -c CHROME, --chrome CHROME
                        Path to Chrome executable
```
