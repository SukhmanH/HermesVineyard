#!/usr/bin/env python3
r"""15-minute liveness check (no LLM). Python twin of heartbeat.sh for Windows hosts, where the
runtime's bash resolution can land on the WSL bash that cannot read C:\ paths.

Installed to $HERMES_HOME/scripts/heartbeat.py by bootstrap.sh - `--script` resolves paths
there, not in the repo. Registered by hermes/cron/setup-jobs.ps1.

-- The watchdog paradox, stated plainly ---------------------------------------------------
This script is itself a cron job. If the ticker stops, THIS DOES NOT RUN, so it cannot be the
thing that tells you cron died. That is what healthchecks.io is for: it is a dead-man's switch
living on someone else's computer. We ping it while healthy; the ABSENCE of a ping is what
raises the alarm. Never "improve" this by making the alerting depend only on this script.

Checks, in order of what kills us silently:
1. Cron ticker freshness - $HERMES_HOME/cron/ticker_heartbeat, refreshed on every ticker wake
   (~60s). Asserts the OUTCOME we care about (jobs fire) rather than the proxy (a process
   exists).
2. Gateway status TEXT - the exit code is 0 even when the gateway is down, so it is worthless
   here and the text is all we have.
3. Ping healthchecks.io when HEALTHCHECKS_URL is set, and ONLY when otherwise healthy.

Empty output = silent tick. Non-zero exit = Hermes raises an alert.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME") or
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes")
TICKER = HOME / "cron" / "ticker_heartbeat"
# The ticker wakes about every 60s (verified: an 8s-old file on a healthy host), so five
# minutes of silence means it has stopped. heartbeat.sh and docs/03 use the same number.
MAX_AGE_S = int(os.environ.get("HEARTBEAT_MAX_TICKER_AGE_S") or 300)

# `hermes gateway status` prints "Gateway is not running" when down. Matching a POSITIVE word
# is the trap: "running" is a substring of "not running", so `if "running" not in text` passes
# happily while the gateway is dead. Match the negative explicitly, then require some positive
# evidence so that empty or unrecognised output still fails.
_DOWN = re.compile(r"not running|not connected|isn't running|stopped|dead", re.I)
_UP = re.compile(r"running|connected", re.I)

ok = True


def fail(msg: str) -> None:
    global ok
    ok = False
    print(f"heartbeat FAIL: {msg}")


# 1. Ticker freshness
if TICKER.is_file():
    age = time.time() - TICKER.stat().st_mtime
    if age > MAX_AGE_S:
        fail(f"cron ticker stale ({age / 60:.0f} min old, max {MAX_AGE_S / 60:.0f} min)")
else:
    fail(f"ticker file missing at {TICKER}")

# 2. Gateway status text (the exit code always lies)
try:
    out = subprocess.run(
        ["hermes", "gateway", "status"], capture_output=True, text=True, timeout=60
    )
    combined = out.stdout + out.stderr
    if _DOWN.search(combined):
        fail(f"gateway reports down: {combined.strip()[:200]}")
    elif not _UP.search(combined):
        fail(f"gateway status text unrecognised: {combined.strip()[:200] or '(empty)'}")
except Exception as exc:  # noqa: BLE001
    fail(f"gateway status check errored: {exc}")

# 3. Dead-man's switch ping - only when configured AND we are otherwise healthy.
# Read the .env directly as a fallback: cron-spawned runs do not inherit the shell environment.
url = os.environ.get("HEALTHCHECKS_URL") or ""
if not url:
    env_file = HOME / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("HEALTHCHECKS_URL="):
                url = line.split("=", 1)[1].strip()
                break

if ok and url:
    try:
        urllib.request.urlopen(url, timeout=15)
    except Exception as exc:  # noqa: BLE001
        # A failed ping is not itself a health failure; healthchecks.io will notice the
        # absence on its own, which is the entire design.
        print(f"heartbeat warn: healthchecks ping failed: {exc}")

print("heartbeat OK" if ok else "heartbeat FAILED")
sys.exit(0 if ok else 1)
