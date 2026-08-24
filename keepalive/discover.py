#!/usr/bin/env python3
"""Add every deployed repository homepage to targets.json.

Run locally (needs the gh CLI, already authenticated):

    python keepalive/discover.py            # show what would be added
    python keepalive/discover.py --write    # add the new targets

Existing entries are never overwritten, so hand-tuned targets and disabled
placeholders survive a re-run.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

TARGETS_FILE = pathlib.Path(__file__).resolve().parent / "targets.json"


def gh_repo_homepages() -> list[tuple[str, str]]:
    command = [
        "gh", "repo", "list", "--limit", "200", "--no-archived",
        "--json", "name,homepageUrl,isArchived",
    ]
    try:
        raw = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("gh CLI not found. Install it from https://cli.github.com and run gh auth login.")
    except subprocess.CalledProcessError as error:
        sys.exit(f"gh failed: {error.stderr.strip()}")

    found = []
    for repo in json.loads(raw):
        url = (repo.get("homepageUrl") or "").strip().rstrip("/")
        if url.startswith("http"):
            found.append((repo["name"], url))
    return sorted(found)


def normalise(url: str) -> str:
    return url.split("?")[0].rstrip("/").lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="save the new targets")
    args = parser.parse_args()

    config = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    known = {normalise(t["url"]) for t in config["targets"]}

    additions = []
    for name, url in gh_repo_homepages():
        if normalise(url) in known:
            continue
        target = {"name": name, "url": url, "type": "http"}
        if "streamlit.app" in url:
            target["type"] = "streamlit"
        additions.append(target)
        known.add(normalise(url))

    if not additions:
        print("Nothing new. Every repository homepage is already a target.")
        return 0

    for target in additions:
        print(f"+ {target['name']:<32} {target['url']}")

    if not args.write:
        print("\nDry run. Re-run with --write to add these.")
        return 0

    config["targets"].extend(additions)
    TARGETS_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"\nAdded {len(additions)} target(s) to {TARGETS_FILE.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
