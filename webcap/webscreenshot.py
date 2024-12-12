import io
import base64
import asyncio
import imagehash
from PIL import Image
from urllib.parse import urlparse

from webcap.base import WebCapBase
from webcap.javascript import JavaScript
from webcap.helpers import sanitize_filename
from webcap.errors import DevToolsProtocolError


class WebScreenshot(WebCapBase):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.technologies = set()
        self.base64 = None
        self.url = None
        self.title = ""
        self.navigation_history = []
        self.network_history = []
        self.dom = None
        self.scripts = set()
        self._blob = None
        self._perception_hash = None
        self._request_ids = set()
        self._semaphore = asyncio.Semaphore(25)
        self._done_condition = asyncio.Condition()

    @property
    def hostname(self):
        if self.url is None:
            raise ValueError("URL not yet set")
        return urlparse(self.url).hostname

    @property
    def blob(self):
        if self._blob is None:
            if self.base64 is None:
                raise ValueError("Screenshot not yet taken")
            self._blob = base64.b64decode(self.base64)
        return self._blob

    @staticmethod
    def perception_hash(blob):
        # make pillow image from blob
        image = Image.open(io.BytesIO(blob))
        image_hash = imagehash.phash(image)
        return str(image_hash)

    @property
    def filename(self):
        if self.url is None:
            raise ValueError("URL not yet set")
        return sanitize_filename(self.url) + ".png"

    async def json(self):
        # wait until nothing is using self._semaphore
        async with self._done_condition:
            await self._done_condition.wait_for(lambda: self._semaphore._value == 25)

        loop = asyncio.get_running_loop()
        perception_hash = await loop.run_in_executor(self.tab.browser._process_pool, self.perception_hash, self.blob)
        j = {
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "status_code": self.status_code,
            "navigation_history": self.navigation_history,
            "network_history": self.network_history,
            "perception_hash": perception_hash,
        }
        if self.tab.browser.capture_base64:
            j["image_base64"] = self.base64
        if self.tab.browser.capture_dom:
            j["dom"] = self.dom
        if self.tab.browser.capture_javascript:
            j["scripts"] = [script.json for script in self.scripts]
        return j

    def add_javascript(self, raw_text, url=None):
        self.scripts.add(JavaScript(self, raw_text, url))

    async def add_history(self, response, request_id, response_type):
        async with self._semaphore:
            url = response.get("url", "")
            history_item = {
                "url": url,
                "status": response.get("status", 0),
                "statusText": response.get("statusText", ""),
                "headers": response.get("headers", {}),
                "mimeType": response.get("mimeType", ""),
                "charset": response.get("charset", ""),
                "remoteIPAddress": response.get("remoteIPAddress", ""),
                "remotePort": response.get("remotePort", 0),
            }
            navigation_item = dict(history_item)

            # capture the response body if requested
            if self.tab.browser.capture_responses and not request_id in self._request_ids:
                self._request_ids.add(request_id)
                # the response body isn't always available right away, so we retry a few times if needed
                success = False
                retry_delay = 0.1
                # 6 iterations == max retry delay of 6.4 seconds
                for i in range(6):
                    try:
                        response_body = await self.tab.request("Network.getResponseBody", requestId=request_id)
                        history_item["body"] = response_body.get("body", "")
                        success = True
                        break
                    except DevToolsProtocolError as e:
                        self.log.info(f"Error getting response body: {e}, retrying...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                if not success:
                    self.log.error(f"Failed to get response body for {url}")

            self.network_history.append(history_item)
            # if the response came from the main page, add it to the navigation history
            if response_type in ("Document", "redirectResponse"):
                self.navigation_history.append(navigation_item)

    @property
    def final_url(self):
        try:
            return self.navigation_history[-1]["url"]
        except (IndexError, KeyError):
            return self.url

    @property
    def status_code(self):
        try:
            return self.navigation_history[-1]["status"]
        except (IndexError, KeyError):
            return 0

    def __str__(self):
        return f"WebScreenshot(status_code={self.status_code}, url={repr(self.url)}, title={repr(self.title)})"

    def __repr__(self):
        return str(self)
