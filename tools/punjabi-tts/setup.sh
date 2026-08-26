#!/usr/bin/env bash
# Build the Punjabi TTS environment from scratch.
#
# Deliberately its own venv: `hermes update` replaces the Hermes venv wholesale, so isolation
# is what stops an upgrade silently removing Punjabi speech. Since the Google Cloud TTS swap
# (2026-08-23) the venv is one small package — no torch, no GPU, no model download.
#
# Auth (not pip) is the real prerequisite: see README.md.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

HERMES_HOME="${HERMES_HOME:-$HOME/AppData/Local/hermes}"
UV="$HERMES_HOME/bin/uv.exe"; [ -f "$UV" ] || UV="$HERMES_HOME/bin/uv"
[ -f "$UV" ] || UV="$(command -v uv)"
[ -n "${UV:-}" ] || { echo "uv not found - install Hermes Agent first"; exit 1; }

echo "==> venv"
"$UV" venv --python 3.11 .venv

if [ -f .venv/Scripts/python.exe ]; then PY=".venv/Scripts/python.exe"; else PY=".venv/bin/python"; fi

echo "==> google-cloud-texttospeech"
"$UV" pip install --python "$PY" google-cloud-texttospeech

echo "==> verifying"
"$PY" -c "import google.cloud.texttospeech; print('    client library OK')"

cat <<'NEXT'

==> Next: authenticate once, then check:
      gcloud auth application-default login
      python speak.py --setup
NEXT
