import io
import base64
import asyncio
import imagehash
from PIL import Image

from webcap.base import WebCapBase
from webcap.helpers import sanitize_filename


class WebScreenshot(WebCapBase):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.technologies = set()
        self.base64 = None
        self.url = None
        self.navigation_history = []
        self.dom = None
        self.status_code = 0
        self._blob = None
        self._perception_hash = None

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

    async def json(self, include_blob=False):
        loop = asyncio.get_running_loop()
        perception_hash = await loop.run_in_executor(self.tab.browser._process_pool, self.perception_hash, self.blob)
        j = {
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "status_code": self.status_code,
            "navigation_history": self.navigation_history,
            "dom": self.dom,
            "perception_hash": perception_hash,
        }
        if include_blob:
            j["base64_blob"] = self.base64
        return j

    @property
    def final_url(self):
        try:
            return self.navigation_history[-1]["url"]
        except (IndexError, KeyError):
            return self.url

    @property
    def title(self):
        try:
            return self.navigation_history[-1]["title"]
        except (IndexError, KeyError):
            return ""

    def __str__(self):
        return f"[{self.status_code}] {self.url} {self.title}"
