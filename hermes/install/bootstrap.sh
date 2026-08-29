#!/usr/bin/env bash
# Wire this repo into a Hermes Agent installation.
# Run from the repo root, after `hermes` is installed and `hermes doctor` passes.
#
# Install Hermes Agent first:
#   Linux/macOS/WSL2:  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
#   Windows:           iex (irm https://hermes-agent.nousresearch.com/install.ps1)

set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

echo "==> Repo:   $REPO"
echo "==> Hermes: $HERMES_HOME"

# 1. Identity. SOUL.md is loaded ONLY from the Hermes home directory, never from the working dir.
echo "==> Installing SOUL.md"
mkdir -p "$HERMES_HOME"
cp "$REPO/SOUL.md" "$HERMES_HOME/SOUL.md"

# 2. Config. Never clobber an existing one — it may hold hand-tuned values.
if [ ! -f "$HERMES_HOME/config.yaml" ]; then
  echo "==> Installing config.yaml (EDIT IT: pin a model, set the crew group JID)"
  cp "$REPO/hermes/config.yaml.example" "$HERMES_HOME/config.yaml"
else
  echo "==> config.yaml exists; leaving it alone. Diff against hermes/config.yaml.example yourself."
fi

if [ ! -f "$HERMES_HOME/.env" ]; then
  echo "==> Installing .env (EDIT IT: secrets)"
  cp "$REPO/hermes/env.example" "$HERMES_HOME/.env"
  chmod 600 "$HERMES_HOME/.env"
fi

# 3. Project skills.
#    NOTE: the upstream docs describe `hermes skills trust` for project-local .hermes/skills.
#    That subcommand does NOT exist in v0.20.4 as installed (verified 2026-08-21) - the working
#    route is skills.external_dirs in config.yaml, which loads them identically (source: local).
echo "==> Registering project skills via skills.external_dirs"
# Resolve an interpreter that actually has PyYAML. Ubuntu ships no bare `python` (only
# python3), and with `set -e` a bare `python` here aborts the whole bootstrap at step 3 -
# silently leaving skills unregistered, the heartbeat scripts uninstalled and the agent
# libraries missing, while steps 1-2 look like they worked. Found on the first real Linux
# install, 2026-08-28. The repo venv is preferred because requirements.txt guarantees PyYAML.
PY=""
for cand in "$REPO/.venv/bin/python" python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import yaml" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "    ! No interpreter with PyYAML found. Build the repo venv first:"
  echo "        python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
echo "    using interpreter: $PY"
"$PY" - "$REPO" "$HERMES_HOME" <<'REGEOF'
import io, sys, os, shutil, yaml
from datetime import datetime
repo, hh = sys.argv[1], sys.argv[2]
cfg = os.path.join(hh, "config.yaml")
skills_dir = os.path.join(repo, ".hermes", "skills").replace(os.sep, "/")
text = io.open(cfg, encoding="utf-8").read()
if skills_dir in text:
    print("    already registered")
