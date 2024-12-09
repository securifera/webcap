#!/usr/bin/env python3

import sys
import orjson
import uvloop
import logging
import argparse
from pathlib import Path

from webcap.browser import Browser
from webcap.helpers import str_or_file_list

ascii_art = r"""
[1;38;5;196m         ___..._[0m
[1;38;5;197m    _,--'       "`-.[0m
[1;38;5;198m  ,'.  .            \[0m
[1;38;5;199m,/:. .     .       .'[0m
[1;38;5;200m|;..  .      _..--'[0m _       __     __    ______
[1;38;5;201m`--:...-,-'""\[0m     | |     / /__  / /_  / ____/___ _____ 
[1;38;5;165m        |:.  `.[0m    | | /| / / _ \/ __ \/ /   / __ `/ __ \
[1;38;5;129m        l;.   l[0m    | |/ |/ /  __/ /_/ / /___/ /_/ / /_/ /
[1;38;5;93m        `|:.   |[0m   |__/|__/\___/_.___/\____/\__,_/ .___/ 
[1;38;5;57m         |:.   `.,[0m                              /_/
"""


log = logging.getLogger(__name__)


def resolution_type(value):
    try:
        width, height = map(int, value.split("x"))
        if width <= 0 or height <= 0:
            raise ValueError
        return value
    except ValueError:
        raise argparse.ArgumentTypeError("Resolution must be in the format WxH, where W and H are positive integers.")


async def _main():
    default_output_dir = Path.cwd() / "screenshots"

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "urls", nargs="+", help="The URL(s) to capture - can be either single URLs or files containing URLs"
    )
    parser.add_argument("-c", "--chrome", help="Path to Chrome executable")
    parser.add_argument("-r", "--resolution", default="1400x900", type=resolution_type, help="Resolution to capture")
    parser.add_argument("-o", "--output", type=Path, default=default_output_dir, help="Output directory")
    parser.add_argument("-d", "--delay", type=float, default=3.0, help="Delay before capturing (default: 3.0 seconds)")
    parser.add_argument(
        "-f", "--full-page", action="store_true", help="Capture the full page (larger resolution images)"
    )
    parser.add_argument("-u", "--user-agent", help="User agent to use")
    parser.add_argument("-j", "--json", action="store_true", help="Output JSON")
    parser.add_argument("-p", "--proxy", help="HTTP proxy to use")
    parser.add_argument("--debug", action="store_true", help="Enable debugging")
    parser.add_argument("-s", "--silent", action="store_true", help="Silent mode")
    options = parser.parse_args()
    urls = str_or_file_list(options.urls)

    if not options.silent:
        sys.stderr.write(ascii_art)

    try:
        options.output.mkdir(parents=True, exist_ok=True)
        if not options.output.is_dir():
            raise argparse.ArgumentTypeError(f"Output path is not a directory: {options.output}")
    except Exception as e:
        raise argparse.ArgumentTypeError(f"Problem with output directory: {e}")

    if options.debug:
        import logging

        root_logger = logging.getLogger("webcap")
        root_logger.setLevel(logging.DEBUG)

    browser = Browser(options)
    await browser.start()
    async for url, webscreenshot in browser.screenshot_urls(urls):
        if webscreenshot is None:
            log.error(f"No screenshot returned for {url}")
            continue
        # write screenshot to file
        output_path = options.output / webscreenshot.filename
        with open(output_path, "wb") as f:
            f.write(webscreenshot.blob)
        # write json to stdout
        if options.json:
            webscreenshot_json = await webscreenshot.json()
            print(orjson.dumps(webscreenshot_json).decode())
        else:
            print(str(webscreenshot))

    # clean up
    await browser.stop()


def main():
    uvloop.run(_main())


if __name__ == "__main__":
    main()
