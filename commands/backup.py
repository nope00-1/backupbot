"""/backup wizard. See README."""

from __future__ import annotations

import asyncio
import io
from datetime import datetime
from typing import Optional

import nextcord
from nextcord import Interaction, ui
from nextcord.ext import commands

from database import get_all_hitters, count_hitters, add_hitter, get_tracked_role
from commands._helpers import can_run, refuse_reason, ok, err, line, ACCENT


# (guild, channel, user) → session for the Import File listener.
_import_sessions: dict[tuple, dict] = {}


async def _deliver(invoker: nextcord.User, interaction: Interaction, *,
                   content: Optional[str] = None,
                   embed: Optional[nextcord.Embed] = None,
                   file: Optional[nextcord.File] = None) -> bool:
    """DM the invoker; fall back to an ephemeral followup if DMs closed."""
    try:
        await invoker.send(content=content, embed=embed, file=file)
        return True
    except Exception:
        pass
    try:
        prefix = "(your DMs are closed — sending here)"
        await interaction.followup.send(
            content=(prefix if not content else f"{prefix}\n{content}"),
            embed=embed, file=file, ephemeral=True,
        )
        return True
    except Exception:
        return False


def _overview_embed(guild) -> nextcord.Embed:
    n = count_hitters(guild.id)
    tracked = get_tracked_role(guild.id)
    role_line = f"<@&{tracked}>" if tracked else "`not set` — run `/settings role`"
    emb = nextcord.Embed(
        title="Hitter List — Backup",
        color=ACCENT,
    )
    emb.description = (
        f"{line('hitters on file', f'`{n}`')}\n"
        f"{line('tracked role', role_line)}\n\n"
        f"pick an action below"
    )
    return emb


def _explain_embed(guild) -> nextcord.Embed:
    emb = nextcord.Embed(
        title="Hitter List — what is this?",
        color=ACCENT,
    )
    emb.description = (
        "**the problem**\n"
        "a role can be deleted by accident, or a bad actor with manage-roles "
        "can delete it on purpose to harm the server. when that happens "
        "everyone holding that role loses it at once and you've got no "
        "record of who they were.\n\n"
        "**the fix**\n"
        "the bot keeps its own list of every user who has ever held the "
        "tracked role (configured via `/settings role`). the list survives "
        "even if the role is gone.\n\n"
        "**how the list fills itself** (no command needed)\n"
        "• someone gets the tracked role → added\n"
        "• saved username refreshes every time we see them\n\n"
        "**auto-cleanup**\n"
        "• a hitter leaves the server → kept for 7 days\n"
        "• back within 7 days → kept if they still have the tracked role, dropped if not\n"
        "• 7 days pass without return → dropped\n\n"
        "**what the buttons do**\n"
        f"{line('Ping All Hitters', 'mention list sent to your DMs — paste anywhere you want to ping')}\n"
        f"{line('Export File', '.txt of the list, sent to your DMs')}\n"
        f"{line('Mass DM', 'form with format (plain or embed) + body using {{user}}')}\n"
        f"{line('Role All', 'pick any role, granted to every hitter — recovers from a deleted role')}\n"
        f"{line('Sync from Role', 'adds current tracked-role holders missing from the list')}\n"
        f"{line('Import File', 'bulk-add from a .txt of user IDs')}\n\n"
        "**who can run this**\n"
        "bot owner, server owner, and any coowner roles configured via "
        "`/settings coowner`. discord admins without a coowner role cannot "
        "use this."
    )
    return emb


