"""
Reliability tests: every way the browser used to hang, leak or die silently.

These run against test/fake_chrome.py instead of a real Chrome, so the failure
paths are deterministic and no browser needs to be installed.
"""

import os
import sys
import time
import select
import shutil
import signal
import asyncio
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager, suppress

import pytest

from webcap.tab import Tab
from webcap.browser import Browser
from webcap.errors import WebCapError, BrowserClosedError

REPO_ROOT = Path(__file__).parent.parent
FAKE_CHROME = Path(__file__).parent / "fake_chrome.py"
START_TIMEOUT = 10


@pytest.fixture
def fake_chrome(tmp_path):
    """Returns a function that builds a fake chrome executable for the given mode"""

    def make(mode=""):
        wrapper = tmp_path / f"fake-chrome-{mode.replace(',', '-') or 'default'}"
        wrapper.write_text(f'#!/bin/sh\nFAKE_CHROME_MODE="{mode}" exec "{sys.executable}" "{FAKE_CHROME}" "$@"\n')
        wrapper.chmod(0o755)
        return str(wrapper)

    return make


@asynccontextmanager
async def launch(chrome_path, **kwargs):
    kwargs.setdefault("timeout", 1)
    kwargs.setdefault("delay", 0.3)
    browser = Browser(chrome_path=chrome_path, **kwargs)
    try:
        await asyncio.wait_for(browser.start(), timeout=START_TIMEOUT)
        yield browser
    finally:
        with suppress(Exception):
            await asyncio.wait_for(browser.stop(), timeout=START_TIMEOUT)
        browser.cleanup()


async def page_targets(browser):
    response = await browser.request("Target.getTargets")
    return [t["targetId"] for t in response["targetInfos"] if t["type"] == "page"]


