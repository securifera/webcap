import time
import asyncio

from webcap.base import WebCapBase
from webcap.errors import WebCapError
from webcap.webscreenshot import WebScreenshot


class Tab(WebCapBase):
    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.tab_id = None
        self.session_id = None
        self.webscreenshot = WebScreenshot(self)
        self._page_loaded = False
        self._page_loaded_future = None
        self._network_requests = set()
        self._last_active_time = time.time()

    def send_request(self, *args, **kwargs):
        return self.browser.send_request(*args, **kwargs)

    async def create(self):
        if self.tab_id is None:
            # Create a new page/tab
            response = await self.browser.request("Target.createTarget", url="about:blank")
            self.tab_id = response["targetId"]
            self.browser.tabs[self.tab_id] = self
        if self.session_id is None:
            response = await self.browser.request("Target.attachToTarget", targetId=self.tab_id, flatten=True)
            self.session_id = response["sessionId"]
            self.browser.sessions[self.session_id] = self
        # Enable the Page domain to receive events
        await self.request("Page.enable")
        await self.request("Network.enable")

    async def request(self, method, **kwargs):
        if self.session_id is None:
            raise WebCapError("You must call create() before making a request")
        request, future = await self.browser._build_request(method, **kwargs)
        request["sessionId"] = self.session_id
        await self.browser._send_request(request)
        return await future

    async def handle_event(self, event):
        event_method = event.get("method")
        params = event.get("params", {})
        self._last_active_time = time.time()
        # page is finished loading
        if event_method == "Page.loadEventFired":
            self._page_loaded = True
        # a network request is starting
        elif event_method == "Network.requestWillBeSent":
            self._network_requests.add(event["params"]["requestId"])
        # a network request is finished
        elif event_method in ("Network.loadingFinished", "Network.loadingFailed"):
            self._network_requests.discard(event["params"]["requestId"])
        # main request status code
        elif event_method == "Network.responseReceived":
            response = params.get("response", {})
            response_type = params.get("type", "")
            status_code = response.get("status", 0)
            if response_type == "Document":
                self.webscreenshot.status_code = status_code

    async def wait_for_page_load(self):
        time_left = float(self.browser.delay)
        # loop in .1 second increments
        while time_left > 0:
            # if the page reports it's loaded and there's been no activity for 1 second, assume the page is done loading
            if self._page_loaded and time.time() - self._last_active_time > 1:
                break
            await asyncio.sleep(0.1)
        # page is loaded - dump the dom
        self.webscreenshot.dom = await self.get_dom()
        if self._page_loaded_future:
            self._page_loaded_future.set_result(None)

    async def navigate(self, url):
        self.webscreenshot.url = url
        # navigate to the URL
        await self.request("Page.navigate", url=url)
        # wait for the page to load
        await self.wait_for_page_load()
        navigation_history = await self.request("Page.getNavigationHistory")
        navigation_history = [
            {"title": h.get("title", ""), "url": h.get("url", "")} for h in navigation_history["entries"]
        ]
        navigation_history = [h for h in navigation_history if h["url"] != "about:blank"]
        self.webscreenshot.navigation_history = navigation_history

    async def screenshot(self):
        # Capture the screenshot
        kwargs = {"format": "png", "quality": 80}
        if self.browser.full_page_capture:
            kwargs["captureBeyondViewport"] = True
        response = await self.request("Page.captureScreenshot", **kwargs)
        self.webscreenshot.base64 = response["data"]
        return self.webscreenshot

    async def close(self):
        # Remove the tab from the browser's tabs and sessions
        self.browser.tabs.pop(self.tab_id, None)
        self.browser.sessions.pop(self.session_id, None)
        # Disable the Page domain to stop receiving events
        # await self.request("Page.disable")
        # Close the page
        await self.browser.request("Target.closeTarget", targetId=self.tab_id)

    async def get_dom(self):
        nodes = await self.request("DOM.getDocument")
        root_node = nodes["root"]
        outer_html = await self.request("DOM.getOuterHTML", nodeId=root_node["nodeId"])
        return outer_html["outerHTML"]
