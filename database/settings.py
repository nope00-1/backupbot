"""Per-guild settings: tracked role + coowner roles."""

from typing import List, Optional

from database._storage import load_doc, save_doc


_DOC = "settings"


def _load(guild_id: int) -> dict:
    return load_doc(guild_id, _DOC, default={})


def _save(guild_id: int, data: dict) -> None:
    save_doc(guild_id, _DOC, data)


def get_tracked_role(guild_id: int) -> Optional[int]:
    return _load(guild_id).get("tracked_role_id")


def set_tracked_role(guild_id: int, role_id: Optional[int]) -> None:
    s = _load(guild_id)
    if role_id is None:
        s.pop("tracked_role_id", None)
    else:
        s["tracked_role_id"] = int(role_id)
    _save(guild_id, s)


def get_coowner_roles(guild_id: int) -> List[int]:
    return list(_load(guild_id).get("coowner_role_ids", []))


def add_coowner_role(guild_id: int, role_id: int) -> bool:
    s = _load(guild_id)
    rids = s.setdefault("coowner_role_ids", [])
    if role_id in rids:
        return False
    rids.append(int(role_id))
    _save(guild_id, s)
    return True


def remove_coowner_role(guild_id: int, role_id: int) -> bool:
    s = _load(guild_id)
    rids = s.get("coowner_role_ids", [])
    if role_id not in rids:
        return False
    rids.remove(int(role_id))
    _save(guild_id, s)
    return True


def is_coowner(member, guild_id: int) -> bool:
    rids = set(get_coowner_roles(guild_id))
    if not rids:
        return False
    return any(r.id in rids for r in member.roles)