def pid_is_running(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            # field 3 is the state; Z means it exited and is only waiting to be reaped
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


### STARTUP ###


@pytest.mark.asyncio
async def test_each_browser_gets_its_own_devtools_port(fake_chrome):
    """Two browsers on one host must not share (or steal) a DevTools endpoint"""
    chrome = fake_chrome()
    async with launch(chrome) as browser1, launch(chrome) as browser2:
        assert "--remote-debugging-port=0" in browser1.chrome_flags
        assert browser1.websocket_uri != browser2.websocket_uri

        # a tab left open in one browser is invisible to the other
        await browser1.request("Target.createTarget", url="about:blank")
        assert len(await page_targets(browser1)) == 2
        assert len(await page_targets(browser2)) == 1

        webscreenshot = await browser2.screenshot("http://ok.test/")
        assert webscreenshot.blob == b"fake"
        assert webscreenshot.status_code == 200
        assert webscreenshot.title == "fake title"


@pytest.mark.asyncio
async def test_noisy_chrome_stderr_does_not_block(fake_chrome):
    """Chrome must never block on a stderr pipe that nobody reads"""
    async with launch(fake_chrome("stderr_flood")) as browser:
        webscreenshot = await browser.screenshot("http://ok.test/")
        assert webscreenshot.blob == b"fake"


@pytest.mark.asyncio
async def test_start_gives_up_when_devtools_never_opens(fake_chrome):
    browser = Browser(chrome_path=fake_chrome("no_port"))
    browser.startup_timeout = 1
    try:
        with pytest.raises(WebCapError, match="DevTools"):
            await asyncio.wait_for(browser.start(), timeout=START_TIMEOUT)
        # the half-started chrome must not be left behind
        assert browser.chrome_process.poll() is not None
        assert not browser.temp_dir.exists()
    finally:
        browser.cleanup()


@pytest.mark.asyncio
async def test_start_fails_when_chrome_exits_cleanly(fake_chrome):
    browser = Browser(chrome_path=fake_chrome("exit0"))
    try:
        with pytest.raises(WebCapError, match="exited"):
            await asyncio.wait_for(browser.start(), timeout=START_TIMEOUT)
    finally:
        browser.cleanup()


@pytest.mark.asyncio
async def test_downloads_are_denied(fake_chrome):
    async with launch(fake_chrome()) as browser:
        log = (await browser.request("Fake.getLog"))["log"]
        assert "Browser.setDownloadBehavior" in log


### TABS ###


@pytest.mark.asyncio
async def test_navigation_timeout_closes_the_tab(fake_chrome):
    async with launch(fake_chrome()) as browser:
        assert await browser.screenshot("http://navhang.test/") is None
        # the hung tab is gone from chrome and from our bookkeeping
        assert await page_targets(browser) == ["initial"]
        assert browser.tabs == {}
        assert browser.event_queues == {}
        # and the timed-out request is not left behind
        assert browser.pending_requests == {}


@pytest.mark.asyncio
async def test_late_error_reply_does_not_kill_the_browser(fake_chrome):
    """Chrome answering a request we already gave up on must be harmless"""
    async with launch(fake_chrome()) as browser:
        # the capture times out, the tab is closed, then chrome fails the capture
        assert await browser.screenshot("http://capturehang.test/") is None
        await asyncio.sleep(0.2)
        assert browser.is_alive
        webscreenshot = await browser.screenshot("http://ok.test/")
        assert webscreenshot.blob == b"fake"


@pytest.mark.asyncio
async def test_javascript_dialog_is_dismissed(fake_chrome):
    async with launch(fake_chrome()) as browser:
        webscreenshot = await browser.screenshot("http://dialog.test/")
        assert webscreenshot is not None
        assert webscreenshot.blob == b"fake"


@pytest.mark.asyncio
async def test_capture_error_raises(fake_chrome):
    async with launch(fake_chrome()) as browser:
        with pytest.raises(WebCapError, match="Unable to capture screenshot"):
            await browser.screenshot("http://caperror.test/")
        assert await page_targets(browser) == ["initial"]


@pytest.mark.asyncio
async def test_get_dom_failure_returns_empty_string(fake_chrome):
    async with launch(fake_chrome()) as browser:
        # never created, so every request raises
        tab = Tab(browser)
        assert await tab.get_dom() == ""


### DEAD BROWSER ###


@pytest.mark.asyncio
async def test_dead_browser_is_reported(fake_chrome):
    async with launch(fake_chrome()) as browser:
        assert browser.is_alive
        with suppress(WebCapError):
            await browser.screenshot("http://crash.test/")
        await asyncio.sleep(0.2)
        assert not browser.is_alive
        with pytest.raises(BrowserClosedError):
            await browser.screenshot("http://ok.test/")


### CLEANUP ###


@pytest.mark.asyncio
async def test_force_target_cleanup_closes_strays_but_keeps_one_page(fake_chrome):
    """Cleanup must not close the last page (which can take the whole browser down)"""
    async with launch(fake_chrome("exit_on_last_page")) as browser:
        await browser.request("Target.createTarget", url="http://stray.test/")
        await browser.request("Target.createTarget", url="http://stray2.test/")
        assert len(await page_targets(browser)) == 3

        await browser.force_target_cleanup()
        await asyncio.sleep(0.2)

        assert browser.is_alive
        assert len(await page_targets(browser)) == 1
        webscreenshot = await browser.screenshot("http://ok.test/")
        assert webscreenshot.blob == b"fake"


@pytest.mark.asyncio
async def test_force_target_cleanup_leaves_tabs_in_use_alone(fake_chrome):
    """Only strays are swept. A tab somebody is still using must survive."""
    async with launch(fake_chrome()) as browser:
        tab = Tab(browser)
        await tab.create()
        tab_id = tab.tab_id
        await browser.request("Target.createTarget", url="http://stray.test/")
        assert len(await page_targets(browser)) == 3

        await browser.force_target_cleanup()

        # the stray is gone; the tab in use and the blank page remain
        assert sorted(await page_targets(browser)) == sorted(["initial", tab_id])
        assert browser.tabs == {tab_id: tab}
        # and the tab still works
        await tab.navigate("http://ok.test/")
        webscreenshot = await tab.screenshot()
        assert webscreenshot.blob == b"fake"
        await tab.close()


@pytest.mark.asyncio
async def test_force_target_cleanup_does_not_pile_up_blank_pages(fake_chrome):
    async with launch(fake_chrome()) as browser:
        for _ in range(3):
            await browser.force_target_cleanup()
        assert await page_targets(browser) == ["initial"]


@pytest.mark.asyncio
async def test_stop_kills_chrome_and_removes_profile(fake_chrome):
    async with launch(fake_chrome()) as browser:
        temp_dir = browser.temp_dir
        chrome_process = browser.chrome_process
        assert temp_dir.is_dir()
        await browser.stop()
        assert chrome_process.poll() is not None
        assert not temp_dir.exists()


@pytest.mark.asyncio
async def test_stop_kills_chrome_that_ignores_sigterm(fake_chrome):
    async with launch(fake_chrome("ignore_sigterm")) as browser:
        browser.kill_grace = 0.5
        chrome_process = browser.chrome_process
        start = time.time()
        await browser.stop()
        assert chrome_process.poll() is not None
        assert time.time() - start < 4


def test_chrome_dies_with_its_parent(fake_chrome, tmp_path):
    """If the python process is killed outright, chrome must not outlive it"""
    script = tmp_path / "parent.py"
    script.write_text(
        "import sys, asyncio\n"
        "from webcap import Browser\n"
        "async def main():\n"
        "    browser = Browser(chrome_path=sys.argv[1])\n"
        "    await browser.start()\n"
        "    print(browser.chrome_process.pid, browser.temp_dir, flush=True)\n"
        "    await asyncio.sleep(60)\n"
        "asyncio.run(main())\n"
    )
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    parent = subprocess.Popen([sys.executable, str(script), fake_chrome()], stdout=subprocess.PIPE, env=env)
    chrome_pid = temp_dir = None
    try:
        ready, _, _ = select.select([parent.stdout], [], [], START_TIMEOUT)
        assert ready, "browser never started"
        chrome_pid, temp_dir = parent.stdout.readline().decode().split()
        chrome_pid = int(chrome_pid)
        assert pid_is_running(chrome_pid)

        parent.kill()
        parent.wait(timeout=5)

        deadline = time.time() + 5
        while pid_is_running(chrome_pid) and time.time() < deadline:
            time.sleep(0.1)
        assert not pid_is_running(chrome_pid)
    finally:
        parent.kill()
        if chrome_pid is not None:
            with suppress(OSError):
                os.kill(chrome_pid, signal.SIGKILL)
        # a SIGKILLed parent can't remove its own profile directory
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


### IMPORT SIDE EFFECTS ###


def test_import_does_not_reconfigure_the_host_process():
    code = (
        "import logging, multiprocessing\n"
        "import webcap\n"
        "assert multiprocessing.get_start_method(allow_none=True) is None, 'start method was set'\n"
        "assert logging.getLogger().handlers == [], 'root logger was configured'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
