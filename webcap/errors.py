class WebCapError(Exception):
    pass


class DevToolsProtocolError(WebCapError):
    pass


class ScreenshotDirError(WebCapError):
    pass


class BrowserClosedError(WebCapError):
    """The browser has stopped (crashed, was killed, or stop() was called)"""
