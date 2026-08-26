#!/usr/bin/env bash
# Enable GPU transcription for faster-whisper on an NVIDIA host.
#
# ⚠ RE-RUN THIS AFTER EVERY `hermes update`. It copies CUDA DLLs into the ctranslate2 package
#   directory, and an upgrade replaces that directory. Nothing will error when it is lost —
#   Hermes catches the CUDA library failure and silently falls back to CPU, so the only symptom
#   is voice notes suddenly taking a minute instead of five seconds.
#
# Measured on an i7-12700H + RTX 3060 Laptop, 2026-08-22, faster-whisper large-v3:
#
#     CPU (int8)     RTF 1.97x   -> a 30 s voice note takes ~60 s
#     CUDA (float16) RTF 0.18x   -> the same note takes ~5 s
#
# That is an 11x speedup and it is the difference between a worker getting an answer while they
# are still holding the phone and one they have stopped waiting for.
#
# Why the copy is needed: `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` puts the DLLs in
# site-packages/nvidia/*/bin, which is on nobody's search path. Neither PATH nor
# os.add_dll_directory reliably resolves them, because Windows does not apply those to the
# TRANSITIVE dependencies ctranslate2.dll loads. Placing them beside ctranslate2.dll works
# because Windows always searches the loading module's own directory first.

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
VENV="$HERMES_HOME/hermes-agent/venv"
UV="$HERMES_HOME/bin/uv.exe"; [ -f "$UV" ] || UV="$HERMES_HOME/bin/uv"

if [ -d "$VENV/Lib/site-packages" ]; then
  SP="$VENV/Lib/site-packages"; PY="$VENV/Scripts/python.exe"      # Windows
else
  SP=$(echo "$VENV"/lib/python*/site-packages); PY="$VENV/bin/python"  # POSIX
fi

if ! command -v nvidia-smi >/dev/null 2>&1 && [ ! -f /c/Windows/System32/nvidia-smi.exe ]; then
  echo "No NVIDIA driver found. Nothing to do - Hermes will use CPU, which works but is ~11x"
  echo "slower on transcription. That is fine on a machine with no GPU."
  exit 0
fi

echo "==> Installing CUDA runtime libraries into the Hermes venv"
"$UV" pip install --python "$PY" nvidia-cublas-cu12 nvidia-cudnn-cu12

echo "==> Copying them beside ctranslate2 (Windows DLL search order)"
CT="$SP/ctranslate2"
[ -d "$CT" ] || { echo "!! ctranslate2 not found at $CT"; exit 1; }
copied=0
for d in "$SP"/nvidia/*/bin; do
  [ -d "$d" ] || continue
  for f in "$d"/*.dll "$d"/*.so*; do
    [ -e "$f" ] || continue
    cp -f "$f" "$CT"/ && copied=$((copied + 1))
  done
done
echo "    copied $copied library files"

echo "==> Verifying ctranslate2 can actually reach the GPU"
"$PY" - <<'PYEOF'
import ctranslate2 as ct
n = ct.get_cuda_device_count()
print(f"    CUDA devices visible: {n}")
if n == 0:
    raise SystemExit("    !! no CUDA device - Hermes will run on CPU")
print("    supported compute types:", sorted(ct.get_supported_compute_types("cuda")))
PYEOF

cat <<'NEXT'

==> Done. Confirm end to end by sending a voice note and watching the logs:
      hermes logs | grep -i "whisper\|cuda"

    If you ever see "faster-whisper CUDA load failed ... falling back to CPU", this script
    needs re-running - most likely because `hermes update` replaced the ctranslate2 directory.
NEXT
