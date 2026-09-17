#!/usr/bin/env bash
# ---- Timu -> GitHub, one command (macOS / Linux) ----------------------
set -u
cd "$(dirname "$0")"
OWNER=sahilsharma0309
REPO=timu

command -v git >/dev/null || { echo "[x] git not found"; exit 1; }

[ -d .git ] || { echo "[timu] initialising git repo…"; git init -q; git branch -M main; }
git add -A
git commit -qm "Timu v2 - extraction engine, transport layer, Streamlit + Flask UIs, tests" \
  || echo "[i] nothing new to commit"
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/$OWNER/$REPO.git"

echo "[timu] pushing -> https://github.com/$OWNER/$REPO"
echo "       If it asks for a password, paste your PERSONAL ACCESS TOKEN (not your GitHub password)."
if git push -u origin main; then
  echo "[ok] done. Deploy: https://share.streamlit.io -> New app -> $OWNER/$REPO -> main -> streamlit_app.py"
else
  echo "[x] push failed — usually a token without 'Contents: write', or the repo already has commits."
  echo "    To overwrite: git push -u origin main --force"
fi
