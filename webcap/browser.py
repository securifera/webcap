import os
import re
import httpx
import atexit
import orjson
import shutil
import asyncio
import tempfile
import websockets
from pathlib import Path
from contextlib import suppress
from subprocess import Popen, PIPE
from concurrent.futures import ProcessPoolExecutor
from webcap.tab import Tab
from webcap.helpers import task_pool
from webcap.base import WebCapBase
from webcap.errors import DevToolsProtocolError, WebCapError


class Browser(WebCapBase):
    chrome_paths = ["chromium", "chromium-browser", "chrome", "chrome-browser", "google-chrome", "brave-browser"]

    base_chrome_flags = [
        "--disable-features=MediaRouter",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--hide-scrollbars",
        "--mute-audio",
        "--no-default-browser-check",
        "--no-first-run",
        "--deny-permission-prompts",
        "--remote-debugging-port=9222",
        "--headless=new",
        # web proxy
        # "--proxy-server=http://127.0.0.1:8081",
    ]

    def __init__(self, options=None):
        super().__init__()
        atexit.register(self.cleanup)
        self.chrome_path = getattr(options, "chrome", None)
        self.chrome_process = None
        self.chrome_version_regex = re.compile(r"[A-za-z][A-Za-z ]+([\d\.]+)")
        self.temp_dir = Path(tempfile.gettempdir()) / ".webcap"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = getattr(
            options,
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        self.proxy = getattr(options, "proxy", None)
        self.delay = getattr(options, "delay", 3.0)
        self.full_page_capture = getattr(options, "full_page", False)
        self.resolution = getattr(options, "resolution", "800x600")
        self.resolution = [int(x) for x in self.resolution.split("x")]
        x, y = self.resolution

        self.chrome_flags = self.base_chrome_flags + [
            f"--user-data-dir={self.temp_dir}",
            f"--window-size={x},{y}",
            f"--user-agent={self.user_agent}",
        ]
        if self.proxy:
            self.chrome_flags += [f"--proxy-server={self.proxy}"]
        if os.geteuid() == 0:
            self.log.info("Running as root, adding --no-sandbox")
            self.chrome_flags += ["--no-sandbox"]

        self.uri = None
        self.websocket = None
        self.pending_requests = {}
        self.tabs = {}
        self.sessions = {}

        self._closed = False
        self._current_message_id = 0
        self._message_id_lock = asyncio.Lock()
        self._message_handler_task = None

        self._process_pool = ProcessPoolExecutor()

    async def screenshot_urls(self, urls):
        async for url, webscreenshot in task_pool(self.screenshot, urls):
            yield url, webscreenshot

    async def new_tab(self):
        tab = Tab(self)
        await tab.create()
        return tab

    async def screenshot(self, url):
        try:
            tab = await self.new_tab()
            await tab.navigate(url)
            # await asyncio.sleep(5.0)
            return await tab.screenshot()
        finally:
            await tab.close()

    async def _next_message_id(self):
        async with self._message_id_lock:
            message_id = int(self._current_message_id)
            self._current_message_id += 1
        return message_id

    async def handle_event(self, event):
        # Handle response to a specific request
        if "id" in event:
            message_id = event["id"]
            if message_id in self.pending_requests:
                future = self.pending_requests[message_id]
                if "error" in event:
                    error = event["error"]
                    msg = f"{error}"
                    future.set_exception(DevToolsProtocolError(msg))
                else:
                    future.set_result(event.get("result", {}))
                del self.pending_requests[message_id]

        # Handle browser events
        elif "method" in event:
            method = event["method"]

            # TODO: intercept requests (for headers etc.)
            # if command == "Network.setRequestInterception"

            # distribute to session
            session_id = event.get("sessionId", None)
            if session_id:
                self.log.info(f"DOING EVENT: {method}")
                try:
                    handler = self.sessions[session_id].handle_event
                    await handler(event)
                except KeyError:
                    self.log.error(f"No handler for event {method} in session {session_id}")
        else:
            self.log.error(f"Unknown message: {event}")

    async def _message_handler(self):
        """Background task to handle incoming messages"""
        try:
            while self.websocket and not self._closed:
                message = await self.websocket.recv()
                response = orjson.loads(message)
                self.log.info(f"GOT MESSAGE: {response}")
                await self.handle_event(response)

        except websockets.ConnectionClosed as e:
            self.log.info(f"WebSocket connection closed: {e}")
        except Exception as e:
            self.log.error(f"Error in message handler: {e}")
            import traceback

            traceback.print_exc()
        finally:
            self._closed = True

    async def request(self, command, **params):
        request, future = await self._build_request(command, **params)
        await self._send_request(request)
        return await future

    async def _build_request(self, command, **params):
        # make sure command is supported
        domain, subcommand = command.split(".")
        if domain not in self._commands:
            raise DevToolsProtocolError(
                f"domain {domain} not supported (supported domains: {','.join(self._commands.keys())})"
            )
        supported_commands = self._commands[domain]
        if subcommand not in supported_commands:
            raise DevToolsProtocolError(
                f"command {subcommand} not supported for domain {domain} (supported commands: {','.join(supported_commands)})"
            )

        future = asyncio.Future()
        message_id = await self._next_message_id()
        self.pending_requests[message_id] = future
        request = {"id": message_id, "method": command, "params": params}
        return request, future

    async def _send_request(self, request):
        if self.websocket is None:
            raise WebCapError("You must call start() on the browser before making a request")
        self.log.info(f"SENDING REQUEST: {request}")
        await self.websocket.send(orjson.dumps(request).decode("utf-8"))

    async def start(self):
        # enumerate chrome path
        if self.chrome_path is None:
            for i in self.chrome_paths:
                chrome_path = shutil.which(i)
                if chrome_path:
                    # run chrome_path --version
                    process = await asyncio.create_subprocess_exec(chrome_path, "--version", stdout=PIPE, stderr=PIPE)
                    stdout, stderr = await process.communicate()

                    if process.returncode != 0:
                        self.log.error(f"Failed to get version for {chrome_path}: {stderr.decode().strip()}")
                        continue

                    version_output = stdout.decode().strip()
                    match = self.chrome_version_regex.search(version_output)
                    if match:
                        self.log.info(f"Found Chrome version {match.group(1)}")
                        self.version = match.group(1)
                        self.chrome_path = chrome_path
                        break
                    else:
                        self.log.error(f"Version output did not match expected format: {version_output}")

        if not self.chrome_path:
            raise Exception("Chrome executable not found")

        # start chrome process
        if self.chrome_process is None:
            chrome_command = [
                self.chrome_path,
            ] + self.chrome_flags
            self.log.info(" ".join(chrome_command))
            self.chrome_process = Popen(chrome_command, stdout=PIPE, stderr=PIPE)

        # loop until we get the chrome uri
        while self.uri is None:
            # if chrome process has exited, raise an exception
            return_code = self.chrome_process.poll()
            if return_code is not None and return_code != 0:
                raise Exception(
                    f"Chrome process exited with code {return_code}\n{self.chrome_process.stderr.read().decode()}"
                )
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get("http://127.0.0.1:9222/json/version")
                    self.uri = response.json()["webSocketDebuggerUrl"]
            except Exception as e:
                self.log.info(f"Error getting Chrome URI: {e}, retrying...")
                await asyncio.sleep(0.1)

        # connect to chrome
        self.websocket = await websockets.connect(self.uri, max_size=50_000_000)

        # start message handler
        self._message_handler_task = asyncio.create_task(self._message_handler())

        # get supported commands
        async with httpx.AsyncClient() as client:
            self._protocol = (await client.get("http://127.0.0.1:9222/json/protocol")).json()
            self._commands = {}
            for domain in self._protocol["domains"]:
                domain_name = domain["domain"]
                commands = set(command["name"] for command in domain["commands"])
                self._commands[domain_name] = commands

        # intercept network requests
        # await self.request("Network.setRequestInterception", patterns=[{"urlPattern": "*"}])

    async def stop(self):
        self.log.info("STOPPING BROWSER")
        if self.websocket:
            await self.websocket.close()
        if self.chrome_process:
            self.chrome_process.terminate()
        self._closed = True

    def cleanup(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        with suppress(Exception):
            self.chrome_process.terminate()

    def __del__(self):
        self.cleanup()
