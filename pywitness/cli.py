#!/usr/bin/env python3

import orjson
import asyncio
import argparse

from pywitness.browser import Browser


async def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="The URL to capture")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debugging")
    options = parser.parse_args()

    if options.debug:
        import logging

        root_logger = logging.getLogger("pywitness")
        root_logger.setLevel(logging.DEBUG)

    browser = Browser()
    webscreenshot_b64 = await browser.screenshot(options.url)
    print(orjson.dumps({"blob": webscreenshot_b64}))

    import base64

    with open("screenshot.png", "wb") as f:
        f.write(base64.decodebytes(webscreenshot_b64.encode()))


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
