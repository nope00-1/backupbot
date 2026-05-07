"""Per-guild list of users who have held the tracked role.

Cleanup: leave → 7-day grace → drop. Rejoin within grace clears the
stamp; an hourly task prunes anything past the window.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from database._storage import load_doc, save_doc


_DOC = "hitters"


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _load(guild_id: int) -> dict:
    return load_doc(guild_id, _DOC, default={})


def _save(guild_id: int, data: dict) -> None:
    save_doc(guild_id, _DOC, data)


def add_hitter(guild_id: int, user_id: int, username: Optional[str] = None) -> bool:
    data = _load(guild_id)
    key = str(int(user_id))
    is_new = key not in data
    rec = data.get(key) or {}
    rec["user_id"] = int(user_id)
    if username is not None:
        rec["username"] = str(username)
    if is_new:
        rec["added_at"] = _now()
    rec["last_seen"] = _now()
    rec.pop("left_at", None)
    data[key] = rec
    _save(guild_id, data)
    return is_new


def mark_left(guild_id: int, user_id: int) -> bool:
    data = _load(guild_id)
    key = str(int(user_id))
    if key not in data:
        return False
    data[key]["left_at"] = _now()
    _save(guild_id, data)
    return True


def clear_left(guild_id: int, user_id: int) -> bool:
    data = _load(guild_id)
    key = str(int(user_id))
    if key in data and "left_at" in data[key]:
        del data[key]["left_at"]
        _save(guild_id, data)
        return True
    return False


def has_left_mark(guild_id: int, user_id: int) -> bool:
    rec = _load(guild_id).get(str(int(user_id))) or {}
    return "left_at" in rec


def remove_hitter(guild_id: int, user_id: int) -> bool:
    data = _load(guild_id)
    key = str(int(user_id))
    if key in data:
        del data[key]
        _save(guild_id, data)
        return True
    return False


def get_all_hitters(guild_id: int) -> List[Dict]:
    return list(_load(guild_id).values())


def count_hitters(guild_id: int) -> int:
    return len(_load(guild_id))


def prune_stale_left(guild_id: int, ttl_days: int = 7) -> int:
    data = _load(guild_id)
    if not data:
        return 0
    cutoff = _now() - (ttl_days * 86400)
    drop = [k for k, v in data.items() if v.get("left_at") and v["left_at"] < cutoff]
    for k in drop:
        del data[k]
    if drop:
        _save(guild_id, data)
    return len(drop)
