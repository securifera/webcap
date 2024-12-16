import time
import base64
import pytest
import asyncio
import logging
import extractous
from pathlib import Path

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
    assert [r["type"] for r in webscreenshot.network_history] == ["Document", "Script", "Other"]
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


@pytest.mark.asyncio
async def test_helpers(temp_dir):
    # str_or_file_list
    from webcap.helpers import str_or_file_list

    tempfile = Path(temp_dir) / "urls.txt"
    with open(tempfile, "w") as f:
        f.write("https://example.com\nhttps://example.com/page2")
    assert str_or_file_list(["http://evilcorp.com", str(tempfile), "http://evilcorp.org"]) == [
        "http://evilcorp.com",
        "https://example.com",
        "https://example.com/page2",
        "http://evilcorp.org",
    ]
    assert str_or_file_list(tempfile) == [
        "https://example.com",
        "https://example.com/page2",
    ]
    tempfile.unlink()
    assert str_or_file_list("https://example.com") == ["https://example.com"]

    # sanitize_filename
    from webcap.helpers import sanitize_filename

    assert (
        sanitize_filename("https://example.com:8080/page2?a=asdf%20.asdf")
        == "https-example.com-8080-page2-a-asdf-20.asdf"
    )

    # task_pool
    from webcap.helpers import task_pool

    async def test_fn(arg):
        await asyncio.sleep(1)
        return arg

    results = []
    start_time = time.time()
    async for result in task_pool(test_fn, list(range(30))):
        results.append(result)
    elapsed = time.time() - start_time
    assert 2.5 < elapsed < 3.5
    assert len(results) == 30
    assert sorted(results) == list((i, i) for i in range(30))


@pytest.mark.asyncio
async def test_cli(monkeypatch, webcap_httpserver, capsys, temp_dir):
    url = webcap_httpserver.url_for("/")

    import sys
    import json
    from webcap.cli import _main

    # disable sys.exit
    monkeypatch.setattr(sys, "exit", lambda x: None)

    # basic run
    monkeypatch.setattr(sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--output", str(temp_dir)])
    await _main()
    captured = capsys.readouterr()
    # assert "hello frank" in captured.out
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "image_base64" not in json_out
    assert "scripts" not in json_out
    assert "requests" not in json_out
    assert "responses" not in json_out
    assert json_out["title"] == "frankie"
    assert json_out["status_code"] == 200
    assert json_out["perception_hash"].startswith("830")
    assert len(json_out["navigation_history"]) == 1

    # DOM
    monkeypatch.setattr(
        sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--dom", "--output", str(temp_dir)]
    )
    await _main()
    captured = capsys.readouterr()
    assert "hello frank" in captured.out
    json_out = json.loads(captured.out)
    assert "dom" in json_out
    assert "image_base64" not in json_out
    assert "scripts" not in json_out
    assert "requests" not in json_out
    assert "responses" not in json_out
    parsed_dom = normalize_html(json_out.pop("dom", ""))
    assert parsed_dom == parsed_rendered

    nav_history = json_out.pop("navigation_history", [])
    assert len(nav_history) == 1
    assert nav_history[0]["url"] == url
    assert nav_history[0]["status"] == 200
    assert nav_history[0]["mimeType"] == "text/html"

    network_history = json_out.pop("network_history", [])
    assert len(network_history) == 0

    perception_hash = json_out.pop("perception_hash", "")
    assert perception_hash.startswith("830")

    assert json_out == {
        "url": url,
        "final_url": url,
        "title": "frankie",
        "status_code": 200,
    }

    # Javascript
    monkeypatch.setattr(
        sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--javascript", "--output", str(temp_dir)]
    )
    await _main()
    captured = capsys.readouterr()
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "image_base64" not in json_out
    assert "scripts" in json_out
    assert "requests" not in json_out
    assert "responses" not in json_out
    assert len(json_out["scripts"]) == 2

    # Base64 blob
    monkeypatch.setattr(
        sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--base64", "--output", str(temp_dir)]
    )
    await _main()
    captured = capsys.readouterr()
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "image_base64" in json_out
    assert "scripts" not in json_out
    assert "requests" not in json_out
    assert "responses" not in json_out

    # Network responses
    monkeypatch.setattr(
        sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--responses", "--output", str(temp_dir)]
    )
    await _main()
    captured = capsys.readouterr()
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "image_base64" not in json_out
    assert "scripts" not in json_out
    assert "requests" not in json_out
    assert "responses" in json_out
    assert "requests" not in json_out
    assert "responses" in json_out
    responses = json_out["responses"]
    assert len(responses) == 3
    assert [r["status"] for r in responses] == [200, 200, 500]
    assert [r["type"] for r in responses] == ["Document", "Script", "Other"]
    assert [r["url"] for r in responses] == [
        webcap_httpserver.url_for("/"),
        webcap_httpserver.url_for("/js.js"),
        webcap_httpserver.url_for("/favicon.ico"),
    ]

    # sanitize_filename
    from webcap.helpers import sanitize_filename

    filename = sanitize_filename(url)
    screenshot_file = temp_dir / f"{filename}.png"
    assert screenshot_file.is_file()
    # extract text from image
    extractor = extractous.Extractor()
    reader, metadata = extractor.extract_file(str(screenshot_file))
    frank = reader.read(99999)
    assert "hello frank" in frank.decode()

    # get_keyword_args
    from webcap.helpers import get_keyword_args

    assert get_keyword_args(Browser) == {
        "chrome_path": None,
        "delay": 3.0,
        "dom": False,
        "full_page": False,
        "ignored_types": [
            "Image",
            "Media",
            "Font",
            "Stylesheet",
        ],
        "javascript": False,
        "requests": False,
        "responses": False,
        "base64": False,
        "threads": 15,
        "resolution": "1440x900",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "proxy": None,
    }