class BackupView(ui.View):
    def __init__(self, invoker: nextcord.Member):
        super().__init__(timeout=900)
        self.invoker = invoker
        self.busy = False

    async def interaction_check(self, i: Interaction) -> bool:
        if i.user.id != self.invoker.id:
            try:
                await i.response.send_message(
                    "this is someone else's wizard", ephemeral=True
                )
            except Exception:
                pass
            return False
        return True

    async def _busy_guard(self, i: Interaction) -> bool:
        if self.busy:
            try:
                await i.response.send_message(
                    "a job is already running — wait for it to finish",
                    ephemeral=True,
                )
            except Exception:
                pass
            return True
        return False

    @ui.button(label="Ping All Hitters", style=nextcord.ButtonStyle.primary, row=0)
    async def ping_all(self, b: ui.Button, i: Interaction):
        if await self._busy_guard(i):
            return
        await self._do_ping(i)

    @ui.button(label="Export File", style=nextcord.ButtonStyle.secondary, row=0)
    async def export(self, b: ui.Button, i: Interaction):
        if await self._busy_guard(i):
            return
        await self._do_export(i)

    @ui.button(label="Mass DM", style=nextcord.ButtonStyle.primary, row=0)
    async def mass_dm(self, b: ui.Button, i: Interaction):
        if await self._busy_guard(i):
            return
        await i.response.send_modal(MassDMModal(self))

    @ui.button(label="Role All", style=nextcord.ButtonStyle.primary, row=0)
    async def role_all(self, b: ui.Button, i: Interaction):
        if await self._busy_guard(i):
            return
        await i.response.edit_message(
            embed=_overview_embed(i.guild),
            view=RolePickerView(self),
        )

    @ui.button(label="Sync from Role", style=nextcord.ButtonStyle.secondary, row=1)
    async def sync_role(self, b: ui.Button, i: Interaction):
        if await self._busy_guard(i):
            return
        await self._do_sync_from_role(i)

    @ui.button(label="Import File", style=nextcord.ButtonStyle.secondary, row=1)
    async def import_file(self, b: ui.Button, i: Interaction):
        if await self._busy_guard(i):
            return
        await self._start_import_session(i)

    @ui.button(label="What is this?", style=nextcord.ButtonStyle.secondary, row=2)
    async def explain(self, b: ui.Button, i: Interaction):
        await i.response.edit_message(
            embed=_explain_embed(i.guild),
            view=BackToWizardView(self),
        )

    @ui.button(label="Close", style=nextcord.ButtonStyle.danger, row=2)
    async def close_btn(self, b: ui.Button, i: Interaction):
        try:
            await i.response.edit_message(content="closed", embed=None, view=None)
        except Exception:
            pass
        self.stop()

    # ── jobs ──────────────────────────────────────────────────────────────

    async def _do_ping(self, i: Interaction):
        roster = get_all_hitters(i.guild.id)
        if not roster:
            await i.response.send_message("the hitter list is empty", ephemeral=True)
            return
        await i.response.defer(ephemeral=True)

        ids = [r["user_id"] for r in roster if r.get("user_id")]
        chunks: list[str] = []
        cur = ""
        for uid in ids:
            mention = f"<@{uid}> "
            if len(cur) + len(mention) > 1900:
                chunks.append(cur.rstrip())
                cur = mention
            else:
                cur += mention
        if cur:
            chunks.append(cur.rstrip())

        await _deliver(
            i.user, i,
            content=f"**hitter list ping — {len(ids)} member(s) across {len(chunks)} message(s)**",
        )
        for chunk in chunks:
            await _deliver(i.user, i, content=chunk)
            await asyncio.sleep(0.6)
        await i.followup.send(
            content=f"DM'd {len(chunks)} message(s) mentioning {len(ids)} hitter(s)",
            ephemeral=True,
        )

    async def _do_export(self, i: Interaction):
        roster = get_all_hitters(i.guild.id)
        if not roster:
            await i.response.send_message("the hitter list is empty", ephemeral=True)
            return
        await i.response.defer(ephemeral=True)

        lines: list[str] = []
        lines.append(f"# hitter list — {i.guild.name} ({i.guild.id})")
        lines.append(f"# exported {datetime.utcnow().isoformat()}Z")
        lines.append(f"# {len(roster)} entries")
        lines.append("# fields: user_id\\tusername\\tadded_at\\tleft_at")
        lines.append("")
        for r in roster:
            uid = r.get("user_id", "")
            uname = r.get("username") or "(unknown)"
            added = ""
            if r.get("added_at"):
                try:
                    added = datetime.utcfromtimestamp(r["added_at"]).strftime("%Y-%m-%d")
                except Exception:
                    pass
            left = ""
            if r.get("left_at"):
                try:
                    left = datetime.utcfromtimestamp(r["left_at"]).strftime("%Y-%m-%d")
                except Exception:
                    pass
            lines.append(f"{uid}\t{uname}\t{added}\t{left}")
        body = "\n".join(lines)
        f = nextcord.File(
            io.BytesIO(body.encode("utf-8")),
            filename=f"hitter-list-{i.guild.id}.txt",
        )
        await _deliver(
            i.user, i,
            content=f"hitter list export · {len(roster)} entries",
            file=f,
        )

    async def _do_mass_dm(self, i: Interaction, kind: str, body_template: str):
        self.busy = True
        try:
            roster = get_all_hitters(i.guild.id)
            total = len(roster)
            if total == 0:
                await i.followup.send("the hitter list is empty", ephemeral=True)
                return

            progress = await i.followup.send(
                content=f"mass DM starting · 0/{total}",
                ephemeral=True, wait=True,
            )

            sent = 0
            failed: list[int] = []
            last_progress_at = 0.0
            for idx, hitter in enumerate(roster):
                uid = hitter.get("user_id")
                if not uid:
                    continue
                member = i.guild.get_member(int(uid)) if i.guild else None
                target = member
                if target is None:
                    try:
                        target = await i.client.fetch_user(int(uid))
                    except Exception:
                        failed.append(int(uid))
                        continue

                mention = f"<@{uid}>"
                text = body_template.replace("{user}", mention)
                try:
                    if kind == "embed":
                        emb = nextcord.Embed(description=text, color=ACCENT)
                        emb.set_footer(text=f"sent from {i.guild.name}")
                        await target.send(embed=emb)
                    else:
                        await target.send(content=text)
                    sent += 1
                except (nextcord.Forbidden, nextcord.HTTPException, Exception):
                    failed.append(int(uid))

                await asyncio.sleep(0.25)

                now = asyncio.get_event_loop().time()
                if (idx + 1) % 25 == 0 or now - last_progress_at > 30:
                    last_progress_at = now
                    try:
                        await progress.edit(
                            content=(
                                f"mass DM in progress · {idx+1}/{total} · "
                                f"sent {sent} · failed {len(failed)}"
                            )
                        )
                    except Exception:
                        pass

            tail = f"sent {sent}/{total} · failed {len(failed)}"
            try:
                await progress.edit(content=f"mass DM complete · {tail}")
            except Exception:
                pass

            if failed:
                if len(failed) <= 10:
                    listed = "\n".join(f"<@{u}> · `{u}`" for u in failed)
                    emb = nextcord.Embed(
                        title="Mass DM — failed deliveries",
                        description=listed,
                        color=ACCENT,
                    )
                    emb.set_footer(text=f"{len(failed)} failed of {total}")
                    await _deliver(i.user, i, embed=emb)
                else:
                    body = "\n".join(str(u) for u in failed)
                    f = nextcord.File(
                        io.BytesIO(body.encode("utf-8")),
                        filename=f"dm-failures-{i.guild.id}.txt",
                    )
                    await _deliver(
                        i.user, i,
                        content=f"mass DM done · {len(failed)} failed (file)",
                        file=f,
                    )
        finally:
            self.busy = False

    async def _do_role_all(self, i: Interaction, role: nextcord.Role):
        self.busy = True
        try:
            roster = get_all_hitters(i.guild.id)
            total = len(roster)
            if total == 0:
                await i.followup.send("the hitter list is empty", ephemeral=True)
                return

            progress = await i.followup.send(
                content=f"role grant starting · 0/{total}",
                ephemeral=True, wait=True,
            )

            granted = already = 0
            failed: list[int] = []
            last_progress_at = 0.0
            for idx, hitter in enumerate(roster):
                uid = hitter.get("user_id")
                if not uid:
                    continue
                member = i.guild.get_member(int(uid))
                if member is None:
                    failed.append(int(uid))
                    continue
                if any(r.id == role.id for r in member.roles):
                    already += 1
                    continue
                try:
                    await member.add_roles(role, reason=f"/backup role-all by {i.user}")
                    granted += 1
                except Exception:
                    failed.append(int(uid))
                await asyncio.sleep(0.1)

                now = asyncio.get_event_loop().time()
                if (idx + 1) % 50 == 0 or now - last_progress_at > 30:
                    last_progress_at = now
                    try:
                        await progress.edit(
                            content=(
                                f"role grant in progress · {idx+1}/{total} · "
                                f"granted {granted} · already had {already} · failed {len(failed)}"
                            )
                        )
                    except Exception:
                        pass

            tail = f"granted {granted} · already {already} · failed {len(failed)}"
            try:
                await progress.edit(content=f"role grant complete · {tail}")
            except Exception:
                pass

            if failed:
                if len(failed) <= 10:
                    listed = "\n".join(f"<@{u}> · `{u}`" for u in failed)
                    emb = nextcord.Embed(
                        title="Role grant — failed",
                        description=listed,
                        color=ACCENT,
                    )
                    emb.set_footer(text=f"{len(failed)} failed of {total}")
                    await _deliver(i.user, i, embed=emb)
                else:
                    body = "\n".join(str(u) for u in failed)
                    f = nextcord.File(
                        io.BytesIO(body.encode("utf-8")),
                        filename=f"role-failures-{i.guild.id}.txt",
                    )
                    await _deliver(
                        i.user, i,
                        content=f"role grant done · {len(failed)} failed (file)",
                        file=f,
                    )
        finally:
            self.busy = False

    # ── sync from role ────────────────────────────────────────────────────

    async def _do_sync_from_role(self, i: Interaction):
        tracked = get_tracked_role(i.guild.id)
        if not tracked:
            await i.response.send_message(
                embed=err("no tracked role configured — run `/settings role` first"),
                ephemeral=True,
            )
            return
        role = i.guild.get_role(tracked)
        if not role:
            await i.response.send_message(
                embed=err("the tracked role no longer exists in this server"),
                ephemeral=True,
            )
            return

        await i.response.defer(ephemeral=True)
        added = refreshed = 0
        for m in role.members:
            try:
                if add_hitter(i.guild.id, m.id, username=str(m)):
                    added += 1
                else:
                    refreshed += 1
            except Exception:
                pass

        emb = nextcord.Embed(
            title="Sync from Role — done",
            color=ACCENT,
        )
        emb.description = (
            f"{line('role', role.mention)}\n"
            f"{line('current holders', f'`{len(role.members)}`')}\n"
            f"{line('added to list', f'`{added}`')}\n"
            f"{line('already on list (refreshed)', f'`{refreshed}`')}"
        )
        await _deliver(i.user, i, embed=emb)
        try:
            await i.edit_original_message(
                embed=_overview_embed(i.guild),
                view=self,
            )
        except Exception:
            pass

    # ── import file ───────────────────────────────────────────────────────

    async def _start_import_session(self, i: Interaction):
        key = (i.guild.id, i.channel.id, i.user.id)
        _import_sessions[key] = {"view": self}
        emb = nextcord.Embed(
            title="Import File",
            color=ACCENT,
        )
        emb.description = (
            "send a `.txt` file in this channel to import\n\n"
            "**accepted formats** (one entry per line):\n"
            "`123456789012345678` — just user IDs\n"
            "`123456789012345678\tusername` — IDs + tab + username\n"
            "lines starting with `#` are skipped"
        )
        try:
            await i.response.edit_message(embed=emb, view=ImportPendingView(self))
        except Exception:
            pass


