import os
import re
import sys
import httpx
import atexit
import ctypes
import orjson
import shutil
import asyncio
import tempfile
import subprocess
import signal
import uuid
import time
import websockets
import multiprocessing
from pathlib import Path
from contextlib import suppress
from subprocess import Popen, PIPE, DEVNULL
from concurrent.futures import ProcessPoolExecutor

from collections import OrderedDict

from webcap.tab import Tab
from webcap import defaults
from webcap.base import WebCapBase
from webcap.errors import DevToolsProtocolError, WebCapError, BrowserClosedError
from webcap.helpers import task_pool, repr_params  # , download_wap


# Methods Chrome commonly emits for a session *after* we have detached/closed
# the tab. These are benign post-close races, not real orphans — receiving them
# should not flag the browser for restart.
_BENIGN_POST_CLOSE_METHODS = frozenset({
    "Inspector.detached",
    "Page.frameDetached",
    "Page.frameStoppedLoading",
    "Page.lifecycleEvent",
    "Page.loadEventFired",
    "Page.domContentEventFired",
    "Page.frameNavigated",
    "Page.navigatedWithinDocument",
    "Network.dataReceived",
    "Network.loadingFinished",
    "Network.loadingFailed",
    "Network.responseReceived",
    "Network.responseReceivedExtraInfo",
    "Network.requestWillBeSent",
    "Network.requestWillBeSentExtraInfo",
    "Network.requestServedFromCache",
    "Network.resourceChangedPriority",
    "Target.targetDestroyed",
    "Target.targetInfoChanged",
    "Runtime.executionContextCreated",
    "Runtime.executionContextDestroyed",
    "Runtime.executionContextsCleared",
})

# How long to remember recently-closed session IDs. Within this window, events
# arriving for those sessions are silently dropped instead of flagging the
# browser as orphaned.
_RECENTLY_CLOSED_TTL = 10.0
# Hard cap to keep memory bounded in case TTL pruning lags.
_RECENTLY_CLOSED_MAX = 1024


# How long to wait for Chrome to open its DevTools endpoint before giving up.
_STARTUP_TIMEOUT = 30.0
# How long Chrome gets to exit after SIGTERM before its process group is SIGKILLed.
_KILL_GRACE = 5.0

# libc is loaded up front so the post-fork hook below does nothing but one call.
_libc = None
if sys.platform.startswith("linux"):
    with suppress(Exception):
        _libc = ctypes.CDLL("libc.so.6", use_errno=True)
_PR_SET_PDEATHSIG = 1


