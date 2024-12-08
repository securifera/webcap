import time
import asyncio
from pywitness.base import PywitnessBase
from pywitness.errors import PywitnessError


class Tab(PywitnessBase):
    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.tab_id = None
        self.session_id = None
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
            raise PywitnessError("You must call create() before making a request")
        request, future = await self.browser._build_request(method, **kwargs)
        request["sessionId"] = self.session_id
        await self.browser._send_request(request)
        return await future

    async def handle_event(self, event):
        event_method = event.get("method")
        self._last_active_time = time.time()
        # page is finished loading
        if event_method == "Page.loadEventFired":
            asyncio.create_task(self.do_when_done())
        # a network request is starting
        elif event_method == "Network.requestWillBeSent":
            # print("ADDING REQUEST", event["params"]["requestId"])
            self._network_requests.add(event["params"]["requestId"])
        # a network request is finished
        elif event_method in ("Network.loadingFinished", "Network.loadingFailed"):
            # print("REMOVING REQUEST", event["params"]["requestId"])
            self._network_requests.discard(event["params"]["requestId"])

    async def do_when_done(self):
        time_left = float(self.browser.delay)
        # loop in .1 second increments
        while time_left > 0:
            # if no activity for 1 second, assume the page is done loading
            if time.time() - self._last_active_time > 1:
                break
            await asyncio.sleep(0.1)
        if self._page_loaded_future:
            self._page_loaded_future.set_result(None)

    async def navigate(self, url):
        # Navigate to the URL
        self._page_loaded_future = asyncio.Future()
        await self.request("Page.navigate", url=url)
        await self._page_loaded_future
        print("NAVIGATED TO URL")

    async def screenshot(self):
        # Capture the screenshot
        kwargs = {"format": "png", "quality": 80}
        if self.browser.full_page_capture:
            kwargs["captureBeyondViewport"] = True
        response = await self.request("Page.captureScreenshot", **kwargs)
        return response["data"]

    async def close(self):
        # Remove the tab from the browser's tabs and sessions
        self.browser.tabs.pop(self.tab_id, None)
        self.browser.sessions.pop(self.session_id, None)
        # Disable the Page domain to stop receiving events
        # await self.request("Page.disable")
        # Close the page
        await self.browser.request("Target.closeTarget", targetId=self.tab_id)
