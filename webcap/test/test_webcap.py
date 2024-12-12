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
    browser = Browser()
    await browser.start()
    webscreenshot = await browser.screenshot(url)

    # distill navigation history down into url, status, and mimetype
    keys = ("url", "status", "mimeType")
    navigation_history = [{k: w[k] for k in keys} for w in webscreenshot.navigation_history]
    assert navigation_history == [
        {"url": webcap_httpserver.url_for("/test2"), "status": 302, "mimeType": "text/plain"},
        {"url": webcap_httpserver.url_for("/test3"), "status": 302, "mimeType": "text/plain"},
        {"url": webcap_httpserver.url_for("/"), "status": 200, "mimeType": "text/html"},
    ]

    network_history = [{k: w[k] for k in keys} for w in webscreenshot.network_history]
    assert network_history == [
        {"url": webcap_httpserver.url_for("/test2"), "status": 302, "mimeType": "text/plain"},
        {"url": webcap_httpserver.url_for("/test3"), "status": 302, "mimeType": "text/plain"},
        {"url": webcap_httpserver.url_for("/"), "status": 200, "mimeType": "text/html"},
        {"url": webcap_httpserver.url_for("/js.js"), "status": 200, "mimeType": "application/javascript"},
        {"url": webcap_httpserver.url_for("/favicon.ico"), "status": 500, "mimeType": "text/plain"},
    ]

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

    monkeypatch.setattr(sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--output", str(temp_dir)])
    await _main()
    captured = capsys.readouterr()
    # assert "hello frank" in captured.out
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "image_base64" not in json_out
    assert "scripts" not in json_out
    assert not any("body" in n for n in json_out["network_history"])
    assert json_out["title"] == "frankie"
    assert json_out["status_code"] == 200
    assert json_out["perception_hash"].startswith("830")
    assert len(json_out["network_history"]) == 3
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
    assert not any("body" in n for n in json_out["network_history"])
    parsed_dom = normalize_html(json_out.pop("dom", ""))
    assert parsed_dom == parsed_rendered

    nav_history = json_out.pop("navigation_history", [])
    assert len(nav_history) == 1
    assert nav_history[0]["url"] == url
    assert nav_history[0]["status"] == 200
    assert nav_history[0]["mimeType"] == "text/html"

    network_history = json_out.pop("network_history", [])
    assert len(network_history) == 3
    assert network_history[0]["url"] == url
    assert network_history[0]["status"] == 200
    assert network_history[0]["mimeType"] == "text/html"
    assert network_history[1]["url"] == webcap_httpserver.url_for("/js.js")
    assert network_history[1]["status"] == 200
    assert network_history[1]["mimeType"] == "application/javascript"
    assert network_history[2]["url"] == webcap_httpserver.url_for("/favicon.ico")
    assert network_history[2]["status"] == 500
    assert network_history[2]["mimeType"] == "text/plain"

    assert json_out == {
        "url": url,
        "final_url": url,
        "title": "frankie",
        "status_code": 200,
        "perception_hash": "830303070f0f3fff",
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
    assert not any("body" in n for n in json_out["network_history"])
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
    assert not any("body" in n for n in json_out["network_history"])

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
    assert all("body" in n for n in json_out["network_history"])
    assert len(json_out["network_history"]) == 3

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
        "javascript": False,
        "responses": False,
        "base64": False,
        "threads": 15,
        "resolution": "1440x900",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "proxy": None,
    }