class BackToWizardView(ui.View):
    """Single Back button used by the explainer."""
    def __init__(self, parent: BackupView):
        super().__init__(timeout=300)
        self.parent = parent

    async def interaction_check(self, i):
        return await self.parent.interaction_check(i)

    @ui.button(label="Back", style=nextcord.ButtonStyle.secondary, row=0)
    async def back(self, b: ui.Button, i: Interaction):
        await i.response.edit_message(
            embed=_overview_embed(i.guild), view=self.parent,
        )


class ImportPendingView(ui.View):
    """Shown while waiting for the user's .txt attachment. Cancel button
    ends the session without needing typed text."""

    def __init__(self, parent: BackupView):
        super().__init__(timeout=600)
        self.parent = parent

    async def interaction_check(self, i):
        return await self.parent.interaction_check(i)

    @ui.button(label="Cancel Import", style=nextcord.ButtonStyle.danger, row=0)
    async def cancel(self, b: ui.Button, i: Interaction):
        key = (i.guild.id, i.channel.id, i.user.id)
        _import_sessions.pop(key, None)
        await i.response.edit_message(
            embed=_overview_embed(i.guild), view=self.parent,
        )

    @ui.button(label="Back", style=nextcord.ButtonStyle.secondary, row=0)
    async def back(self, b: ui.Button, i: Interaction):
        key = (i.guild.id, i.channel.id, i.user.id)
        _import_sessions.pop(key, None)
        await i.response.edit_message(
            embed=_overview_embed(i.guild), view=self.parent,
        )


