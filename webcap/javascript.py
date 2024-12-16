from webcap.base import WebCapBase


class JavaScript(WebCapBase):
    def __init__(self, webscreenshot, script, url=None):
        super().__init__()
        self.webscreenshot = webscreenshot
        self.url = url
        self.script = script

    @property
    def json(self):
        ret = {
            "script": self.script,
        }
        if self.url:
            ret["url"] = self.url
        return ret
