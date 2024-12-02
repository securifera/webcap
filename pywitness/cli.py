#!/usr/bin/env python3

import json
import asyncio
import argparse

from pywitness.browser import Browser


async def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="The URL to capture")
    options = parser.parse_args()

    browser = Browser()
    await browser.start()
    tab = await browser.new_tab()
    await tab.navigate(options.url)
    webscreenshot_b64 = await tab.screenshot()
    print(json.dumps({"blob": webscreenshot_b64}))

    import base64
    with open("screenshot.png", "wb") as f:
        f.write(base64.decodebytes(webscreenshot_b64.encode()))


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
