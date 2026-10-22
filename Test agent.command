#!/bin/bash
# Testrun Investing Agent — plaatst GEEN orders (dry-run)
cd "$(dirname "$0")"
{
echo "=== $(date) ==="
PY=""
for c in python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  command -v "$c" >/dev/null 2>&1 && PY="$c" && break
done
echo "Python: $PY ($($PY --version))"
if [ -x .venv/bin/python ] && [ "$(.venv/bin/python --version)" != "$($PY --version)" ]; then rm -rf .venv; fi
[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt && echo "Installatie OK"
pip list 2>/dev/null | grep -iE "alpaca|genai"
echo "--- tests ---";  python -m pytest -q 2>&1 | tail -3
echo "--- status ---"; python -m agent status 2>&1 | tail -20
echo "--- dry-run ---"; python -m agent once --dry-run --ignore-market-hours 2>&1 | tail -60
echo "=== EINDE ==="
} 2>&1 | tee test_output.txt
echo; echo "Klaar. Je mag dit venster sluiten."
