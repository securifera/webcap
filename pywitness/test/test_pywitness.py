import base64
import pytest
import logging
import tempfile
import extractous
from pathlib import Path

from pywitness import Browser

logging.getLogger().setLevel(logging.DEBUG)

temp_dir = Path(tempfile.gettempdir())


@pytest.mark.asyncio
async def test_screenshot(httpserver):
    # serve basic web page
    httpserver.expect_request("/").respond_with_data(
        b"<html><body>hello frank</body></html>", headers={"Content-Type": "text/html"}
    )
    url = httpserver.url_for("/")

    # create browser and take screenshot
    browser = Browser()
    await browser.start()
    encoded_screenshot = await browser.screenshot(url)

    # decode screenshot and write to file
    assert isinstance(encoded_screenshot, str)
    image_bytes = base64.b64decode(encoded_screenshot)
    image_path = temp_dir / "screenshot.png"
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # extract text from image
    extractor = extractous.Extractor()
    reader, metadata = extractor.extract_file(str(image_path))
    frank = reader.read(99999)
    print(frank)
    assert "hello frank" in frank.decode()

    # clean up
    image_path.unlink()
    await browser.stop()
