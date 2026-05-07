"""Shared helpers — embed colours, line formatter, permission gate."""

import nextcord


ACCENT = 0x5865F2  # discord blurple


def line(label: str, value: str) -> str:
    return f"**{label}** · {value}"


def ok(text: str) -> nextcord.Embed:
    return nextcord.Embed(description=text, color=0x57F287)


def err(text: str) -> nextcord.Embed:
    return nextcord.Embed(description=text, color=0xED4245)


def render_user_text(text: str, member=None, guild=None, *, mode: str = "embed") -> str:
    """Substitute {user} (mention in plain mode, **name** in embed mode),
    {username}, {server}, {member_count}."""
    if not text:
        return ""
    out = text
    if member is not None:
        if mode == "plain":
            out = out.replace("{user}", member.mention)
        else:
            out = out.replace("{user}", f"**{member.display_name}**")
        out = out.replace("{username}", member.name)
    if guild is not None:
        out = out.replace("{server}", guild.name)
        out = out.replace("{member_count}", str(guild.member_count or 0))
    return out


def can_run(member: nextcord.Member, guild_id: int) -> bool:
    """Allowed: bot owner, server owner, anyone holding a coowner role.
    Discord admin perm alone is NOT enough."""
    from config import OWNER_ID
    from database.settings import is_coowner

    if OWNER_ID and member.id == OWNER_ID:
        return True
    if member.guild and member.guild.owner_id == member.id:
        return True
    return is_coowner(member, guild_id)


def refuse_reason(guild_id: int) -> str:
    from database.settings import get_coowner_roles

    if not get_coowner_roles(guild_id):
        return (
            "only the server owner or a coowner role can use this command.\n\n"
            "no coowner role is set yet — the **server owner** needs to run "
            "`/settings coowner add @role` first."
        )
    return "only the server owner or a coowner role can use this command."
