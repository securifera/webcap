import base64

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

    @property
    def blob(self):
        if self.base64 is None:
            raise ValueError("Screenshot not yet taken")
        return base64.b64decode(self.base64)

    @property
    def filename(self):
        if self.url is None:
            raise ValueError("URL not yet set")
        return sanitize_filename(self.url) + ".png"

    def json(self, include_blob=False):
        j = {
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "status_code": self.status_code,
            "navigation_history": self.navigation_history,
            "dom": self.dom,
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
