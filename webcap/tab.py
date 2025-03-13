import time
import orjson
import asyncio
from contextlib import suppress

from webcap.base import WebCapBase
from webcap.webscreenshot import WebScreenshot
from webcap.errors import WebCapError, DevToolsProtocolError


class Tab(WebCapBase):
    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.tab_id = None
        self.session_id = None
        self.webscreenshot = WebScreenshot(self)
        self._page_loaded = False
        self._page_loaded_future = None
        self._last_active_time = time.time()
        self._incoming_event_queue = asyncio.Queue()
        self._event_handler_task = None
        self._event_handler_started = asyncio.Event()
        self._initial_semaphore_value = 25
        self._semaphore = asyncio.Semaphore(self._initial_semaphore_value)
        self._done_condition = asyncio.Condition()
        self._closed = False

    async def create(self):
        # start event handler
        self._event_handler_task = asyncio.create_task(self.handle_events())
        await self._event_handler_started.wait()
        async with self.browser._tab_lock:
            if self.tab_id is None:
                # Create a new page/tab
                response = await self.browser.request("Target.createTarget", url="about:blank")
                self.tab_id = response["targetId"]
                self.browser.tabs[self.tab_id] = self
            if self.session_id is None:
                response = await self.browser.request("Target.attachToTarget", targetId=self.tab_id, flatten=True)
                self.session_id = response["sessionId"]
                self.browser.event_queues[self.session_id] = self._incoming_event_queue
        # Enable the Page domain to receive events
        await self.request("Page.enable")
        await self.request("Network.enable")
        if self.browser.capture_javascript:
            await self.request("Debugger.enable")
        # await self.request("Runtime.enable")

    async def screenshot(self):
        async with self.browser._tab_lock:
            # switch to our tab
            await self.request("Target.activateTarget", targetId=self.tab_id)
            # Capture the screenshot
            kwargs = {"format": "png", "quality": 100}
            if self.browser.full_page_capture:
                kwargs["captureBeyondViewport"] = True
            response = await self.request("Page.captureScreenshot", **kwargs)
            self.webscreenshot.base64 = response["data"]
        self.webscreenshot.title = await self.get_title()
        return self.webscreenshot

    def request(self, method, **kwargs):
        if self.session_id is None:
            raise WebCapError("You must call create() before making a request")
        return self.browser.request(method, sessionId=self.session_id, **kwargs)

    async def handle_events(self):
        self._event_handler_started.set()
        while not self._closed:
            try:
                event = await self._incoming_event_queue.get()
            except (RuntimeError, asyncio.CancelledError):
                break
            try:
                await self.handle_event(event)
            except Exception as e:
                self.log.error(f"Error handling event: {e}")
                import traceback

                self.log.error(traceback.format_exc())

    async def handle_event(self, event):
        async with self._semaphore:
            event_method = event.get("method")
            params = event.get("params", {})
            self._last_active_time = time.time()
            # page is finished loading
            if event_method == "Page.loadEventFired":
                self._page_loaded = True
            # network request
            elif event_method == "Network.requestWillBeSent":
                await self.add_request(params)
            # network response
            elif event_method == "Network.responseReceived":
                await self.add_response(params)
            # javascript parsed
            elif event_method == "Debugger.scriptParsed" and self.browser.capture_javascript:
                await self.add_javascript(params)

    async def add_request(self, request):
        request_type = request.get("type", "Unknown").lower()
        if request_type in self.browser.ignore_types:
            # self.log.debug(f"Ignoring request type: {request_type}")
            return

        request_id = request.get("requestId", "")
        redirect_response = request.pop("redirectResponse", {})
        request_obj = self.webscreenshot.get_request_obj(request_id, request_type)
        if self.browser.capture_requests:
            request = request.get("request", {})
            try:
                request_obj["requests"].append(request)
            except KeyError:
                request_obj["requests"] = [request]

        if redirect_response:
            await self.add_response(redirect_response, request_id, request_type)

    async def add_response(self, response, request_id=None, response_type=None):
        if request_id is None:
            request_id = response.get("requestId", "")
            if not request_id:
                raise DevToolsProtocolError(f"No requestId found in response: {response}")
        if response_type is None:
            response_type = response.get("type", "").lower()
            if not response_type:
                raise DevToolsProtocolError(f"No response type found in response: {response}")

        if response_type in self.browser.ignore_types:
            # self.log.debug(f"Ignoring response type: {response_type}")
            return

        with suppress(KeyError):
            response = response["response"]

        url = response.get("url", "")
        status_code = response.get("status", 0)
        mime_type = response.get("mimeType", "unknown")
        headers = response.get("headers", {})
        headers = {k.lower(): v for k, v in headers.items()}

        nav_item = {"url": url, "status": status_code, "mimeType": mime_type}
        if str(status_code).startswith("3") and "location" in headers:
            nav_item["location"] = headers["location"]

        request_obj = self.webscreenshot.get_request_obj(request_id, response_type)
        # update with the latest response type (Document, Script, etc)
        request_obj["type"] = response_type

        # capture the response body if requested
        if self.browser.capture_responses:
            history_item = dict(
                **nav_item,
                **{
                    "statusText": response.get("statusText", ""),
                    "headers": headers,
                    "charset": response.get("charset", ""),
                    "protocol": response.get("protocol", ""),
                    "remoteIPAddress": response.get("remoteIPAddress", ""),
                    "remotePort": response.get("remotePort", 0),
                },
            )

            # if it's not a redirect, capture the response body
            # the response body isn't always available right away, so we retry a few times if needed
            response_body = await self.request("Network.getResponseBody", requestId=request_id, retry=True)
            history_item["responseBody"] = response_body.get("body", "")
            try:
                request_obj["responses"].append(history_item)
            except KeyError:
                request_obj["responses"] = [history_item]

        if response_type == "document" and not "":
            self.webscreenshot.navigation_history.append(nav_item)

    async def add_javascript(self, params):
        script_id = params.get("scriptId", "")
        if script_id:
            response = await self.request("Debugger.getScriptSource", scriptId=script_id)
            source = response.get("scriptSource", "")
            if source:
                self.webscreenshot.add_javascript(source, params.get("url", None))

    async def navigate(self, url):
        self.webscreenshot.url = url
        # navigate to the URL
        await self.request("Page.navigate", url=url)
        # wait for the page to load
        await self.wait_for_page_load()

        # await self.get_technologies()

    async def wait_for_page_load(self):
        time_left = float(self.browser.delay)
        # loop in .1 second increments
        while time_left > 0:
            # if the page reports it's loaded and there's been no activity for 1 second, assume the page is done loading
            if self._page_loaded and time.time() - self._last_active_time > 1:
                break
            await asyncio.sleep(0.1)
            time_left -= 0.1
        # page is loaded - dump the dom
        if self.browser.capture_dom:
            self.webscreenshot.dom = await self.get_dom()
        if self._page_loaded_future:
            self._page_loaded_future.set_result(None)

    async def wait_for_finish(self):
        async with self._done_condition:
            await self._done_condition.wait_for(lambda: self._semaphore._value == self._initial_semaphore_value)

    async def close(self):
        # Remove the tab from the browser's tabs and sessions
        self.browser.tabs.pop(self.tab_id, None)
        self.browser.event_queues.pop(self.session_id, None)
        # Disable the Page domain to stop receiving events
        # await self.request("Page.disable")
        # Close the page
        await self.browser.request("Target.closeTarget", targetId=self.tab_id)
        self._closed = True
        # cancel anything waiting on the queue
        for waiter in self._incoming_event_queue._getters:
            if not waiter.done():
                waiter.set_exception(asyncio.CancelledError())

    async def get_dom(self):
        try:
            nodes = await self.request("DOM.getDocument")
            root_node = nodes["root"]
            outer_html = await self.request("DOM.getOuterHTML", nodeId=root_node["nodeId"])
            return outer_html["outerHTML"]
        except Exception as e:
            url = getattr(self.webscreenshot, "url", "")
            self.log.error(f"Error getting DOM for {url}: {e} (available nodes: {list(nodes)})")
            return ""

    async def get_title(self):
        response = await self.request("Page.getNavigationHistory")
        try:
            return response["entries"][-1]["title"]
        except (KeyError, IndexError):
            return ""

    async def get_technologies(self):
        # TODO: find a better way to wait for the technologies
        # await asyncio.sleep(5)
        technologies = []
        if self.browser.wap_session_id is None:
            return technologies
        response = await self.browser.request(
            "Runtime.evaluate",
            sessionId=self.browser.wap_session_id,
            expression=f"JSON.stringify(Driver.cache.hostnames['{self.webscreenshot.hostname}'])",
            awaitPromise=True,
            returnByValue=True,
        )
        technologies = []
        if isinstance(response, dict):
            tech_json = response.get("result", {}).get("value", "")
            if tech_json:
                technologies = orjson.loads(tech_json)
                if "detections" in technologies:
                    for technology in technologies["detections"]:
                        technology = technology.get("technology", {})
                        name = technology.get("name", "")
                        categories = technology.get("categories", [])
                        icon = technology.get("icon", "")
                        slug = technology.get("slug", "")
                        technologies[name] = {"categories": categories, "icon": icon, "slug": slug}
        return technologies
