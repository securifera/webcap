#!/usr/bin/env python3

import os
import sys
import time
import typer
import orjson
import uvloop
import logging
import argparse
from pathlib import Path
from typing import Annotated
from contextlib import suppress
from rich.console import Console

from webcap import defaults
from webcap.browser import Browser
from webcap.errors import ScreenshotDirError
from webcap.helpers import str_or_file_list, validate_urls, is_cancellation, color_status_code


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


stdout = Console(file=sys.stdout)
stderr = Console(file=sys.stderr)
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
    "color": False,
}


@app.callback()
def _global_options(
    silent: bool = False,
    debug: bool = False,
    color: bool = True,
):
    global_options["silent"] = silent
    global_options["debug"] = debug
    global_options["color"] = color


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
    ] = False,
    directory: Annotated[
        Path, typer.Option("-d", "--directory", help="Directory to serve screenshots from", metavar="OUTPUT_DIR")
    ] = default_output_dir,
):
    import uvicorn

    os.environ["OUTPUT_DIR"] = str(directory)
    try:
        uvicorn.run("webcap.server:app", host=listen_address, port=listen_port, reload=auto_reload)
    except ScreenshotDirError as e:
        stderr.print(f"{e}")


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

    # print the mushroom
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

    async def _scan():

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

        index = {}
        last_index_sync = time.time()
        index_path = output_dir / "index.json"
        json_dir = output_dir / "json"
        json_dir.mkdir(parents=True, exist_ok=True)

        # sync JSON index every 10 seconds
        def sync_index(force=False):
            nonlocal index
            nonlocal last_index_sync
            if force or time.time() - last_index_sync > 10:
                with open(index_path, "wb") as f:
                    f.write(orjson.dumps(index))
                last_index_sync = time.time()

        try:
            # start the browser
            await browser.start()

            # iterate through screenshots as they're taken
            async for url, webscreenshot in browser.screenshot_urls(urls):
                # skip failed requests
                if webscreenshot is None or not webscreenshot.status_code:
                    log.info(f"No screenshot returned for {url} -> {webscreenshot}")
                    continue

                # format the final url
                nav_steps = len(webscreenshot.navigation_history)
                if nav_steps == 1:
                    final_url = webscreenshot.final_url
                else:
                    final_url = []
                    for i, entry in enumerate(webscreenshot.navigation_history):
                        final_url.append(entry["url"])
                        if i < nav_steps - 1:
                            status_code = color_status_code(entry["status"])
                            final_url.append(f"-[{status_code}]->")

                    final_url = " ".join(final_url)

                # write screenshot to index
                index[webscreenshot.id] = {
                    "url": webscreenshot.url,
                    "status_code": webscreenshot.status_code,
                    "title": webscreenshot.title,
                }
                sync_index()

                webscreenshot_json = await webscreenshot.json()

                # write details
                with open(json_dir / f"{webscreenshot.id}.json", "wb") as f:
                    f.write(orjson.dumps(webscreenshot_json))

                # write screenshot to file
                if not no_screenshots:
                    output_path = output_dir / webscreenshot.filename
                    with open(output_path, "wb") as f:
                        f.write(webscreenshot.blob)
                # write json to stdout
                if json:
                    output = orjson.dumps(webscreenshot_json).decode()
                else:
                    # print the status code, title, and final url
                    if global_options["color"]:
                        output = f"[{color_status_code(webscreenshot.status_code)}]\t{webscreenshot.title[:30]:<30}\t{final_url}"
                    else:
                        output = (
                            f"[{webscreenshot.status_code}]\t{webscreenshot.title[:30]:<30}\t{webscreenshot.final_url}"
                        )
                stdout.print(output, highlight=False, soft_wrap=True)
        finally:
            # write the index
            sync_index(force=True)
            # stop the browser
            with suppress(Exception):
                await browser.stop()

    uvloop.run(_scan())


def main():
    try:
        app()
    except BaseException as e:
        if is_cancellation(e):
            sys.exit(1)
        elif isinstance(e, (argparse.ArgumentError, argparse.ArgumentTypeError)):
            stderr.print(f"{e}\n")
        elif not isinstance(e, SystemExit):
            stderr.print_exception(show_locals=True)
            sys.exit(1)


if __name__ == "__main__":
    main()
