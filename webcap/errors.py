class WebCapError(Exception):
    pass


class DevToolsProtocolError(WebCapError):
    pass


class ScreenshotDirError(WebCapError):
    pass


class ChromeInternalError(WebCapError):
    pass
