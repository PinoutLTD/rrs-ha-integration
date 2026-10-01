#!/usr/bin/env bash
# The test stand: a clean Home Assistant publishing to a development chain.
# See stand/run.py for what runs and what is checked.
#
#   scripts/stand.sh                    # everything, about 10 minutes
#   scripts/stand.sh --skip-heartbeat   # without the 5 min wait for the first beat
set -euo pipefail

# The Home Assistant release CI tests against.
HOME_ASSISTANT="${HOME_ASSISTANT:-2026.9.3}"

cd "$(dirname "$0")/.."

# Without its frontend Home Assistant starts in recovery mode and loads no
# integration; take the exact release this Home Assistant asks for.
FRONTEND=$(uv run --no-project --python 3.14 --with "homeassistant==$HOME_ASSISTANT" python -c '
import json, pathlib, homeassistant.components.frontend as frontend
manifest = json.loads((pathlib.Path(frontend.__file__).parent / "manifest.json").read_text())
print(next(r for r in manifest["requirements"] if r.startswith("home-assistant-frontend==")))
')

exec uv run --python 3.14 --extra dev \
  --with "homeassistant==$HOME_ASSISTANT" --with "$FRONTEND" \
  python stand/run.py "$@"
