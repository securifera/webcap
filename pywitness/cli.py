#!/usr/bin/env python3

import orjson
import asyncio
import argparse

from pywitness.browser import Browser


def resolution_type(value):
    try:
        width, height = map(int, value.split("x"))
        if width <= 0 or height <= 0:
            raise ValueError
        return value
    except ValueError:
        raise argparse.ArgumentTypeError("Resolution must be in the format WxH, where W and H are positive integers.")


async def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="The URL to capture")
    parser.add_argument("-c", "--chrome", help="Path to Chrome executable")
    parser.add_argument("-r", "--resolution", default="800x600", type=resolution_type, help="Resolution to capture")
    parser.add_argument(
        "-f", "--full-page", action="store_true", help="Capture the full page (larger resolution images)"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debugging")
    options = parser.parse_args()

    if options.debug:
        import logging

        root_logger = logging.getLogger("pywitness")
        root_logger.setLevel(logging.DEBUG)

    browser = Browser(options)
    await browser.start()
    webscreenshot_b64 = await browser.screenshot(options.url)
    print(orjson.dumps({"blob": webscreenshot_b64}))

    import base64

    with open("screenshot.png", "wb") as f:
        f.write(base64.decodebytes(webscreenshot_b64.encode()))

    # clean up
    await browser.stop()


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
