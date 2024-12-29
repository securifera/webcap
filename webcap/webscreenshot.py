import io
import base64
import asyncio
import imagehash
from PIL import Image
from urllib.parse import urlparse

from webcap.base import WebCapBase
from webcap.javascript import JavaScript
from webcap.helpers import sanitize_filename


class WebScreenshot(WebCapBase):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.technologies = set()
        self.base64 = None
        self.url = None
        self.title = ""
        self.navigation_history = []
        self.dom = None
        self.scripts = set()
        self._blob = None
        self._ocr_text = None
        self._perception_hash = None

        # holds the request id and data for each request/response
        self._requests = {}

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
    def id(self):
        return self.filename

    @property
    def filename(self):
        if self.url is None:
            raise ValueError("URL not yet set")
        return sanitize_filename(self.url) + ".png"

    async def json(self):
        # before we jsonify, wait until our tab is finished processing
        await self.tab.wait_for_finish()

        loop = asyncio.get_running_loop()
        perception_hash = await loop.run_in_executor(self.tab.browser._process_pool, self.perception_hash, self.blob)
        j = {
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "status_code": self.status_code,
            "navigation_history": self.navigation_history,
            "perception_hash": perception_hash,
        }
        if self.tab.browser.capture_base64:
            j["image_base64"] = self.base64
        if self.tab.browser.capture_dom:
            j["dom"] = self.dom
        if self.tab.browser.capture_javascript:
            j["javascript"] = [script.json for script in self.scripts]
        if self.tab.browser.capture_responses:
            j["responses"] = self.responses
        if self.tab.browser.capture_requests:
            j["requests"] = self.requests
        if self.tab.browser.capture_ocr:
            ocr_text = await self.ocr()
            j["ocr"] = ocr_text
        return j

    def add_javascript(self, script, url=None):
        self.scripts.add(JavaScript(self, script, url))

    def get_request_obj(self, request_id, request_type):
        try:
            return self._requests[request_id]
        except KeyError:
            request_obj = {"type": request_type}
            self._requests[request_id] = request_obj
            return request_obj

    async def ocr(self):
        if self._ocr_text is None:
            loop = asyncio.get_running_loop()
            self._ocr_text = await loop.run_in_executor(None, self._get_ocr_text, self.blob)
        return self._ocr_text

    def _get_ocr_text(self, blob):
        result, _ = self.tab.browser.extractous.extract_bytes_to_string(bytearray(blob))
        return result

    @property
    def network_history(self):
        return list(self._requests.values())

    @property
    def requests(self):
        ret = []
        for request in self._requests.values():
            request_type = request.get("type", "Other")
            for request_item in request.get("requests", []):
                request_item = dict(request_item)
                request_item["type"] = request_type
                ret.append(request_item)
        return ret

    @property
    def responses(self):
        ret = []
        for request in self._requests.values():
            request_type = request.get("type", "Other")
            for response_item in request.get("responses", []):
                response_item = dict(response_item)
                response_item["type"] = request_type
                ret.append(response_item)
        return ret

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
        return f"WebScreenshot(url={repr(self.url)}, status_code={self.status_code}, title={repr(self.title)})"

    def __repr__(self):
        return str(self)