def _parse_import_text(text: str) -> tuple[list[tuple[int, Optional[str]]], int]:
    """(entries, skipped). Tolerates IDs, mentions, tab-separated id+username,
    and # comment lines."""
    entries: list[tuple[int, Optional[str]]] = []
    skipped = 0
    for raw in text.splitlines():
        line_s = raw.strip()
        if not line_s or line_s.startswith("#"):
            continue
        parts = line_s.split("\t") if "\t" in line_s else line_s.split(None, 1)
        first = parts[0].strip().replace("<@!", "").replace("<@", "").rstrip(">")
        if not first.isdigit():
            skipped += 1
            continue
        uid = int(first)
        uname = None
        if len(parts) > 1:
            uname = parts[1].strip() or None
        entries.append((uid, uname))
    return entries, skipped


class MassDMModal(ui.Modal):
    def __init__(self, parent: BackupView):
        super().__init__(title="Mass DM Hitters")
        self.parent = parent
        self.kind = ui.TextInput(
            label="format — plain or embed",
            required=True, max_length=10,
            default_value="plain",
            placeholder="plain | embed",
        )
        self.body = ui.TextInput(
            label="message — supports {user} for mention",
            style=nextcord.TextInputStyle.paragraph,
            required=True, max_length=2000,
            placeholder="hi {user}, just a reminder ...",
        )
        self.add_item(self.kind)
        self.add_item(self.body)

    async def callback(self, i: Interaction):
        kind = self.kind.value.strip().lower()
        if kind not in ("plain", "embed"):
            kind = "plain"
        body = self.body.value
        await i.response.defer(ephemeral=True)
        asyncio.create_task(self.parent._do_mass_dm(i, kind, body))