else:
    shutil.copy2(cfg, cfg + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S"))
    d = yaml.safe_load(text) or {}
    sk = d.get("skills") or {}
    dirs = list(sk.get("external_dirs") or [])
    dirs.append(skills_dir)
    # Append as text rather than round-tripping: PyYAML would strip every comment.
    text = text.rstrip() + "\n\nskills:\n  external_dirs:\n"
    for entry in dirs:
        text += '    - "%s"\n' % entry
    text += "  write_approval: true\n  guard_agent_created: true\n"
    io.open(cfg, "w", encoding="utf-8").write(text)
    print("    registered", skills_dir)
REGEOF
echo "    verify with: hermes skills list | grep spray-log"

# 4. Heartbeat script. `hermes cron create --script` resolves paths under $HERMES_HOME/scripts/,
#    NOT the repo - a script left in the repo is silently never found.
#    Both twins are installed: setup-jobs.sh registers the .sh, setup-jobs.ps1 registers the
#    .py, because on Windows the runtime's bash can resolve to a WSL bash that cannot read
#    C:\ paths. Whichever one is registered, the other is harmless sitting beside it.
echo "==> Installing heartbeat.sh + heartbeat.py into $HERMES_HOME/scripts/"
mkdir -p "$HERMES_HOME/scripts"
cp "$REPO/hermes/install/heartbeat.sh" "$HERMES_HOME/scripts/heartbeat.sh"
cp "$REPO/hermes/install/heartbeat.py" "$HERMES_HOME/scripts/heartbeat.py"
chmod +x "$HERMES_HOME/scripts/heartbeat.sh" "$HERMES_HOME/scripts/heartbeat.py"

# 5. Libraries Hermes reaches for in execute_code. These are NOT the MCP server's dependencies —
#    they must be installed in the interpreter code execution actually uses. Getting this wrong
#    produces a baffling failure weeks later when weather or exports quietly stop working.
# VERIFIED 2026-08-22: execute_code runs on the HERMES AGENT VENV, not on whatever `python`
# resolves to in your shell. Installing with a bare `python -m pip` puts the libraries where
# Hermes will never see them, and the failure surfaces weeks later as "exports stopped working".
# That venv has no pip either - Hermes is installed via uv, so uv is what installs into it.
HERMES_VENV_PY="$HERMES_HOME/hermes-agent/venv/Scripts/python.exe"     # Windows
[ -f "$HERMES_VENV_PY" ] || HERMES_VENV_PY="$HERMES_HOME/hermes-agent/venv/bin/python"  # POSIX
UV_BIN="$HERMES_HOME/bin/uv.exe"
[ -f "$UV_BIN" ] || UV_BIN="$HERMES_HOME/bin/uv"

echo "==> Installing agent-side libraries into the Hermes venv"
if [ -f "$UV_BIN" ] && [ -f "$HERMES_VENV_PY" ]; then
  "$UV_BIN" pip install --python "$HERMES_VENV_PY" httpx openpyxl imapclient beautifulsoup4 lxml
else
  echo "    ! Could not locate the Hermes venv or uv. Install manually, then verify with:"
  echo "      hermes -z \"use execute_code to run: import httpx, openpyxl, imapclient, bs4, lxml\""
fi

echo "==> Verifying execute_code can actually see them"
hermes -z "Use execute_code to run: import httpx, openpyxl, imapclient, bs4, lxml; print('ALL AGENT LIBS OK')"   || echo "    ! Verification failed - weather, listings and exports will break. Fix before M5."

# 6. GPU transcription, if there is a GPU. Safe to run on a CPU-only host - it detects and
#    exits. MUST be re-run after every `hermes update`; see the script header for why.
echo "==> Enabling GPU transcription (no-op without an NVIDIA driver)"
bash "$REPO/hermes/install/enable-gpu-stt.sh" ||   echo "    ! GPU setup did not complete - transcription will run on CPU (~11x slower)"

# 7. Timezone. Global only — there is no per-job timezone upstream.
hermes config set timezone "America/Vancouver" || true
echo "==> System clock check:"
date
echo "    If that is not Pacific time, FIX IT NOW. A box in UTC fires the 06:00 brief at 23:00"
echo "    the previous night and nothing will warn you."

cat <<'NEXT'

==> Bootstrap done. Remaining steps, in order:

  1. hermes model                     # add 9router as an OpenAI-compatible provider, PIN a model
  2. hermes doctor                    # must pass before anything else
  3. hermes chat                      # exercise the whole system with NO WhatsApp attached.
                                      # This is the fastest feedback loop you have — use it.
  4. hermes whatsapp                  # QR-pair the DEDICATED number. Never a personal number.
                                      # Capture the crew group JID and put it in .env.
  5. sudo hermes gateway install --system      # boot service. CRON DOES NOT TICK WITHOUT THIS.
  6. CREW_GROUP_JID=... hermes/cron/setup-jobs.sh
  7. hermes gateway status            # confirm connected, then confirm a job actually fires

==> Teach it what it does not know yet (/learn builds a skill from a source):

  /learn https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/604_2004   # BC IPM Reg
  /learn <product label PDF or directory of them>
  /learn "how we do harvest here"     # dictate it; Hermes writes the skill

NEXT
