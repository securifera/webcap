# Pywitness

<img src="https://github.com/user-attachments/assets/b1d2a3b7-8546-473a-9dd0-564696622cb3" width="400"/>

Pywitness is an extremely lightweight web screenshot tool written in Python. It does not require selenium, playwright, or any other browser automation framework. All it needs is a working installation of Chrome.

Features:

- [ ] Blazing fast screenshots of unlimited URLs
- [ ] Full DOM extraction
- [ ] Status code
- [ ] Title extraction
- [ ] Fuzzy hashing
- [ ] Technology detection
- [ ] Javascript extraction (environment dump)

## Example Usage - CLI

```bash
pywitness http://example.com
```

## Example Usage - Python

```python
import base64
from pywitness import Browser

async def main():
    # create a browser instance
    browser = Browser()
    # start the browser
    await browser.start()
    # take a screenshot
    encoded_screenshot = await browser.screenshot("http://example.com")
    # save the screenshot to a file
    with open("screenshot.png", "wb") as f:
        f.write(base64.b64decode(encoded_screenshot))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```
