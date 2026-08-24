#!/usr/bin/env python3
"""Click the wake button on hibernated Streamlit Community Cloud apps.

An HTTP request alone does not always bring one of those apps back: the
hibernation page answers 200 and waits for a real click. This drives a headless
browser to press it, then waits for the app frame to render.

Needs playwright, which the workflow installs on demand.
"""

from __future__ import annotations

import json
import pathlib
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
TARGETS_FILE = ROOT / "targets.json"

WAKE_BUTTON = "text=/get this app back up/i"


def streamlit_targets() -> list[dict]:
    config = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    return [
        target
        for target in config["targets"]
        if target.get("type") == "streamlit" and target.get("enabled", True)
    ]


def wake(page, target: dict) -> bool:
    page.goto(target["url"], wait_until="domcontentloaded", timeout=60_000)
    try:
        button = page.locator(WAKE_BUTTON).first
        button.wait_for(state="visible", timeout=8_000)
    except PlaywrightTimeout:
        print(f"  awake  {target['name']}")
        return True

    print(f"  asleep {target['name']} - clicking wake button")
    button.click()
    try:
        # The app container only mounts once the container has actually restarted.
        page.wait_for_selector("[data-testid='stAppViewContainer']", timeout=180_000)
    except PlaywrightTimeout:
        print(f"  FAIL   {target['name']} did not come back within 3 minutes")
        return False
    print(f"  woken  {target['name']}")
    return True


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
