import time
import httpx
import pytest
import shutil
import logging
import tempfile
from pathlib import Path
from werkzeug import Response

from lxml import html
from lxml.etree import tostring


log = logging.getLogger("webcap.tests")


@pytest.fixture
def temp_dir():
    tempdir = Path(tempfile.gettempdir()) / ".webcap-test"
    tempdir.mkdir(parents=True, exist_ok=True)
    yield tempdir
    shutil.rmtree(tempdir, ignore_errors=True)


@pytest.fixture
def webcap_httpserver(make_httpserver):
    httpserver = make_httpserver
    httpserver.clear()

    # httpserver custom response function that returns the headers + user agent
    def custom_response(request):
        body = ""
        for header_name, header_value in request.headers.items():
            header_name = header_name.lower()
            if header_name.startswith("webcap-test") or header_name == "user-agent":
                body += f"{header_name}: {header_value}\n"
        response = Response(html_body.replace("[[body]]", f"<p>{body}</p>"))
        response.headers.add("Content-Type", "text/html")
        return response

    # Set up the httpserver to use the custom response handler
    httpserver.expect_request("/").respond_with_handler(custom_response)
    httpserver.expect_request("/test1").respond_with_data("OK")
    # respond with redirect to /test3
    httpserver.expect_request("/test2").respond_with_data(
        "redirect", status=302, headers={"Location": httpserver.url_for("/test3")}
    )
    httpserver.expect_request("/test3").respond_with_data(
        "redirect2", status=302, headers={"Location": httpserver.url_for("/")}
    )
    # javascript
    httpserver.expect_request("/js.js").respond_with_data(
        "console.log('hello')", headers={"Content-Type": "application/javascript"}
    )
    # css
    httpserver.expect_request("/style.css").respond_with_data(
        "body { background-color: white; }", headers={"Content-Type": "text/css"}
    )

    # loop until the server is ready
    while 1:
        response = httpx.get(httpserver.url_for("/"))
        if response.status_code == 200:
            break
        time.sleep(0.1)

    # Return the configured httpserver
    return httpserver


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

    # Return the normalized HTML as a string with pretty print
    return tostring(tree, method="html", encoding="unicode")  # , pretty_print=True)


html_body = """
<html>
    <head>
        <title>frankie</title>
        <link rel="stylesheet" href="/style.css">
        <script>
            // when the page loads, add a <p> element to the body
            window.addEventListener("load", function() {
                document.body.innerHTML += "<p>hello frank</p>";
            });
        </script>
        <script src="/js.js"></script>
    </head>
    <body>[[body]]</body>
</html>
"""
rendered_html_body = """
<html>
    <head>
        <title>frankie</title>
        <link rel="stylesheet" href="/style.css">
        <script>
            // when the page loads, add a <p> element to the body
            window.addEventListener("load", function() {
                document.body.innerHTML += "<p>hello frank</p>";
            });
        </script>
        <script src="/js.js"></script>
    </head>
    <body>
        <p>user-agent: testagent</p>
        <p>hello frank</p>
    </body>
</html>
"""
parsed_rendered = normalize_html(rendered_html_body)
