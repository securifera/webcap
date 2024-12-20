import base64
import pytest
import logging
import extractous

from webcap import Browser
from webcap.test.helpers import *
from webcap.webscreenshot import WebScreenshot

logging.getLogger().setLevel(logging.DEBUG)


@pytest.mark.asyncio
async def test_screenshot(webcap_httpserver, temp_dir):
    url = webcap_httpserver.url_for("/")

    # create browser and take screenshot
    browser = Browser(user_agent="testagent")
    await browser.start()
    webscreenshot = await browser.screenshot(url)

    # decode screenshot and write to file
    assert isinstance(webscreenshot, WebScreenshot)
    image_bytes = base64.b64decode(webscreenshot.base64)
    image_path = temp_dir / "screenshot.png"
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # extract text from image
    extractor = extractous.Extractor()
    reader, metadata = extractor.extract_file(str(image_path))
    frank = reader.read(99999).decode()
    assert "hello frank" in frank
    assert "user-agent: testagent" in frank

    # clean up
    image_path.unlink()
    await browser.stop()


@pytest.mark.asyncio
async def test_screenshot_redirect(webcap_httpserver):
    url = webcap_httpserver.url_for("/test2")
    browser = Browser(responses=True)
    await browser.start()
    webscreenshot = await browser.screenshot(url)

    # distill navigation history down into url, status, and mimetype
    assert webscreenshot.navigation_history == [
        {
            "url": webcap_httpserver.url_for("/test2"),
            "status": 302,
            "mimeType": "text/plain",
            "location": webcap_httpserver.url_for("/test3"),
        },
        {
            "url": webcap_httpserver.url_for("/test3"),
            "status": 302,
            "mimeType": "text/plain",
            "location": webcap_httpserver.url_for("/"),
        },
        {"url": webcap_httpserver.url_for("/"), "status": 200, "mimeType": "text/html"},
    ]

    assert len(webscreenshot.network_history) == 3

    assert len(webscreenshot.responses) == 5
    assert webscreenshot.requests == []

    assert not any("requests" in r for r in webscreenshot.network_history)
    assert [r["type"] for r in webscreenshot.network_history] == ["document", "script", "other"]
    responses_1, responses_2, responses_3 = [r["responses"] for r in webscreenshot.network_history]
    assert len(responses_1) == 3
    assert len(responses_2) == 1
    assert len(responses_3) == 1
    assert [r["url"] for r in responses_1] == [
        webcap_httpserver.url_for("/test2"),
        webcap_httpserver.url_for("/test3"),
        webcap_httpserver.url_for("/"),
    ]
    assert [r["url"] for r in responses_2] == [webcap_httpserver.url_for("/js.js")]
    assert [r["url"] for r in responses_3] == [webcap_httpserver.url_for("/favicon.ico")]
    assert [r["status"] for r in responses_1] == [302, 302, 200]
    assert [r["status"] for r in responses_2] == [200]
    assert [r["status"] for r in responses_3] == [500]
    assert [r["mimeType"] for r in responses_1] == ["text/plain", "text/plain", "text/html"]
    assert [r["mimeType"] for r in responses_2] == ["application/javascript"]
    assert [r["mimeType"] for r in responses_3] == ["text/plain"]

    await browser.stop()
