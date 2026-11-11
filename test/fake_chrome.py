"""
A fake Chrome used by test_reliability.py.

It speaks just enough of the DevTools protocol for webcap to drive it, and
misbehaves on demand so the failure paths (hung navigations, late replies,
crashes, blocked dialogs, a full stderr pipe) can be tested without a real
browser.

Process-level behaviour is selected with the FAKE_CHROME_MODE environment
variable (comma-separated):

    stderr_flood       write ~1MB to stderr before serving
    no_port            never open the DevTools port
    exit0              exit immediately with code 0
    ignore_sigterm     ignore SIGTERM
    exit_on_last_page  exit when the last page target is closed

Per-page behaviour is selected by a marker in the URL being navigated to:

    navhang      never answer Page.navigate
    capturehang  never answer Page.captureScreenshot; answer it with an error
                 once the target is closed (a "late" error reply)
    caperror     answer Page.captureScreenshot with an error
    dialog       open a JS dialog; captures block until it is handled
    crash        exit the whole process
"""

import os
import sys
import json
import signal
import asyncio
import http
from pathlib import Path

from websockets.asyncio.server import serve

MODES = set(filter(None, os.environ.get("FAKE_CHROME_MODE", "").split(",")))

PROTOCOL = {
    "domains": [
        {
            "domain": domain,
            "commands": [{"name": name} for name in commands],
        }
        for domain, commands in {
            "Target": [
                "createTarget",
                "attachToTarget",
                "detachFromTarget",
                "closeTarget",
                "getTargets",
                "activateTarget",
            ],
            "Page": ["enable", "navigate", "captureScreenshot", "getNavigationHistory", "handleJavaScriptDialog"],
            "Network": ["enable", "getResponseBody"],
            "Browser": ["setDownloadBehavior", "getVersion"],
            "DOM": ["getDocument", "getOuterHTML"],
            "Debugger": ["enable", "getScriptSource"],
            # test-only introspection
            "Fake": ["getLog"],
        }.items()
    ]
}


