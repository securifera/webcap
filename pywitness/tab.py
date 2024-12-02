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

    async def request(self, method, **kwargs):
        if self.session_id is None:
            raise PywitnessError("You must call create() before making a request")
        request, future = self.browser._build_request(method, **kwargs)
        request["sessionId"] = self.session_id
        await self.browser._send_request(request)
        return await future

    async def handle_event(self, event):
        self.log.info(f"SESSION {self.session_id} GOT EVENT: {event}")
        if event.get("method") == "Page.loadEventFired":
            self._page_loaded_future.set_result(None)

    async def navigate(self, url):
        # Navigate to the URL
        self._page_loaded_future = asyncio.Future()
        await self.request("Page.navigate", url=url)
        await self._page_loaded_future

    async def screenshot(self, x=800, y=600):
        # Capture the screenshot
        response = await self.request("Page.captureScreenshot", format="png", quality=100, width=x, height=y)
        return response["data"]

    async def close(self):
        # Disable the Page domain to stop receiving events
        await self.request("Page.disable")
        # Close the page
        await self.browser.request("Target.closeTarget", targetId=self.tab_id)
        # Remove the tab from the browser's tabs and sessions
        self.browser.tabs.pop(self.tab_id, None)
        self.browser.sessions.pop(self.session_id, None)
