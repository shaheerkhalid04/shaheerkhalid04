# keepalive

Keeps every deployed app awake, and keeps the cron jobs that do it from being
switched off.

Three things put a free-tier app to sleep, and each needs a different answer:

| What sleeps | When | Handled by |
|:--|:--|:--|
| Render / Railway / Fly free web services | ~15 idle minutes | `keepalive.yml`, every 10 minutes |
| Streamlit Community Cloud apps | ~7 quiet days, and the wake page needs a real click | `wake-streamlit.yml`, every 2 days |
| Supabase free projects | 7 days with no request | a `supabase` target in `targets.json` |
| Your own scheduled workflows | GitHub disables them after 60 days of repository inactivity | `actions-alive.yml`, weekly |

Vercel deployments do not sleep. They are still pinged, because a ping that
fails is how you find out a deployment broke.

## Files

- `targets.json` — the list of things to keep awake.
- `ping.py` — hits every enabled target, writes `status.json`, exits non-zero if a required one is down. Standard library only.
- `discover.py` — adds every repository homepage from `gh repo list` as a target.
- `wake_streamlit.py` — drives a headless browser to press the Streamlit wake button.
- `status.json` — full last result: timings, status codes, errors. Not committed, because it changes every run.
- `state.txt` — just up or down per target. This is what gets committed, so history only records real changes.
- `heartbeat.txt` — a date stamp written every 20 quiet days, so this repository never goes 60 days without a commit and has its own cron switched off.

## Adding a target

```json
{
  "name": "Attune backend",
  "url": "https://attune-api.onrender.com/health",
  "type": "http"
}
```

Optional per-target keys: `enabled` (default `true`), `required` (default
`true` — a failure opens an issue), `timeout`, `retries`, `expect_status`, and
`headers`. Any `${NAME}` inside a url or header value is filled from the
environment, so secrets never sit in the file.

To pull in everything deployed from a repository homepage:

```bash
python keepalive/discover.py --write
```

## Setup

1. For each Supabase project, add `SUPABASE_URL` and `SUPABASE_ANON_KEY` as repository secrets, then enable that target.
2. For `actions-alive.yml`, create a personal access token with `repo` and `workflow` scope and store it as the `KEEPALIVE_TOKEN` secret. Without it the sweep can only see this repository.

## Running it by hand

```bash
python keepalive/ping.py
```

Or from the Actions tab: **keepalive → Run workflow**.

## When something is down

The run opens a single issue labelled `keepalive`, comments on it on every
further failure rather than opening a second one, and closes it automatically
once everything answers again.

## A note on the 10 minute cron

Scheduled workflows are free on public repositories. GitHub queues cron runs on
a best-effort basis and drops them under load, so treat 10 minutes as a target
rather than a guarantee — it is comfortably inside Render's 15 minute idle
window even when a run is skipped.