class RolePickerView(ui.View):
    def __init__(self, parent: BackupView):
        super().__init__(timeout=180)
        self.parent = parent
        rs = ui.RoleSelect(
            placeholder="select role to grant to every hitter...",
            min_values=1, max_values=1, row=0,
        )
        rs.callback = self._on_role
        self.add_item(rs)

    async def interaction_check(self, i: Interaction) -> bool:
        return await self.parent.interaction_check(i)

    @ui.button(label="Back", style=nextcord.ButtonStyle.secondary, row=1)
    async def back(self, b: ui.Button, i: Interaction):
        await i.response.edit_message(
            embed=_overview_embed(i.guild), view=self.parent,
        )

    async def _on_role(self, i: Interaction):
        rid = int(i.data["values"][0])
        role = i.guild.get_role(rid)
        if not role:
            await i.response.send_message("role not found", ephemeral=True)
            return
        if role >= i.guild.me.top_role:
            await i.response.send_message(
                "that role is at or above mine — i can't grant it",
                ephemeral=True,
            )
            return
        if role.managed:
            await i.response.send_message(
                "that role is managed by an integration and can't be assigned",
                ephemeral=True,
            )
            return
        await i.response.edit_message(
            embed=_overview_embed(i.guild), view=self.parent,
        )
        asyncio.create_task(self.parent._do_role_all(i, role))


def backup_commands(bot: commands.Bot):

    @bot.slash_command(
        name="backup",
        description="Member backup wizard (admin / coowner only)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def backup_cmd(interaction: Interaction):
        if not can_run(interaction.user, interaction.guild.id):
            await interaction.response.send_message(
                embed=err(refuse_reason(interaction.guild.id)),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=_overview_embed(interaction.guild),
            view=BackupView(interaction.user),
            ephemeral=True,
        )

    # ── Import-file listener — picks up the next attachment from a user
    # with an active import session in the same channel.
    @bot.listen("on_message")
    async def _import_listener(message: nextcord.Message):
        if message.author.bot or not message.guild:
            return
        key = (message.guild.id, message.channel.id, message.author.id)
        session = _import_sessions.get(key)
        if not session:
            return
        if not message.attachments:
            return  # waits for an attachment; Cancel button ends the session

        att = message.attachments[0]
        if att.size and att.size > 5 * 1024 * 1024:
            try:
                m = await message.channel.send("file too big — 5 MB limit")
                await asyncio.sleep(5)
                await m.delete()
            except Exception:
                pass
            return

        try:
            raw = await att.read()
            text = raw.decode("utf-8", errors="replace")
        except Exception as e:
            try:
                m = await message.channel.send(f"couldn't read attachment: {e}")
                await asyncio.sleep(5)
                await m.delete()
            except Exception:
                pass
            return

        entries, skipped = _parse_import_text(text)
        del _import_sessions[key]

        added = refreshed = 0
        for uid, uname in entries:
            try:
                if add_hitter(message.guild.id, uid, username=uname):
                    added += 1
                else:
                    refreshed += 1
            except Exception:
                pass

        try:
            await message.delete()
        except Exception:
            pass

        emb = nextcord.Embed(
            title="Import File — done",
            color=ACCENT,
        )
        emb.description = (
            f"{line('total parsed', f'`{len(entries)}`')}\n"
            f"{line('added to list', f'`{added}`')}\n"
            f"{line('already on list (refreshed)', f'`{refreshed}`')}\n"
            f"{line('skipped (unparseable)', f'`{skipped}`')}"
        )
        try:
            await message.author.send(embed=emb)
        except Exception:
            try:
                m = await message.channel.send(
                    f"import done · added {added} · refreshed {refreshed} · skipped {skipped}"
                )
                await asyncio.sleep(8)
                await m.delete()
            except Exception:
                pass
