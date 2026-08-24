#!/usr/bin/env python3
"""Keep-alive pinger.

Reads keepalive/targets.json, hits every enabled target, and writes a status
report to keepalive/status.json. Standard library only: no install step, so the
workflow starts pinging within seconds of the runner booting.

Exit code is 0 when every required target is healthy, 1 otherwise, so the
calling workflow can decide whether to raise an issue.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import pathlib
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
TARGETS_FILE = ROOT / "targets.json"
STATUS_FILE = ROOT / "status.json"
STATE_FILE = ROOT / "state.txt"

USER_AGENT = "keepalive-bot/1.0 (+https://github.com/shaheerkhalid04/shaheerkhalid04)"

# Text that Streamlit Community Cloud serves once an app has been hibernated.
# An HTTP 200 is not proof of life for those, so the body has to be inspected.
SLEEP_MARKERS = (
    "get this app back up",
    "this app has gone to sleep",
    "yes, get this app back up",
    "zzzz",
)


def load_config() -> dict:
    with TARGETS_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


def expand_env(value: str) -> str:
    """Allow ${SECRET_NAME} placeholders inside urls and headers."""
    return os.path.expandvars(value) if "$" in value else value


def fetch(url: str, headers: dict, timeout: int) -> tuple[int, str]:
    # Streamlit sets a cookie and redirects to itself, which urlopen alone reads
    # as an infinite loop. A per-request cookie jar lets the redirect resolve so
    # the real body can be checked for a hibernation page.
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    with opener.open(request, timeout=timeout) as response:
        body = response.read(65536).decode("utf-8", "replace")
        return response.status, body


def probe(target: dict, defaults: dict) -> dict:
    url = expand_env(target["url"])
    timeout = target.get("timeout", defaults["timeout"])
    retries = target.get("retries", defaults["retries"])
    accepted = set(target.get("expect_status", defaults["expect_status"]))
    headers = {k: expand_env(v) for k, v in target.get("headers", {}).items()}

    result = {
        "name": target["name"],
        "url": url.split("?")[0],
        "type": target.get("type", "http"),
        "required": target.get("required", True),
    }

    last_error = None
    for attempt in range(retries):
        started = time.monotonic()
        try:
            status, body = fetch(url, headers, timeout)
            elapsed_ms = round((time.monotonic() - started) * 1000)

            if status not in accepted:
                last_error = f"HTTP {status}"
            elif any(marker in body.lower() for marker in SLEEP_MARKERS):
                last_error = "served a hibernation page"
                result["hibernating"] = True
            else:
                result.update(ok=True, status=status, ms=elapsed_ms, attempts=attempt + 1)
                return result
        except urllib.error.HTTPError as error:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            if error.code in accepted:
                result.update(ok=True, status=error.code, ms=elapsed_ms, attempts=attempt + 1)
                return result
            last_error = f"HTTP {error.code}"
        except Exception as error:  # noqa: BLE001 - any failure is just "down"
            last_error = f"{type(error).__name__}: {error}"

        # A cold container needs longer than a warm one; back off before retrying.
        if attempt + 1 < retries:
            time.sleep(2 ** attempt * 3)

    result.update(ok=False, error=last_error, attempts=retries)
    return result


def main() -> int:
    config = load_config()
    defaults = config["defaults"]
    targets = [t for t in config["targets"] if t.get("enabled", True)]

    results = [probe(target, defaults) for target in targets]
    failed = [r for r in results if not r["ok"]]
    blocking = [r for r in failed if r["required"]]

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(results),
        "up": len(results) - len(failed),
        "down": len(failed),
        "results": sorted(results, key=lambda r: (r["ok"], r["name"])),
    }
    STATUS_FILE.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    # status.json changes on every run because of the timestamp and timings, and
    # committing that 144 times a day would bury the repository history. state.txt
    # holds only up or down, so it changes when something actually changes, and
    # that is the file the workflow commits.
    state = "\n".join(
        f"{entry['name']}\t{'up' if entry['ok'] else 'down'}"
        for entry in sorted(report["results"], key=lambda r: r["name"])
    )
    STATE_FILE.write_text(state + "\n", encoding="utf-8")

    for entry in report["results"]:
        if entry["ok"]:
            print(f"  up   {entry['name']:<28} {entry['status']} in {entry['ms']}ms")
        else:
            flag = "FAIL" if entry["required"] else "warn"
            print(f"  {flag} {entry['name']:<28} {entry['error']}")

    print(f"\n{report['up']}/{report['total']} awake at {report['checked_at']}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = ["| Target | State | Detail |", "|:--|:--|:--|"]
        for entry in report["results"]:
            state = "awake" if entry["ok"] else "DOWN"
            detail = f"{entry['ms']}ms" if entry["ok"] else entry["error"]
            lines.append(f"| {entry['name']} | {state} | {detail} |")
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    if blocking:
        names = ", ".join(r["name"] for r in blocking)
        print(f"\nRequired targets down: {names}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
