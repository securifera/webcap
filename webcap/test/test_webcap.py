import time
import shutil
import base64
import pytest
import asyncio
import logging
import tempfile
import extractous
from pathlib import Path
from lxml import html
from lxml.etree import tostring

from webcap import Browser
from webcap.webscreenshot import WebScreenshot

logging.getLogger().setLevel(logging.DEBUG)


@pytest.fixture
def temp_dir():
    tempdir = Path(tempfile.gettempdir()) / ".webcap-test"
    tempdir.mkdir(parents=True, exist_ok=True)
    yield tempdir
    shutil.rmtree(tempdir)


def normalize_html(html_content):
    # Parse the HTML content
    tree = html.fromstring(html_content)

    # Normalize the tree by stripping whitespace and sorting attributes
    for element in tree.iter():
        if element.text:
            element.text = element.text.strip()
        if element.tail:
            element.tail = element.tail.strip()

        # Create a sorted list of attribute items
        sorted_attrib = sorted(element.attrib.items())

        # Clear existing attributes and set them in sorted order
        element.attrib.clear()
        for k, v in sorted_attrib:
            element.attrib[k] = v.strip()

    # Return the normalized HTML as a string
    return tostring(tree, method="html", encoding="unicode")


html_body = """
<html>
    <head>
        <title>frankie</title>
        <script>
            // when the page loads, add a <p> element to the body
            window.addEventListener("load", function() {
                document.body.innerHTML += "<p>hello frank</p>";
            });
        </script>
    </head>
    <body></body>
</html>
"""
rendered_html_body = """
<html>
    <head>
        <title>frankie</title>
        <script>
            // when the page loads, add a <p> element to the body
            window.addEventListener("load", function() {
                document.body.innerHTML += "<p>hello frank</p>";
            });
        </script>
    </head>
    <body>
        <p>hello frank</p>
    </body>
</html>
"""
parsed_rendered = normalize_html(rendered_html_body)


@pytest.mark.asyncio
async def test_screenshot(httpserver, temp_dir):
    # serve basic web page
    httpserver.expect_request("/").respond_with_data(html_body, headers={"Content-Type": "text/html"})
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
    parsed_dom = normalize_html(json_out.pop("dom", ""))
    assert parsed_dom == parsed_rendered
    assert json_out == {
        "url": url,
        "final_url": url,
        "title": "frankie",
        "status_code": 200,
        "navigation_history": [{"title": "frankie", "url": url}],
        "perception_hash": "87070707070f1f7f",
    }

    from webcap.helpers import sanitize_filename

    filename = sanitize_filename(url)
    screenshot_file = temp_dir / f"{filename}.png"
    assert screenshot_file.is_file()
    # extract text from image
    extractor = extractous.Extractor()
    reader, metadata = extractor.extract_file(str(screenshot_file))
    frank = reader.read(99999)
    assert "hello frank" in frank.decode()
