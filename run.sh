#!/usr/bin/env bash
# Launcher with three startup paths, in priority order:
#   1. CONDA_ENV (default "cheiron") if conda is available — recommended
#   2. ./.venv if a virtualenv exists locally
#   3. system python — last resort
# .env is loaded inside the app via python-dotenv.
set -euo pipefail
cd "$(dirname "$0")"

CONDA_ENV="${CONDA_ENV:-cheiron}"
PORT="${PORT:-8000}"

if command -v conda >/dev/null 2>&1 \
   && conda env list 2>/dev/null | awk '{print $1}' | grep -qx "$CONDA_ENV"; then
  echo "Using conda env: $CONDA_ENV"
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "$CONDA_ENV"
elif [ -x ".venv/bin/uvicorn" ]; then
  echo "Using local venv: .venv"
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "Falling back to system python (no conda env '$CONDA_ENV', no .venv)"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
