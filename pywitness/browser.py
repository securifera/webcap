import httpx
import orjson
import shutil
import asyncio
import websockets
from contextlib import suppress
from subprocess import Popen, PIPE

from pywitness.tab import Tab
from pywitness.base import PywitnessBase
from pywitness.errors import DevToolsProtocolError


class Browser(PywitnessBase):
    chrome_paths = ["chromium", "chrome", "chrome-browser", "google-chrome", "brave-browser"]

    def __init__(self):
        super().__init__()
        self.chrome_path = None
        self.chrome_process = None
        for i in self.chrome_paths:
            chrome_path = shutil.which(i)
            if chrome_path:
                self.chrome_path = chrome_path
                break
        if not self.chrome_path:
            raise Exception("Chrome executable not found")

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
            if self.websocket:
                await self.websocket.close()

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
        self.log.info(f"SENDING REQUEST: {request}")
        await self.websocket.send(orjson.dumps(request).decode("utf-8"))

    async def start(self):
        # start chrome process
        if self.chrome_process is None:
            self.chrome_process = Popen(
                [self.chrome_path, "--remote-debugging-port=9222", "--headless"], stdout=PIPE, stderr=PIPE
            )

        # loop until we get the chrome uri
        while self.uri is None:
            # if chrome process has exited, raise an exception
            return_code = self.chrome_process.poll()
            if return_code is not None and return_code != 0:
                raise Exception(f"Chrome process exited with code {return_code}")
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
