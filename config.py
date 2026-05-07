"""
Config loader. Reads config.yaml at startup. Refuses to start if the
file is missing or the token is still the placeholder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


_HERE = Path(__file__).parent
_CONFIG_PATH = _HERE / "config.yaml"
_EXAMPLE_PATH = _HERE / "config.yaml.example"


def _die(msg: str):
    print(f"\n[backup_bot] {msg}\n", file=sys.stderr)
    sys.exit(1)


if not _CONFIG_PATH.exists():
    _die(
        f"config.yaml not found.\n"
        f"  cp {_EXAMPLE_PATH.name} {_CONFIG_PATH.name}\n"
        f"  edit {_CONFIG_PATH.name} and paste your bot token, then run again."
    )

try:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        _cfg = yaml.safe_load(f) or {}
except yaml.YAMLError as e:
    _die(f"config.yaml is not valid YAML: {e}")

BOT_TOKEN: str = (_cfg.get("bot_token") or "").strip()
OWNER_ID: int = int(_cfg.get("owner_id") or 0)

if not BOT_TOKEN or BOT_TOKEN.startswith("PASTE"):
    _die("bot_token is not set in config.yaml — paste your bot token and try again.")

# Where the per-guild SQLite db lives. Auto-created.
DATA_DIR = _HERE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "backup_bot.db"
