import time
import pytest
import asyncio
from pathlib import Path


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

    # filename truncation
    from webcap.helpers import truncate_filename

    super_long_filename = "/tmp/" + ("a" * 1024) + ".txt"
    with pytest.raises(OSError):
        with open(super_long_filename, "w") as f:
            f.write("wat")
    truncated_filename = truncate_filename(super_long_filename, 256)
    assert truncated_filename.name == "a" * 252 + ".txt"
    with pytest.raises(OSError):
        with open(truncated_filename, "w") as f:
            f.write("wat")
    truncated_filename = truncate_filename(super_long_filename)
    assert truncated_filename.name == "a" * 251 + ".txt"
    with open(truncated_filename, "w") as f:
        f.write("wat")
    truncated_filename.unlink()
