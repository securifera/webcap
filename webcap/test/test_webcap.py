import time
import shutil
import base64
import pytest
import asyncio
import logging
import tempfile
import extractous
from pathlib import Path

from webcap import Browser
from webcap.webscreenshot import WebScreenshot

logging.getLogger().setLevel(logging.DEBUG)


@pytest.fixture
def temp_dir():
    tempdir = Path(tempfile.gettempdir()) / ".webcap-test"
    tempdir.mkdir(parents=True, exist_ok=True)
    yield tempdir
    shutil.rmtree(tempdir)


html_body = "<html><head><title>frankie</title></head><body>hello frank</body></html>"


@pytest.mark.asyncio
async def test_screenshot(httpserver, temp_dir):
    # serve basic web page
    httpserver.expect_request("/").respond_with_data(
        html_body, headers={"Content-Type": "text/html"}
    )
    url = httpserver.url_for("/")

    # create browser and take screenshot
    browser = Browser()
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
    frank = reader.read(99999)
    assert "hello frank" in frank.decode()

    # clean up
    image_path.unlink()
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
async def test_cli(monkeypatch, httpserver, capsys, temp_dir):
    # serve basic web page
    httpserver.expect_request("/").respond_with_data(
        html_body,
        headers={"Content-Type": "text/html"},
    )
    url = httpserver.url_for("/")

    import sys
    import json
    from webcap.cli import _main

    monkeypatch.setattr(sys, "argv", ["webcap", url, "--json", "--output", str(temp_dir)])
    await _main()
    captured = capsys.readouterr()
    assert "hello frank" in captured.out
    json_out = json.loads(captured.out)
    assert json_out["url"] == url
    assert json_out["title"] == "frankie"
    assert json_out["status_code"] == 200
    assert json_out["dom"] == html_body

    from webcap.helpers import sanitize_filename

    filename = sanitize_filename(url)
    screenshot_file = temp_dir / f"{filename}.png"
    assert screenshot_file.is_file()
    # extract text from image
    extractor = extractous.Extractor()
    reader, metadata = extractor.extract_file(str(screenshot_file))
    frank = reader.read(99999)
    assert "hello frank" in frank.decode()
