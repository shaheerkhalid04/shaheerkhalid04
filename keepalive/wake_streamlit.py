#!/usr/bin/env python3
"""Click the wake button on hibernated Streamlit Community Cloud apps.

An HTTP request alone does not reliably revive one of those apps: the
hibernation page answers 200 and waits for a real click. This drives a headless
browser to press it, then waits for the app to actually come back.

The app itself does not live in the top-level document. streamlit.app serves a
shell that embeds the running app in a `/~/+/` iframe, so both the wake button
and the readiness check have to be looked for across every frame.

Needs playwright, which the workflow installs on demand.
"""

from __future__ import annotations

import json
import pathlib
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
TARGETS_FILE = ROOT / "targets.json"

WAKE_BUTTON = "text=/get this app back up/i"
APP_READY = "[data-testid='stAppViewContainer']"

# A cold container has to be scheduled, pull the image and re-run the script.
# Five minutes is generous; the run still finishes well inside the job timeout.
WAKE_TIMEOUT_SECONDS = 300


def streamlit_targets() -> list[dict]:
    config = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    return [
        target
        for target in config["targets"]
        if target.get("type") == "streamlit" and target.get("enabled", True)
    ]


def app_is_rendered(page) -> bool:
    for frame in page.frames:
        try:
            if frame.locator(APP_READY).count():
                return True
        except Exception:  # noqa: BLE001 - a frame can detach mid-check
            continue
    return False


def find_wake_button(page):
    for frame in page.frames:
        try:
            button = frame.locator(WAKE_BUTTON).first
            if button.count() and button.is_visible():
                return button
        except Exception:  # noqa: BLE001 - a frame can detach mid-check
            continue
    return None


def wait_for_app(page, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if app_is_rendered(page):
            return True
        page.wait_for_timeout(5_000)
    return False


def wake(page, target: dict) -> bool:
    page.goto(target["url"], wait_until="domcontentloaded", timeout=90_000)

    # Give the shell a moment to mount its iframe before deciding anything.
    try:
        page.wait_for_timeout(8_000)
    except PlaywrightTimeout:
        pass

    button = find_wake_button(page)
    if button is None:
        if app_is_rendered(page):
            print(f"  awake  {target['name']}")
            return True
        # No button and no app yet: it may still be booting from an earlier ping.
        print(f"  waiting {target['name']} - no wake button, app not rendered yet")
        if wait_for_app(page, time.monotonic() + 90):
            print(f"  awake  {target['name']}")
            return True
        print(f"  FAIL   {target['name']} never rendered")
        return False

    print(f"  asleep {target['name']} - clicking wake button")
    button.click()

    if wait_for_app(page, time.monotonic() + WAKE_TIMEOUT_SECONDS):
        print(f"  woken  {target['name']}")
        return True

    print(f"  FAIL   {target['name']} did not come back within {WAKE_TIMEOUT_SECONDS}s")
    return False


def main() -> int:
    targets = streamlit_targets()
    if not targets:
        print("No Streamlit targets configured.")
        return 0

    failures = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        for target in targets:
            try:
                if not wake(page, target):
                    failures += 1
            except Exception as error:  # noqa: BLE001
                print(f"  ERROR  {target['name']}: {type(error).__name__}: {error}")
                failures += 1
        browser.close()

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
