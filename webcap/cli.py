#!/usr/bin/env python3

import sys
import orjson
import uvloop
import logging
import argparse
from pathlib import Path
from contextlib import suppress
from webcap import defaults
from webcap.browser import Browser
from webcap.helpers import str_or_file_list, validate_urls, is_cancellation


ascii_art = r""" [1;38;5;196m         ___..._[0m
 [1;38;5;197m    _,--'       "`-.[0m
 [1;38;5;198m  ,'.  .            \[0m
 [1;38;5;199m,/: __...--'''''---..|[0m
 [1;38;5;200m|;'`   ＼\ | /／ _.-'[0m       __     __    ______
 [1;38;5;201m`--:...-,-'""\[0m     | |     / /__  / /_  / ____/__ ______ 
 [1;38;5;165m        |:.  `.[0m    | | /| / / _ \/ __ \/ /   / __' / __ \
 [1;38;5;129m        l;.   l[0m    | |/ |/ /  __/ /_/ / /___/ /_/ / /_/ /
 [1;38;5;93m        `|:.   |[0m   |__/|__/\___/_.___/\____/\__,_/ .___/ 
 [1;38;5;57m         |:.   `.,[0m                              /_/

"""


END = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[38;5;47m"
BLUE = "\033[38;5;39m"
PURPLE = "\033[38;5;177m"
RED = "\033[38;5;196m"


log = logging.getLogger(__name__)


def resolution_type(value):
    try:
        width, height = map(int, value.split("x"))
        if width <= 0 or height <= 0:
            raise ValueError
        return value
    except ValueError:
        raise argparse.ArgumentTypeError("Resolution must be in the format WxH, where W and H are positive integers.")


async def _cli():
    default_output_dir = Path.cwd() / "screenshots"

    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--urls", nargs="+", help="URL(s) to capture, or file(s) containing URLs")

    output_options = parser.add_argument_group("Output")
    output_options.add_argument("-o", "--output", type=Path, default=default_output_dir, help="Output directory")
    output_options.add_argument(
        "-r", "--resolution", default=defaults.resolution, type=resolution_type, help="Resolution to capture"
    )
    output_options.add_argument(
        "-f", "--full-page", action="store_true", help="Capture the full page (larger resolution images)"
    )
    output_options.add_argument(
        "--ignore-types",
        nargs="+",
        default=defaults.ignored_types,
        help=f"Ignore certain types of network requests (default: {', '.join(defaults.ignored_types)})",
    )

    performance_options = parser.add_argument_group("Performance")
    performance_options.add_argument(
        "-t", "--threads", type=int, default=defaults.threads, help="Number of threads to use"
    )
    performance_options.add_argument(
        "--delay", type=float, default=defaults.delay, help="Delay before capturing (default: 3.0 seconds)"
    )

    http_options = parser.add_argument_group("HTTP")
    http_options.add_argument("-U", "--user-agent", default=defaults.user_agent, help="User agent to use")
    http_options.add_argument(
        "-H",
        "--headers",
        nargs="+",
        help="Additional headers to send in format: 'Header-Name: Header-Value' (multiple supported)",
    )
    http_options.add_argument("-p", "--proxy", help="HTTP proxy to use")

    json_options = parser.add_argument_group("JSON Output")
    json_options.add_argument("-b", "--base64", action="store_true", help="Output each screenshot as base64")
    json_options.add_argument("-j", "--json", action="store_true", help="Output JSON")
    json_options.add_argument("-d", "--dom", action="store_true", help="Capture the fully-rendered DOM")
    json_options.add_argument(
        "-Rs",
        "--responses",
        action="store_true",
        help="Capture the full body of each HTTP response (including API calls etc.)",
    )
    json_options.add_argument(
        "-Rq",
        "--requests",
        action="store_true",
        help="Capture the full body of each HTTP request (including API calls etc.)",
    )
    json_options.add_argument(
        "-J", "--javascript", action="store_true", help="Capture every snippet of Javascript (inline + external)"
    )

    misc_options = parser.add_argument_group("Misc")
    misc_options.add_argument("-s", "--silent", action="store_true", help="Silent mode")
    misc_options.add_argument("--debug", action="store_true", help="Enable debugging")
    misc_options.add_argument("--no-color", action="store_true", help="Disable color output")
    misc_options.add_argument("-c", "--chrome", help="Path to Chrome executable")

    options = parser.parse_args()
    urls = str_or_file_list(options.urls)
    urls = list(validate_urls(urls))

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

    browser = Browser.from_argparse(options)
    try:
        await browser.start()
        async for url, webscreenshot in browser.screenshot_urls(urls):
            if webscreenshot is None or not webscreenshot.status_code:
                log.info(f"No screenshot returned for {url} -> {webscreenshot}")
                continue
            # write screenshot to file
            output_path = options.output / webscreenshot.filename
            with open(output_path, "wb") as f:
                f.write(webscreenshot.blob)
            # write json to stdout
            if options.json:
                webscreenshot_json = await webscreenshot.json()
                outline = orjson.dumps(webscreenshot_json).decode()
            else:
                if options.no_color:
                    outline = (
                        f"[{webscreenshot.status_code}]\t{webscreenshot.title[:30]:<30}\t{webscreenshot.final_url}"
                    )
                else:
                    str_status = str(webscreenshot.status_code)
                    if str_status.startswith("2"):
                        color = f"{BOLD}{GREEN}"
                    elif str_status.startswith("3"):
                        color = f"{BOLD}{BLUE}"
                    elif str_status.startswith("4"):
                        color = f"{BOLD}{PURPLE}"
                    else:
                        color = f"{BOLD}{RED}"
                    outline = f"[{color}{webscreenshot.status_code}{END}]\t{webscreenshot.title[:30]:<30}\t{webscreenshot.final_url}"
            print(outline, flush=True)
    finally:
        with suppress(Exception):
            await browser.stop()


async def _main():
    try:
        await _cli()
    except BaseException as e:
        if is_cancellation(e):
            sys.exit(1)
        elif not isinstance(e, SystemExit):
            import traceback

            log.critical(f"Unhandled error: {e}")
            log.critical(traceback.format_exc())
            sys.exit(1)


def main():
    uvloop.run(_main())


if __name__ == "__main__":
    main()
