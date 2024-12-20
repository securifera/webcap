import pytest
import shutil
import extractous

from webcap.test.helpers import *


@pytest.mark.asyncio
async def test_cli(monkeypatch, webcap_httpserver, capsys, temp_dir):
    url = webcap_httpserver.url_for("/")

    import sys
    import json
    from webcap.cli import _main

    from webcap.helpers import sanitize_filename

    # disable sys.exit
    monkeypatch.setattr(sys, "exit", lambda x: None)

    # clear temp_dir
    shutil.rmtree(temp_dir)

    # basic run
    monkeypatch.setattr(sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--output", str(temp_dir)])
    await _main()
    captured = capsys.readouterr()
    # assert "hello frank" in captured.out
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "ocr" not in json_out
    assert "image_base64" not in json_out
    assert "javascript" not in json_out
    assert "requests" not in json_out
    assert "responses" not in json_out
    assert json_out["title"] == "frankie"
    assert json_out["status_code"] == 200
    assert json_out["perception_hash"].startswith("8")
    assert len(json_out["navigation_history"]) == 1

    filename = sanitize_filename(url)
    screenshot_file = temp_dir / f"{filename}.png"

    # make sure screenshot actually captured the page
    assert screenshot_file.is_file()
    # extract text from image
    extractor = extractous.Extractor()
    reader, metadata = extractor.extract_file(str(screenshot_file))
    frank = reader.read(99999)
    assert "hello frank" in frank.decode()

    # make sure screenshots are written
    screenshot_files = list(temp_dir.glob("*.png"))
    assert len(screenshot_files) == 1
    assert screenshot_files[0].is_file()
    assert screenshot_files[0].name == screenshot_file.name

    # DOM
    monkeypatch.setattr(
        sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--dom", "--output", str(temp_dir)]
    )
    await _main()
    captured = capsys.readouterr()
    assert "hello frank" in captured.out
    json_out = json.loads(captured.out)
    assert "dom" in json_out
    assert "ocr" not in json_out
    assert "image_base64" not in json_out
    assert "javascript" not in json_out
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
    assert perception_hash.startswith("8")

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
    assert "ocr" not in json_out
    assert "image_base64" not in json_out
    assert "javascript" in json_out
    assert "requests" not in json_out
    assert "responses" not in json_out
    assert len(json_out["javascript"]) == 2
    assert all("script" in j for j in json_out["javascript"])

    # Base64 blob
    monkeypatch.setattr(
        sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--base64", "--output", str(temp_dir)]
    )
    await _main()
    captured = capsys.readouterr()
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "ocr" not in json_out
    assert "image_base64" in json_out
    assert "javascript" not in json_out
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
    assert "ocr" not in json_out
    assert "image_base64" not in json_out
    assert "javascript" not in json_out
    assert "requests" not in json_out
    assert "responses" in json_out
    assert "requests" not in json_out
    responses = json_out["responses"]
    assert len(responses) == 3
    assert [r["status"] for r in responses] == [200, 200, 500]
    assert [r["type"] for r in responses] == ["document", "script", "other"]
    assert [r["url"] for r in responses] == [
        webcap_httpserver.url_for("/"),
        webcap_httpserver.url_for("/js.js"),
        webcap_httpserver.url_for("/favicon.ico"),
    ]

    # Network requests
    monkeypatch.setattr(
        sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--requests", "--output", str(temp_dir)]
    )
    await _main()
    captured = capsys.readouterr()
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "ocr" not in json_out
    assert "image_base64" not in json_out
    assert "javascript" not in json_out
    assert "responses" not in json_out
    assert "requests" in json_out
    requests = json_out["requests"]
    assert len(requests) == 3
    assert [r["type"] for r in requests] == ["document", "script", "other"]
    assert [r["url"] for r in requests] == [
        webcap_httpserver.url_for("/"),
        webcap_httpserver.url_for("/js.js"),
        webcap_httpserver.url_for("/favicon.ico"),
    ]

    # ignore script instead of stylesheet
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "webcap",
            "-u",
            url,
            "-U",
            "testagent",
            "--json",
            "--requests",
            "--responses",
            "--javascript",
            "--ignore-types",
            "script",
            "--output",
            str(temp_dir),
        ],
    )
    await _main()
    captured = capsys.readouterr()
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "ocr" not in json_out
    assert "image_base64" not in json_out
    assert "javascript" in json_out
    assert "requests" in json_out
    assert "responses" in json_out
    requests = json_out["requests"]
    assert len(requests) == 4
    assert [r["type"] for r in requests] == ["document", "stylesheet", "image", "other"]
    assert [r["url"] for r in requests] == [
        webcap_httpserver.url_for("/"),
        webcap_httpserver.url_for("/style.css"),
        webcap_httpserver.url_for("/image.png"),
        webcap_httpserver.url_for("/favicon.ico"),
    ]
    responses = json_out["responses"]
    assert len(responses) == 4
    assert [r["type"] for r in responses] == ["document", "stylesheet", "image", "other"]
    assert [r["url"] for r in responses] == [
        webcap_httpserver.url_for("/"),
        webcap_httpserver.url_for("/style.css"),
        webcap_httpserver.url_for("/image.png"),
        webcap_httpserver.url_for("/favicon.ico"),
    ]

    # Don't take screenshots
    shutil.rmtree(temp_dir, ignore_errors=True)
    monkeypatch.setattr(
        sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--no-screenshots", "--output", str(temp_dir)]
    )
    await _main()
    captured = capsys.readouterr()
    # assert "hello frank" in captured.out
    json_out = json.loads(captured.out)
    assert len(json_out["navigation_history"]) == 1
    assert not temp_dir.exists()

    # extract text from image
    monkeypatch.setattr(
        sys, "argv", ["webcap", "-u", url, "-U", "testagent", "--json", "--ocr", "--output", str(temp_dir)]
    )
    await _main()
    captured = capsys.readouterr()
    # assert "hello frank" in captured.out
    json_out = json.loads(captured.out)
    assert "dom" not in json_out
    assert "ocr" in json_out
    assert "image_base64" not in json_out
    assert "javascript" not in json_out
    assert "requests" not in json_out
    assert "responses" not in json_out
    assert json_out["ocr"]
    assert "hello frank" in json_out["ocr"]
