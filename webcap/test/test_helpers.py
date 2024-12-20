import time
import pytest
import asyncio
from pathlib import Path

from webcap import Browser


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

    # get_keyword_args
    from webcap.helpers import get_keyword_args

    assert get_keyword_args(Browser) == {
        "chrome_path": None,
        "delay": 3.0,
        "dom": False,
        "full_page": False,
        "ignore_types": [
            "Image",
            "Media",
            "Font",
            "Stylesheet",
        ],
        "javascript": False,
        "ocr": False,
        "requests": False,
        "responses": False,
        "base64": False,
        "threads": 15,
        "resolution": "1440x900",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "proxy": None,
    }

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

    # filename truncation
    from webcap.helpers import truncate_filename

    super_long_filename = "/tmp/" + ("a" * 1024) + ".txt"
    with pytest.raises(OSError):
        with open(super_long_filename, "w") as f:
            f.write("wat")
    truncated_filename = truncate_filename(super_long_filename)
    assert truncated_filename.name.endswith(".txt")
    with open(truncated_filename, "w") as f:
        f.write("wat")
    truncated_filename.unlink()
