"""Shared test helpers: puts scripts/ on sys.path and loads fixtures."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "robinhood-swing-copilot")
SCRIPTS = os.path.join(SKILL, "scripts")
HOOK = os.path.join(ROOT, ".claude", "hooks", "order_guard.py")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import swing  # noqa: E402

RULES = swing.load_rules()


def fixture(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def bar(d, o, h, l, c, v=1_000_000):
    return {"date": d, "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": v}