class FakeChrome:
    def __init__(self):
        self.targets = {"initial": {"targetId": "initial", "type": "page", "url": "about:blank"}}
        self.sessions = {}  # session id -> target id
        self.pending_captures = {}  # target id -> (message id, session id)
        self.open_dialogs = set()  # target ids with an unhandled dialog
        self.log = []  # every method received, in order
        self.counter = 0

    def next_id(self, prefix):
        self.counter += 1
        return f"{prefix}{self.counter}"

    async def handle(self, websocket):
        async for raw in websocket:
            message = json.loads(raw)
            try:
                await self.dispatch(websocket, message)
            except Exception as e:  # pragma: no cover - debugging aid
                sys.stderr.write(f"fake chrome error: {e!r}\n")

    async def reply(self, websocket, message, result=None, error=None):
        response = {"id": message["id"]}
        if error is not None:
            response["error"] = {"code": -32000, "message": error}
        else:
            response["result"] = result or {}
        if "sessionId" in message:
            response["sessionId"] = message["sessionId"]
        await websocket.send(json.dumps(response))

    async def event(self, websocket, session_id, method, params=None):
        await websocket.send(json.dumps({"method": method, "params": params or {}, "sessionId": session_id}))

    async def dispatch(self, websocket, message):
        method = message["method"]
        params = message.get("params", {})
        session_id = message.get("sessionId")
        target_id = self.sessions.get(session_id)
        self.log.append(method)

        if method == "Fake.getLog":
            await self.reply(websocket, message, {"log": self.log})

        elif method == "Target.createTarget":
            target_id = self.next_id("target")
            self.targets[target_id] = {"targetId": target_id, "type": "page", "url": params.get("url", "")}
            await self.reply(websocket, message, {"targetId": target_id})

        elif method == "Target.attachToTarget":
            new_session = self.next_id("session")
            self.sessions[new_session] = params["targetId"]
            await self.reply(websocket, message, {"sessionId": new_session})

        elif method == "Target.getTargets":
            await self.reply(websocket, message, {"targetInfos": list(self.targets.values())})

        elif method == "Target.closeTarget":
            closed = params["targetId"]
            if closed not in self.targets:
                await self.reply(websocket, message, error="No target with given id found")
                return
            del self.targets[closed]
            self.open_dialogs.discard(closed)
            await self.reply(websocket, message, {"success": True})
            # a command that was still pending on the closed target fails late
            pending = self.pending_captures.pop(closed, None)
            if pending is not None:
                message_id, pending_session = pending
                await websocket.send(
                    json.dumps(
                        {
                            "id": message_id,
                            "sessionId": pending_session,
                            "error": {"code": -32000, "message": "Target closed"},
                        }
                    )
                )
            if "exit_on_last_page" in MODES and not self.targets:
                os._exit(0)

        elif method == "Page.navigate":
            url = params.get("url", "")
            if "crash" in url:
                os._exit(1)
            self.targets[target_id]["url"] = url
            if "navhang" in url:
                return
            await self.reply(websocket, message, {"frameId": "frame"})
            await self.event(
                websocket,
                session_id,
                "Network.responseReceived",
                {
                    "requestId": self.next_id("request"),
                    "type": "Document",
                    "response": {"url": url, "status": 200, "mimeType": "text/html", "headers": {}},
                },
            )
            if "dialog" in url:
                self.open_dialogs.add(target_id)
                await self.event(websocket, session_id, "Page.javascriptDialogOpening", {"type": "alert"})
            else:
                await self.event(websocket, session_id, "Page.loadEventFired")

        elif method == "Page.handleJavaScriptDialog":
            self.open_dialogs.discard(target_id)
            await self.reply(websocket, message)
            pending = self.pending_captures.pop(target_id, None)
            if pending is not None:
                await websocket.send(
                    json.dumps({"id": pending[0], "sessionId": pending[1], "result": {"data": "ZmFrZQ=="}})
                )

        elif method == "Page.captureScreenshot":
            url = self.targets[target_id]["url"]
            if "caperror" in url:
                await self.reply(websocket, message, error="Unable to capture screenshot")
            elif "capturehang" in url or target_id in self.open_dialogs:
                self.pending_captures[target_id] = (message["id"], session_id)
            else:
                await self.reply(websocket, message, {"data": "ZmFrZQ=="})

        elif method == "Page.getNavigationHistory":
            await self.reply(websocket, message, {"entries": [{"title": "fake title"}]})

        else:
            await self.reply(websocket, message)


async def main():
    if "exit0" in MODES:
        sys.exit(0)
    if "ignore_sigterm" in MODES:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if "stderr_flood" in MODES:
        # far more than a pipe buffer holds; blocks forever if nobody reads it
        for _ in range(1024):
            sys.stderr.write("x" * 1023 + "\n")
        sys.stderr.flush()
    if "no_port" in MODES:
        await asyncio.sleep(3600)

    user_data_dir = None
    for arg in sys.argv[1:]:
        if arg.startswith("--user-data-dir="):
            user_data_dir = Path(arg.split("=", 1)[1])
    if user_data_dir is None:
        sys.exit("fake chrome needs --user-data-dir")

    chrome = FakeChrome()

    def process_request(connection, request):
        # plain HTTP endpoints that live on the DevTools port
        if request.path == "/json/protocol":
            return connection.respond(http.HTTPStatus.OK, json.dumps(PROTOCOL))
        if request.path == "/json/version":
            port = connection.local_address[1]
            return connection.respond(
                http.HTTPStatus.OK,
                json.dumps({"webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/fake"}),
            )
        return None

    async with serve(chrome.handle, "127.0.0.1", 0, process_request=process_request) as server:
        port = server.sockets[0].getsockname()[1]
        # same file real Chrome writes when started with --remote-debugging-port=0
        (user_data_dir / "DevToolsActivePort").write_text(f"{port}\n/devtools/browser/fake\n")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
