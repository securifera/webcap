<img src="https://github.com/user-attachments/assets/16505254-121d-4e21-9e04-270f3a46fee4" width="600"/>

**WebCap** is an extremely lightweight web screenshot tool written in Python. It does not require selenium, playwright, or any other browser automation framework. It only needs a working Chrome installation.

Features:

- [x] Blazing fast screenshots
- [x] Full DOM extraction
- [x] Status code
- [x] Title
- [x] JSON output
- [x] Fuzzy hashing
- [ ] Technology detection
- [ ] Javascript extraction (environment dump)
- [ ] OCR text extraction
- [ ] Full network logs

## Example Usage - CLI

```bash
webcap http://example.com
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
