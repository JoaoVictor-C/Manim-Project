#!/usr/bin/env bash
# The whole restructure, in order. Run from the root of the tree to change.
set -euo pipefail
SP="C:/Users/joaoc/AppData/Local/Temp/claude/C--Joao-Programa--o-ProjectHub-Manim-Project/efc32611-1180-448a-a04c-2f973094ab5e/scratchpad"
PY="${PY:-C:/Joao/Programação/ProjectHub/Manim-Project/.venv/Scripts/python.exe}"
echo "== codemod";  "$PY" "$SP/codemod.py" apply "$SP/moves.json"
echo "== manual";   "$PY" "$SP/manual_fixes.py"
echo "== ruff";     "$PY" -m ruff check --select I,F401 --fix -q . || true
                    "$PY" -m ruff format -q .
                    "$PY" -m ruff check . && echo "ruff clean"
