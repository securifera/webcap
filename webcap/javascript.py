from webcap.base import WebCapBase


class JavaScript(WebCapBase):
    def __init__(self, webscreenshot, raw_text, url=None):
        super().__init__()
        self.webscreenshot = webscreenshot
        self.url = url
        self.raw_text = raw_text

    @property
    def json(self):
        ret = {
            "raw_text": self.raw_text,
        }
        if self.url:
            ret["url"] = self.url
        return ret
