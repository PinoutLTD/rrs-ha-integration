#!/usr/bin/env bash
# Every test, on a real Home Assistant core.
#
#   scripts/test-ha.sh                        # all tests
#   scripts/test-ha.sh tests/integration -x   # arguments go to pytest
#
# pytest-homeassistant-custom-component pins one Home Assistant release:
# 0.13.366 is homeassistant==2026.9.3, the release CI tests against. Bump both
# together (the plugin's release notes name its HA version).
set -euo pipefail

PHCC="${PHCC:-0.13.366}"

cd "$(dirname "$0")/.."
exec uv run --python 3.14 --extra dev \
  --with "pytest-homeassistant-custom-component==$PHCC" \
  pytest -p pytest_homeassistant_custom_component.plugins -p pytest_freezer "$@"
