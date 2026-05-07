"""backup_bot — entrypoint. See README."""

import asyncio
import logging
import sys

import nextcord
from nextcord.ext import commands

from config import BOT_TOKEN
from commands import register_all


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("nextcord").setLevel(logging.WARNING)
logging.getLogger("nextcord.voice_client").setLevel(logging.ERROR)
log = logging.getLogger("backup_bot")


intents = nextcord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.event
async def on_ready():
    parts = [f"{g.name!r} (id={g.id}, owner={g.owner_id})" for g in bot.guilds]
    log.info("started as %s — %s", bot.user, ", ".join(parts) or "no guilds")
    try:
        await bot.sync_all_application_commands()
    except Exception:
        log.exception("command sync failed")
    if not getattr(bot, "_started", False):
        bot._started = True
        bot.loop.create_task(_prune())


@bot.event
async def on_member_update(before, after):
    from database import add_hitter, get_tracked_role
    tracked = get_tracked_role(after.guild.id)
    if not tracked:
        return
    if tracked in {r.id for r in after.roles} and tracked not in {r.id for r in before.roles}:
        add_hitter(after.guild.id, after.id, username=str(after))


@bot.event
async def on_member_remove(member):
    from database import mark_left
    mark_left(member.guild.id, member.id)


@bot.event
async def on_member_join(member):
    from database import has_left_mark, clear_left
    if has_left_mark(member.guild.id, member.id):
        clear_left(member.guild.id, member.id)
        asyncio.create_task(_recheck(member))


async def _recheck(member, delay=600):
    await asyncio.sleep(delay)
    from database import remove_hitter, get_all_hitters, get_tracked_role
    if member.id not in {h.get("user_id") for h in get_all_hitters(member.guild.id)}:
        return
    tracked = get_tracked_role(member.guild.id)
    if not tracked:
        return
    fresh = member.guild.get_member(member.id)
    if fresh and not any(r.id == tracked for r in fresh.roles):
        remove_hitter(member.guild.id, member.id)


async def _prune():
    from database import prune_stale_left
    await bot.wait_until_ready()
    while not bot.is_closed():
        for g in bot.guilds:
            try:
                prune_stale_left(g.id, ttl_days=7)
            except Exception:
                log.exception("prune %s", g.id)
        await asyncio.sleep(3600)


register_all(bot)


if __name__ == "__main__":
    try:
        bot.run(BOT_TOKEN)
    except nextcord.LoginFailure:
        sys.exit("invalid bot token — check config.yaml")
