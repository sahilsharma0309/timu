#!/usr/bin/env bash
# ---- Timu v2 launcher (macOS / Linux) --------------------------------
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

# Chromium is only needed for JS-rendered sites (RENDER = BROWSER)
if ! python timu_doctor.py --chromium; then
  read -r -p "[timu] Install Chromium for JS-rendered sites? (y/N) " a
  case "$a" in [yY]*) python -m playwright install chromium ;; esac
fi

echo "  TIMU v2 starting -> http://127.0.0.1:7801"
python timu_app.py
