import os
import re
import httpx
import orjson
import shutil
import asyncio
import tempfile
import websockets
from pathlib import Path
from contextlib import suppress
from subprocess import Popen, PIPE

from pywitness.tab import Tab
from pywitness.base import PywitnessBase
from pywitness.errors import DevToolsProtocolError, PywitnessError


class Browser(PywitnessBase):
    chrome_paths = ["chromium", "chromium-browser", "chrome", "chrome-browser", "google-chrome", "brave-browser"]

    def __init__(self):
        super().__init__()
        self.chrome_path = None
        self.chrome_process = None
        self.chrome_version_regex = re.compile(r"[A-za-z][A-Za-z ]+([\d\.]+)")
        self.temp_dir = Path(tempfile.gettempdir()) / ".pywitness"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.uri = None
        self.websocket = None
        self.pending_requests = {}
        self.tabs = {}
        self.sessions = {}

        self._closed = False
        self._current_message_id = 0
        self._message_handler_task = None

    async def new_tab(self):
        tab = Tab(self)
        await tab.create()
        return tab

    async def screenshot(self, url, x=800, y=600):
        try:
            tab = await self.new_tab()
            await tab.navigate(url)
            return await tab.screenshot(x=x, y=y)
        finally:
            with suppress(Exception):
                await tab.close()

    def _next_message_id(self):
        message_id = int(self._current_message_id)
        self._current_message_id += 1
        return message_id

    async def _message_handler(self):
        """Background task to handle incoming messages"""
        try:
            while self.websocket and not self._closed:
                message = await self.websocket.recv()
                response = orjson.loads(message)
                self.log.info(f"GOT MESSAGE: {response}")

                # Handle response to a specific request
                if "id" in response:
                    message_id = response["id"]
                    if message_id in self.pending_requests:
                        future = self.pending_requests[message_id]
                        if "error" in response:
                            future.set_exception(DevToolsProtocolError(response["error"]))
                        else:
                            future.set_result(response.get("result", {}))
                        del self.pending_requests[message_id]

                # Handle events (messages without id)
                elif "method" in response:
                    method = response["method"]
                    session_id = response.get("sessionId", None)
                    if session_id:
                        self.log.info(f"DOING EVENT: {method}")
                        try:
                            handler = self.sessions[session_id].handle_event
                            await handler(response)
                        except KeyError:
                            self.log.error(f"No handler for event {method} in session {session_id}")

                else:
                    self.log.error(f"Unknown message: {response}")

        except websockets.ConnectionClosed:
            self.log.info("WebSocket connection closed")
        except Exception as e:
            self.log.error(f"Error in message handler: {e}")
        finally:
            self._closed = True

    async def request(self, method, **params):
        request, future = self._build_request(method, **params)
        await self._send_request(request)
        return await future

    def _build_request(self, method, **params):
        future = asyncio.Future()
        message_id = self._next_message_id()
        self.pending_requests[message_id] = future
        request = {"id": message_id, "method": method, "params": params}
        return request, future

    async def _send_request(self, request):
        if self.websocket is None:
            raise PywitnessError("You must call start() on the browser before making a request")
        self.log.info(f"SENDING REQUEST: {request}")
        await self.websocket.send(orjson.dumps(request).decode("utf-8"))

    async def start(self):
        # enumerate chrome path
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
                "--remote-debugging-port=9222",
                "--headless",
                f"--user-data-dir={self.temp_dir}",
            ]
            if os.geteuid() == 0:
                self.log.info("Running as root, adding --no-sandbox")
                chrome_command += ["--no-sandbox"]
            self.log.info(f"Running Chrome with command: {' '.join(chrome_command)}")
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
                response = httpx.get("http://127.0.0.1:9222/json/version")
                self.uri = response.json()["webSocketDebuggerUrl"]
            except Exception as e:
                self.log.info(f"Error getting Chrome URI: {e}, retrying...")
                await asyncio.sleep(0.1)

        # connect to chrome
        self.websocket = await websockets.connect(self.uri)

        # start message handler
        self._message_handler_task = asyncio.create_task(self._message_handler())

    async def receive_response(self):
        return await self.websocket.recv()

    async def stop(self):
        if self.websocket:
            await self.websocket.close()
        if self.chrome_process:
            self.chrome_process.terminate()
        self._closed = True
