import os
import re
import httpx
import atexit
import orjson
import shutil
import asyncio
import tempfile
import subprocess
import signal
import uuid
import time
import websockets
from pathlib import Path
from contextlib import suppress
from subprocess import Popen, PIPE
from concurrent.futures import ProcessPoolExecutor

from webcap.tab import Tab
from webcap import defaults
from webcap.base import WebCapBase
from webcap.errors import DevToolsProtocolError, WebCapError
from webcap.helpers import task_pool, repr_params  # , download_wap


class Browser(WebCapBase):
    possible_chrome_binaries = [
        "chromium", "chromium-browser", "chrome", "chrome-browser", "google-chrome"]

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
        "--enable-automation",
        "--ignore-certificate-errors",
        "--disable-session-crashed-bubble",  # Don't show crash recovery
        "--disable-infobars",                # No info bars
        "--disable-restore-session-state",   # Don't restore previous session
        "--disable-background-timer-throttling",  # Better for automation
        # "--site-per-process",
    ]

    def __init__(
        self,
        threads=defaults.threads,
        chrome_path=None,
        resolution=defaults.resolution,
        user_agent=defaults.user_agent,
        proxy=None,
        timeout=defaults.timeout,
        delay=defaults.delay,
        quality=defaults.quality,
        image_format=defaults.image_format,
        full_page=False,
        dom=False,
        javascript=False,
        requests=False,
        responses=False,
        base64=False,
        ocr=False,
        ignore_types=defaults.ignored_types,
    ):
        super().__init__()
        atexit.register(self.cleanup)
        self.chrome_process = None
        self.chrome_path = chrome_path
        self.chrome_version_regex = re.compile(r"[A-za-z][A-Za-z ]+([\d\.]+)")
        self.threads = threads
        # Create unique temp directory for each browser instance
        unique_id = str(uuid.uuid4())[:8]
        self.temp_dir = Path(tempfile.gettempdir()) / f".webcap_{unique_id}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path.home() / ".webcap"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.proxy = proxy
        self.timeout = timeout
        self.quality = quality
        self.image_format = image_format
        self.delay = delay
        self.user_agent = user_agent
        self.full_page_capture = full_page
        self.capture_javascript = javascript
        self.capture_requests = requests
        self.capture_responses = responses
        self.capture_base64 = base64
        self.capture_ocr = ocr
        self.capture_dom = dom
        if isinstance(ignore_types, str):
            ignore_types = [ignore_types]
        ignore_types = [t.lower() for t in ignore_types]
        self.ignore_types = ignore_types
        self.resolution = str(resolution)
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

        self.wap_session_id = None

        self.websocket_uri = None
        self.websocket = None
        self.pending_requests = {}
        self.tabs = {}
        self.event_queues = {}

        self._closed = False
        self._current_message_id = 0
        self._message_id_lock = asyncio.Lock()
        self._tab_lock = asyncio.Lock()
        self._message_handler_task = None

        self._extractous = None

        self._process_pool = ProcessPoolExecutor()
        self.orphaned_session = False

    async def screenshot_urls(self, urls):
        async for url, webscreenshot in task_pool(self.screenshot, urls, threads=self.threads):
            yield url, webscreenshot

    async def screenshot(self, url):
        tab = None
        try:
            tab = await self.new_tab(url)
            await tab.screenshot(self.image_format, self.quality)
            return tab.webscreenshot
        except asyncio.TimeoutError:
            self.log.info(
                f"URL {url} load timed out after {self.timeout} seconds")
        finally:
            if tab:
                with suppress(Exception):
                    await tab.close()

    async def new_tab(self, url):
        tab = Tab(self)
        await tab.create()
        await asyncio.wait_for(tab.navigate(url), timeout=self.timeout)
        return tab

    async def start(self):
        await self.detect_chrome_path()
        await self._start_chrome()
        await self._start_message_handler()

        # wap_session_id = await self.get_wap_session()

        # intercept network requests
        # await self.request("Network.setRequestInterception", patterns=[{"urlPattern": "*"}])

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
                    with suppress(Exception):
                        future.set_result(event.get("result", {}))
                del self.pending_requests[message_id]

        # Handle browser events
        elif "method" in event:
            method = event["method"]

            # TODO: intercept requests (for headers etc.)
            # if method == "Network.setRequestInterception"

            # distribute to session
            session_id = event.get("sessionId", None)
            if session_id:
                try:
                    event_queue = self.event_queues[session_id]
                    await event_queue.put(event)
                except KeyError:
                    if method not in ["Inspector.detached", "Page.frameDetached"]:
                        self.log.debug(
                            f"No handler for event {method} in session {session_id}")
                        self.orphaned_session = True
                        # Detach from orphaned session to stop receiving events
                        # with suppress(Exception):
                        #     # Use explicit parameter name to avoid conflict with method's sessionId parameter
                        #     self.log.debug(
                        #         f"Detaching from orphaned session {session_id}")
                        #     await self.request("Target.detachFromTarget", sessionId=None, **{"sessionId": session_id})

                        # # Calling force cleanup to ensure no stale sessions remain
                        # await self.force_cleanup()

        else:
            self.log.error(f"Unknown message: {event}")

    async def request(self, command, sessionId=None, retry=False, **params):
        retries = 1
        retry_delay = 0.1
        # 7 iterations w/ exponential backoff == max retry delay of 6.4 seconds
        if retry:
            retries = 7
        error = None
        for _ in range(retries):
            message_id = await self._next_message_id()
            try:
                future = asyncio.Future()
                self.pending_requests[message_id] = future
                request = await self._build_request(command, message_id, **params)
                if sessionId:
                    request["sessionId"] = sessionId
                await self._send_request(request)
                response = await asyncio.wait_for(future, timeout=self.timeout)
                return response
            except DevToolsProtocolError as e:
                self.pending_requests.pop(message_id, None)
                error = DevToolsProtocolError(
                    f"Error sending command: {command}({repr_params(params)}): {e}")
                self.log.info(error)
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
        self.log.debug(
            f"Error sending command: {command}({repr_params(params)}): {error}")
        return {"success": False, "error": str(error)}

    async def _build_request(self, command, message_id, **params):
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

        request = {"id": message_id, "method": command, "params": params}
        return request

    async def _send_request(self, request):
        if self.websocket is None:
            raise WebCapError(
                "You must call start() on the browser before making a request")
        await self.websocket.send(orjson.dumps(request).decode("utf-8"))

    async def detect_chrome_path(self):
        # enumerate chrome path
        if self.chrome_path is None:
            for i in self.possible_chrome_binaries:
                chrome_path = shutil.which(i)
                if chrome_path:
                    # run chrome_path --version
                    process = await asyncio.create_subprocess_exec(chrome_path, "--version", stdout=PIPE, stderr=PIPE)
                    stdout, stderr = await process.communicate()

                    if process.returncode != 0:
                        self.log.error(
                            f"Failed to get version for {chrome_path}: {stderr.decode().strip()}")
                        continue

                    version_output = stdout.decode().strip()
                    match = self.chrome_version_regex.search(version_output)
                    if match:
                        self.log.info(
                            f"Found Chrome version {match.group(1)} at {chrome_path}")
                        self.version = match.group(1)
                        self.chrome_path = chrome_path
                        break
                    else:
                        self.log.error(
                            f"Version output did not match expected format: {version_output}")

        if not self.chrome_path:
            raise Exception("Chrome executable not found")

    async def _start_chrome(self):
        # download wap
        # wap_path = await download_wap(self.version, self.cache_dir)

        # start chrome process
        if self.chrome_process is None:
            chrome_command = [
                self.chrome_path,
            ] + self.chrome_flags
            # if wap_path is not None:
            #     chrome_command += [f"--load-extension={wap_path}"]
            self.log.debug("Executing chrome command: " +
                           " ".join(chrome_command))
            # Start in new process group to kill all child processes
            self.chrome_process = Popen(
                chrome_command, stdout=PIPE, stderr=PIPE,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None)

        # loop until we get the chrome uri
        while self.websocket_uri is None:
            # if chrome process has exited, raise an exception
            return_code = self.chrome_process.poll()
            if return_code is not None and return_code != 0:
                raise Exception(
                    f"Chrome process exited with code {return_code}\n{self.chrome_process.stderr.read().decode()}"
                )
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get("http://127.0.0.1:9222/json/version")
                    self.websocket_uri = response.json()[
                        "webSocketDebuggerUrl"]
            except Exception as e:
                self.log.info(f"Error getting Chrome URI: {e}, retrying...")
                await asyncio.sleep(0.1)

        # connect to chrome
        self.websocket = await websockets.connect(self.websocket_uri, max_size=500_000_000)

        # enumerate supported CDP commands
        await self._enum_commands()

    async def _enum_commands(self):
        # get supported CDP commands
        async with httpx.AsyncClient() as client:
            self._protocol = (await client.get("http://127.0.0.1:9222/json/protocol")).json()
            self._commands = {}
            for domain in self._protocol["domains"]:
                domain_name = domain["domain"]
                commands = set(command["name"]
                               for command in domain["commands"])
                self._commands[domain_name] = commands

    async def _start_message_handler(self):
        self._message_handler_task = asyncio.create_task(
            self._message_handler())

    async def _message_handler(self):
        """Background task to handle incoming messages"""
        try:
            while self.websocket and not self._closed:
                message = await self.websocket.recv()
                response = orjson.loads(message)
                # self.log.debug(f"Got message: {response}")
                await self.handle_event(response)

        except websockets.ConnectionClosed as e:
            self.log.debug(f"WebSocket connection closed: {e}")
        # except WebCapError as e:
        #     raise e
        except Exception as e:
            self.log.critical(f"Error in message handler: {e}")
            import traceback

            self.log.critical(traceback.format_exc())
        finally:
            await self.stop()

    async def stop(self):
        if not self._closed:
            self.log.debug("Stopping browser")

            # Close all tabs first
            tab_close_tasks = []
            for tab in list(self.tabs.values()):
                tab_close_tasks.append(asyncio.create_task(tab.close()))

            if tab_close_tasks:
                await asyncio.gather(*tab_close_tasks, return_exceptions=True)

            # Cancel message handler task
            if self._message_handler_task and not self._message_handler_task.done():
                self._message_handler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._message_handler_task

            # Close websocket
            if self.websocket:
                with suppress(Exception):
                    await self.websocket.close()
                self.websocket = None

            # Close chrome process
            if self.chrome_process:
                with suppress(Exception):
                    self.chrome_process.terminate()
                    # Wait for process to actually exit, with timeout
                    try:
                        await asyncio.wait_for(
                            asyncio.create_task(asyncio.to_thread(
                                self.chrome_process.wait)),
                            timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        # Force kill if terminate didn't work
                        self.log.warning(
                            "Chrome process didn't terminate gracefully, force killing")
                        self.chrome_process.kill()
                        await asyncio.wait_for(
                            asyncio.create_task(asyncio.to_thread(
                                self.chrome_process.wait)),
                            timeout=2.0
                        )

            # Close process pool
            if hasattr(self, '_process_pool') and self._process_pool:
                self._process_pool.shutdown(wait=False)
                self._process_pool = None

            # Cancel any pending requests
            for future in self.pending_requests.values():
                if not future.done():
                    future.set_exception(WebCapError(
                        "Browser stopped before request completed"))

            # Clear collections
            self.pending_requests.clear()
            self.tabs.clear()
            self.event_queues.clear()

        self._closed = True

    async def force_target_cleanup(self):
        """Aggressively close ALL page targets (including about:blank)"""
        try:
            # Get all targets using Chrome DevTools Protocol
            response = await self.request("Target.getTargets")
            all_targets = response.get("targetInfos", [])

            targets_to_close = []
            for target in all_targets:
                target_id = target.get("targetId", "")
                target_type = target.get("type", "")

                # Close ALL page targets (including about:blank for maximum cleanup)
                if target_type == "page":
                    targets_to_close.append(target_id)

            # Close all targets
            for target_id in targets_to_close:
                with suppress(Exception):
                    self.log.debug(f"Closing target {target_id}")
                    await self.request("Target.closeTarget", targetId=target_id)

            # Reset flag
            self.orphaned_session = False

        except Exception as e:
            self.log.debug(f"Error during forced cleanup: {e}")

    def cleanup(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

        # Shutdown process pool
        with suppress(Exception):
            if hasattr(self, '_process_pool') and self._process_pool:
                self._process_pool.shutdown(wait=False)
                self._process_pool = None

        with suppress(Exception):
            if self.chrome_process and self.chrome_process.poll() is None:
                # Try to kill the entire process group first
                if hasattr(os, 'killpg'):
                    try:
                        os.killpg(os.getpgid(
                            self.chrome_process.pid), signal.SIGTERM)
                        self.chrome_process.wait(timeout=5)
                    except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
                        # Fallback to killing individual process
                        self.chrome_process.terminate()
                        try:
                            self.chrome_process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            # Force kill if terminate didn't work
                            self.chrome_process.kill()
                            self.chrome_process.wait(timeout=2)
                else:
                    # Windows fallback
                    self.chrome_process.terminate()
                    try:
                        self.chrome_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.chrome_process.kill()
                        self.chrome_process.wait(timeout=2)

    async def _next_message_id(self):
        async with self._message_id_lock:
            message_id = int(self._current_message_id)
            self._current_message_id += 1
        return message_id

    @property
    def extractous(self):
        if self._extractous is None:
            import extractous

            self._extractous = extractous.Extractor()
        return self._extractous

    # async def get_wap_session(self):
    #     # wait for chrome extension to come online (100 iterations == 10 seconds)
    #     wap_target_id = None
    #     async with httpx.AsyncClient() as client:
    #         for i in range(100):
    #             response = await client.get("http://127.0.0.1:9222/json")
    #             targets = response.json()
    #             for target in targets[::-1]:
    #                 target_type = target.get("type", "")
    #                 target_url = target.get("url", "")
    #                 target_id = target.get("id", "")
    #                 if target_type == "service_worker" and target_url.startswith("chrome-extension://") and target_id:
    #                     wap_target_id = target_id
    #                     break
    #             await asyncio.sleep(0.1)
    #     if wap_target_id is None:
    #         raise WebCapError("Failed to find WAP extension target")
    #     # attach to the target
    #     for i in range(100):
    #         try:
    #             wap_response = await self.request("Target.attachToTarget", targetId=wap_target_id, flatten=True)
    #             self.wap_session_id = wap_response.get("sessionId", None)
    #         except DevToolsProtocolError:
    #             await asyncio.sleep(0.1)
    #             continue
    #     if self.wap_session_id is not None:
    #         return self.wap_session_id
    #     raise WebCapError("Timed out waiting for chrome extension to load:")

    def __del__(self):
        self.cleanup()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
