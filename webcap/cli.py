#!/usr/bin/env python3

import sys
import typer
import orjson
import uvloop
import logging
import argparse
from pathlib import Path
from typing import Annotated
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


default_output_dir = Path.cwd() / "screenshots"


app = typer.Typer()
global_options = {
    "silent": False,
    "debug": False,
    "no_color": False,
}


@app.callback()
def _global_options(
    silent: bool = False,
    debug: bool = False,
    no_color: bool = False,
):
    global_options["silent"] = silent
    global_options["debug"] = debug
    global_options["no_color"] = no_color


@app.command(help="Start the webcap HTTP server (GUI for browsing screenshots)")
def server(
    # listen address
    listen_address: Annotated[
        str, typer.Option("--listen-address", "-l", help="Listen address", metavar="ADDRESS")
    ] = "0.0.0.0",
    # listen port
    listen_port: Annotated[int, typer.Option("--listen-port", "-p", help="Listen port", metavar="PORT")] = 8000,
    # auto reload
    auto_reload: Annotated[
        bool, typer.Option("--auto-reload", "-r", help="Auto reload the server when files change")
    ] = True,
):
    print(listen_address, listen_port)


@app.command(help="Screenshot URLs")
def scan(
    # main options
    urls: Annotated[list[str], typer.Argument(help="URL(s) to capture, or file(s) containing URLs", metavar="URLS")],
    json: Annotated[bool, typer.Option("-j", "--json", help="Output JSON")] = False,
    chrome_path: Annotated[str, typer.Option("-c", "--chrome", help="Path to Chrome executable")] = None,
    output_dir: Annotated[
        Path, typer.Option("-o", "--output", help="Output directory", metavar="OUTPUT_DIR")
    ] = default_output_dir,
    # screenshot options
    resolution: Annotated[
        str,
        typer.Option(
            "-r", "--resolution", help="Resolution to capture", metavar="RESOLUTION", rich_help_panel="Screenshots"
        ),
    ] = defaults.resolution,
    full_page: Annotated[
        bool,
        typer.Option(
            "-f", "--full-page", help="Capture the full page (larger resolution images)", rich_help_panel="Screenshots"
        ),
    ] = False,
    no_screenshots: Annotated[
        bool,
        typer.Option(
            "--no-screenshots",
            help="Only visit the sites; don't capture screenshots (useful with -j/--json)",
            rich_help_panel="Screenshots",
        ),
    ] = False,
    # performance options
    threads: Annotated[
        int, typer.Option("-t", "--threads", help="Number of threads to use", rich_help_panel="Performance")
    ] = defaults.threads,
    delay: Annotated[
        float,
        typer.Option(
            "--delay",
            help=f"Delay before capturing (default: {defaults.delay:.1f} seconds)",
            metavar="SECONDS",
            rich_help_panel="Performance",
        ),
    ] = defaults.delay,
    # http options
    user_agent: Annotated[
        str, typer.Option("-U", "--user-agent", help="User agent to use", rich_help_panel="HTTP")
    ] = defaults.user_agent,
    headers: Annotated[
        list[str],
        typer.Option(
            "-H",
            "--headers",
            help="Additional headers to send in format: 'Header-Name: Header-Value' (multiple supported)",
            rich_help_panel="HTTP",
        ),
    ] = [],
    proxy: Annotated[str, typer.Option("-p", "--proxy", help="HTTP proxy to use", rich_help_panel="HTTP")] = None,
    # json options
    base64: Annotated[
        bool,
        typer.Option(
            "-b",
            "--base64",
            help="Output each screenshot as base64",
            rich_help_panel="JSON (Only apply when -j/--json is used)",
        ),
    ] = False,
    dom: Annotated[
        bool,
        typer.Option(
            "-d",
            "--dom",
            help="Capture the fully-rendered DOM",
            rich_help_panel="JSON (Only apply when -j/--json is used)",
        ),
    ] = False,
    responses: Annotated[
        bool,
        typer.Option(
            "-rs",
            "--responses",
            help="Capture the full body of each HTTP response (including API calls etc.)",
            rich_help_panel="JSON (Only apply when -j/--json is used)",
        ),
    ] = False,
    requests: Annotated[
        bool,
        typer.Option(
            "-rq",
            "--requests",
            help="Capture the full body of each HTTP request (including API calls etc.)",
            rich_help_panel="JSON (Only apply when -j/--json is used)",
        ),
    ] = False,
    javascript: Annotated[
        bool,
        typer.Option(
            "-J",
            "--javascript",
            help="Capture every snippet of Javascript (inline + external)",
            rich_help_panel="JSON (Only apply when -j/--json is used)",
        ),
    ] = False,
    ignore_types: Annotated[
        list[str],
        typer.Option(
            help="Capture the full body of each HTTP response (including API calls etc.)",
            rich_help_panel="JSON (Only apply when -j/--json is used)",
        ),
    ] = defaults.ignored_types,
    ocr: Annotated[
        bool,
        typer.Option(help="Extract text from screenshots", rich_help_panel="JSON (Only apply when -j/--json is used)"),
    ] = False,
):
    # read urls from file if provided
    urls = str_or_file_list(urls)
    # validate urls
    urls = list(validate_urls(urls))
    # if ocr is enabled, make sure we have tesseract
    if ocr:
        import shutil

        if not shutil.which("tesseract"):
            raise argparse.ArgumentTypeError("Please install tesseract to use OCR:\n   - apt install tesseract-ocr")

    # print the pretty mushroom
    if not global_options["silent"]:
        sys.stderr.write(ascii_art)

    try:
        # make sure output directory exists
        if not no_screenshots:
            output_dir.mkdir(parents=True, exist_ok=True)
            if not output_dir.is_dir():
                raise argparse.ArgumentTypeError(f"Output path is not a directory: {output_dir}")
    except Exception as e:
        raise argparse.ArgumentTypeError(f"Problem with output directory: {e}")

    # enable debugging if requested
    if global_options["debug"]:
        import logging

        root_logger = logging.getLogger("webcap")
        root_logger.setLevel(logging.DEBUG)

    browser = Browser(
        threads=threads,
        chrome_path=chrome_path,
        resolution=resolution,
        user_agent=user_agent,
        proxy=proxy,
        delay=delay,
        full_page=full_page,
        dom=dom,
        javascript=javascript,
        requests=requests,
        responses=responses,
        base64=base64,
        ocr=ocr,
        ignore_types=ignore_types,
    )

    async def _scan(browser):
        # start the browser
        try:
            await browser.start()
            async for url, webscreenshot in browser.screenshot_urls(urls):
                if webscreenshot is None or not webscreenshot.status_code:
                    log.info(f"No screenshot returned for {url} -> {webscreenshot}")
                    continue
                # write screenshot to file
                if not no_screenshots:
                    output_path = output_dir / webscreenshot.filename
                    with open(output_path, "wb") as f:
                        f.write(webscreenshot.blob)
                # write json to stdout
                if json:
                    webscreenshot_json = await webscreenshot.json()
                    outline = orjson.dumps(webscreenshot_json).decode()
                else:
                    # print the status code, title, and final url
                    if global_options["no_color"]:
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
            # stop the browser
            with suppress(Exception):
                await browser.stop()

    uvloop.run(_scan(browser))


def main():
    app()


if __name__ == "__main__":
    main()
