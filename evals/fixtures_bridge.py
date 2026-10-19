"""Reuse the test team fixture in the red-team suite without duplicating it."""

import importlib.util

from strategy.paths import PROJECT_DIR

_spec = importlib.util.spec_from_file_location("_team_fixtures", PROJECT_DIR / "tests" / "fixtures.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

VALID_TEAM = _mod.VALID_TEAM
team = _mod.team