def _die_with_parent():
    """
    Runs in the Chrome child between fork and exec: ask the kernel to SIGKILL
    Chrome when the thread that launched it goes away.

    Chrome runs in its own session, so without this it survives a crashed or
    SIGKILLed parent and is left running with nothing to stop it.
    """
    _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)


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
        # Port 0 == let the OS pick a free port. Chrome reports the one it got
        # in <user-data-dir>/DevToolsActivePort. A fixed port means a second
        # browser (or one left over from an earlier run) silently shares or
        # steals the endpoint.
        "--remote-debugging-port=0",
        "--headless=new",
        "--enable-automation",
        "--ignore-certificate-errors",
        "--disable-session-crashed-bubble",  # Don't show crash recovery
        "--disable-infobars",                # No info bars
        "--disable-restore-session-state",   # Don't restore previous session
        "--disable-background-timer-throttling",  # Better for automation
        # Avoid the gnome-keyring / libsecret "Unlock login keyring" popup
        # when running headed on Linux. Chrome's default is to try to store
        # credentials in the system keyring; --password-store=basic uses an
        # in-process store and --use-mock-keychain bypasses macOS Keychain.
        "--password-store=basic",
        "--use-mock-keychain",
        # /dev/shm is tiny in containers; renderers crash or hang when it fills
        "--disable-dev-shm-usage",
        # No background work that isn't the page we asked for
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-extensions",
        "--disable-breakpad",
        "--metrics-recording-only",
        # Don't deprioritise tabs that aren't in the foreground
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-hang-monitor",
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

        # created on first use; see the _process_pool property
        self._process_pool_instance = None
        self.startup_timeout = _STARTUP_TIMEOUT
        self.kill_grace = _KILL_GRACE
        self.debug_port = None
        self._chrome_log = None
        self.orphaned_session = False
        # session_id -> timestamp when the tab was closed. Used to silently
        # ignore Chrome's post-close event tail without flagging an orphan.
        self._recently_closed_sessions: "OrderedDict[str, float]" = OrderedDict()
        # cleanup() runs from both atexit and __del__ and may also be reached
        # after an explicit stop(). This flag keeps it idempotent so we don't
        # double-kill Chrome or re-wipe an already-deleted temp dir.
        self._cleaned_up = False

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
        try:
            await tab.create()
            await asyncio.wait_for(tab.navigate(url), timeout=self.timeout)
        except BaseException:
            # The caller never gets a handle to this tab, so nobody else can
            # close it. Leaving it open leaks the page (still loading) in
            # Chrome plus its event queue and handler task here.
            with suppress(Exception):
                await tab.close()
            raise
        return tab

    @property
    def is_alive(self):
        """
        True while the browser can still take requests.

        Goes False as soon as Chrome exits or the DevTools connection drops,
        after which every request raises BrowserClosedError and the only way
        forward is a new Browser.
        """
        if self._closed or self.websocket is None:
            return False
        if self.chrome_process is None or self.chrome_process.poll() is not None:
            return False
        return self._message_handler_task is not None and not self._message_handler_task.done()

    async def start(self):
        try:
            await self.detect_chrome_path()
            await self._start_chrome()
            await self._start_message_handler()
            # Never write downloads to disk; a URL that serves a file would
            # otherwise fill the download directory over a long scan.
            with suppress(Exception):
                await self.request("Browser.setDownloadBehavior", behavior="deny")
        except BaseException:
            # don't leave a half-started Chrome behind
            with suppress(Exception):
                await self.stop()
            raise

        # wap_session_id = await self.get_wap_session()

        # intercept network requests
        # await self.request("Network.setRequestInterception", patterns=[{"urlPattern": "*"}])

    async def handle_event(self, event):
        # Handle response to a specific request
        if "id" in event:
            future = self.pending_requests.pop(event["id"], None)
            # The future is gone or already done when the caller timed out or
            # was cancelled before Chrome answered. Chrome still answers (often
            # with an error, once the tab is closed) and that must be a no-op.
            if future is not None and not future.done():
                if "error" in event:
                    error = event["error"]
                    msg = f"{error}"
                    future.set_exception(DevToolsProtocolError(msg))
                else:
                    future.set_result(event.get("result", {}))

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
                    # Three reasons we may not have a queue for this session:
                    #   1. We just closed the tab and Chrome is flushing its
                    #      buffered events (benign — silently drop).
                    #   2. The event method is one Chrome routinely emits
                    #      around teardown (also benign).
                    #   3. Something is genuinely wrong — flag as orphaned.
                    if self._is_recently_closed(session_id):
                        self.log.debug(
                            f"Ignoring post-close event {method} for session {session_id}")
                    elif method in _BENIGN_POST_CLOSE_METHODS:
                        self.log.debug(
                            f"Ignoring benign event {method} for unknown session {session_id}")
                    else:
                        self.log.debug(
                            f"No handler for event {method} in session {session_id}")
                        self.orphaned_session = True

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
                error = DevToolsProtocolError(
                    f"Error sending command: {command}({repr_params(params)}): {e}")
                self.log.info(error)
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
            finally:
                # also covers timeouts and cancellation
                self.pending_requests.pop(message_id, None)
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
        if self._closed:
            raise BrowserClosedError("The browser has stopped")
        if self.websocket is None:
            raise WebCapError(
                "You must call start() on the browser before making a request")
        try:
            await self.websocket.send(orjson.dumps(request).decode("utf-8"))
        except websockets.ConnectionClosed as e:
            raise BrowserClosedError(f"Lost connection to the browser: {e}") from e

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

        deadline = time.monotonic() + self.startup_timeout

        # start chrome process
        if self.chrome_process is None:
            chrome_command = [
                self.chrome_path,
            ] + self.chrome_flags
            # if wap_path is not None:
            #     chrome_command += [f"--load-extension={wap_path}"]
            self.log.debug("Executing chrome command: " +
                           " ".join(chrome_command))
            # Chrome's output goes to a file, never a pipe: nothing reads a
            # pipe here, so Chrome would block for good once it filled.
            self._chrome_log = open(self.temp_dir / "chrome_stderr.log", "wb")
            self.chrome_process = Popen(
                chrome_command, stdin=DEVNULL, stdout=DEVNULL, stderr=self._chrome_log,
                # own session/process group, so the whole tree can be killed
                start_new_session=True,
                preexec_fn=_die_with_parent if _libc is not None else None)

        # wait for chrome to report the port it is listening on
        port_file = self.temp_dir / "DevToolsActivePort"
        while True:
            return_code = self.chrome_process.poll()
            if return_code is not None:
                raise WebCapError(
                    f"Chrome process exited with code {return_code} before DevTools was ready\n{self._chrome_log_tail()}"
                )
            lines = []
            with suppress(OSError):
                lines = port_file.read_text().split()
            if len(lines) >= 2 and lines[0].isdigit():
                break
            if time.monotonic() > deadline:
                raise WebCapError(
                    f"Chrome did not open its DevTools port within {self.startup_timeout} seconds\n{self._chrome_log_tail()}"
                )
            await asyncio.sleep(0.1)

        self.debug_port = int(lines[0])
        self.websocket_uri = f"ws://127.0.0.1:{self.debug_port}{lines[1]}"

        # connect to chrome
        try:
            self.websocket = await asyncio.wait_for(
                websockets.connect(self.websocket_uri, max_size=500_000_000),
                timeout=max(deadline - time.monotonic(), 1),
            )
        except asyncio.TimeoutError:
            raise WebCapError(f"Timed out connecting to Chrome DevTools at {self.websocket_uri}")

        # enumerate supported CDP commands
        await self._enum_commands()

    def _chrome_log_tail(self, max_bytes=4096):
        """The last few KB of Chrome's stderr, for error messages"""
        with suppress(Exception):
            with open(self.temp_dir / "chrome_stderr.log", "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(f.tell() - max_bytes, 0))
                return f.read().decode(errors="replace")
        return ""

    async def _enum_commands(self):
        # get supported CDP commands
        async with httpx.AsyncClient(timeout=self.startup_timeout) as client:
            self._protocol = (await client.get(f"http://127.0.0.1:{self.debug_port}/json/protocol")).json()
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
                try:
                    response = orjson.loads(message)
                    # self.log.debug(f"Got message: {response}")
                    await self.handle_event(response)
                except Exception as e:
                    # one bad message must not take the whole connection down
                    self.log.error(f"Error handling message from browser: {e}")

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
        if self._closed:
            return
        # Set first: stop() can be re-entered (the message handler calls it
        # when the connection drops), and it makes every request from here on
        # fail fast instead of waiting on a browser that is going away.
        self._closed = True
        self.log.debug("Stopping browser")

        # Forget all tabs. Chrome is about to be killed, so this only cleans
        # up our side (event handler tasks, queues).
        for tab in list(self.tabs.values()):
            with suppress(Exception):
                await tab.close()

        # Cancel message handler task (unless that's who is calling us)
        handler = self._message_handler_task
        if handler and not handler.done() and handler is not asyncio.current_task():
            handler.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await handler

        # Close websocket. Bounded, because a wedged Chrome never completes
        # the closing handshake.
        websocket, self.websocket = self.websocket, None
        if websocket:
            with suppress(Exception):
                await asyncio.wait_for(websocket.close(), timeout=2)

        # Fail any requests still waiting on a reply
        for future in self.pending_requests.values():
            if not future.done():
                future.set_exception(BrowserClosedError(
                    "Browser stopped before request completed"))

        # Clear collections
        self.pending_requests.clear()
        self.tabs.clear()
        self.event_queues.clear()

        # Kill Chrome and delete its profile. This blocks while Chrome exits,
        # so keep it off the event loop.
        await asyncio.to_thread(self.cleanup)

    async def force_target_cleanup(self):
        """
        Close every page in the browser, tracked or not, leaving one blank page.

        The blank page matters: a Chrome with no pages left can exit, which
        would turn a cheap cleanup into a dead browser.
        """
        try:
            # tabs we know about: close them properly so their handler tasks
            # and event queues go away too
            for tab in list(self.tabs.values()):
                with suppress(Exception):
                    await tab.close()

            # Get all targets using Chrome DevTools Protocol
            response = await self.request("Target.getTargets")
            pages = [t.get("targetId", "") for t in response.get("targetInfos", []) if t.get("type", "") == "page"]

            # open the page that stays, before closing anything
            keeper = (await self.request("Target.createTarget", url="about:blank")).get("targetId")
            if keeper is None and pages:
                # couldn't open one, so spare an existing page instead
                keeper = pages[0]

            for target_id in pages:
                if target_id == keeper:
                    continue
                with suppress(Exception):
                    self.log.debug(f"Closing target {target_id}")
                    await self.request("Target.closeTarget", targetId=target_id)

            # Reset flag
            self.orphaned_session = False

        except BrowserClosedError:
            raise
        except Exception as e:
            self.log.debug(f"Error during forced cleanup: {e}")

    def _signal_chrome(self, sig):
        """Send a signal to Chrome's whole process group"""
        with suppress(OSError):
            if hasattr(os, "killpg"):
                # Chrome is its own session leader, so its pid is the group id
                os.killpg(self.chrome_process.pid, sig)
            elif sig == signal.SIGTERM:
                self.chrome_process.terminate()
            else:
                self.chrome_process.kill()

    def _kill_chrome(self):
        """Stop Chrome and everything it spawned. Blocks until it is gone."""
        process = self.chrome_process
        if process is None:
            return
        if process.poll() is None:
            self._signal_chrome(signal.SIGTERM)
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=self.kill_grace)
        # Unconditional: catches a Chrome that ignored SIGTERM as well as
        # helper processes that outlived the main one.
        self._signal_chrome(getattr(signal, "SIGKILL", signal.SIGTERM))
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)

    def cleanup(self):
        """
        Synchronous last-resort teardown: kill Chrome and delete its profile.

        stop() ends here, and so do atexit and __del__ for a browser that was
        never stopped. Idempotent.
        """
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True
        self._closed = True

        # this browser no longer needs to be kept alive until interpreter exit
        with suppress(Exception):
            atexit.unregister(self.cleanup)

        # First, shutdown process pool
        with suppress(Exception):
            if self._process_pool_instance is not None:
                self._process_pool_instance.shutdown(wait=False)
                self._process_pool_instance = None

        # Next, kill Chrome and wait for it to fully exit
        with suppress(Exception):
            self._kill_chrome()

        with suppress(Exception):
            if self._chrome_log is not None:
                self._chrome_log.close()
                self._chrome_log = None

        # Finally, remove the profile now that nothing has it open
        with suppress(Exception):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    @property
    def _process_pool(self):
        # Created on first use: most callers never need it, and it uses an
        # explicit spawn context so importing webcap doesn't have to change the
        # host process's multiprocessing start method.
        if self._process_pool_instance is None:
            self._process_pool_instance = ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn"))
        return self._process_pool_instance

    def _mark_session_closed(self, session_id):
        """Remember a session_id so its post-close event tail is ignored."""
        if not session_id:
            return
        self._recently_closed_sessions[session_id] = time.time()
        # Bound the dict — drop oldest entries past the cap.
        while len(self._recently_closed_sessions) > _RECENTLY_CLOSED_MAX:
            self._recently_closed_sessions.popitem(last=False)

    def _is_recently_closed(self, session_id):
        """True if session_id was closed within the TTL window."""
        ts = self._recently_closed_sessions.get(session_id)
        if ts is None:
            return False
        if (time.time() - ts) > _RECENTLY_CLOSED_TTL:
            self._recently_closed_sessions.pop(session_id, None)
            return False
        return True

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

    def __del__(self):
        self.cleanup()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
