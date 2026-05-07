"""
/settings — minimal config surface.

Two subcommands:
  - /settings role @role           which role the bot tracks
  - /settings coowner @role        add/remove a coowner role (extra
                                    permission tier for /backup access)

Admin-only at the slash menu (default_member_permissions). The in-code
permission check inside each callback adds bot owner + server owner +
configured coowners.
"""

from __future__ import annotations

import nextcord
from nextcord import Interaction, SlashOption, ui
from nextcord.ext import commands

from database.settings import (
    set_tracked_role, get_tracked_role,
    add_coowner_role, remove_coowner_role, get_coowner_roles,
)
from commands._helpers import can_run, refuse_reason, ok, err, line, ACCENT


def _refuse(interaction: Interaction):
    """Refuse-with-reason — surfaces the bootstrap hint when no coowner
    role is set yet, so an admin who tries /settings sees that the
    server owner has to run /settings coowner add first."""
    return interaction.response.send_message(
        embed=err(refuse_reason(interaction.guild.id)), ephemeral=True,
    )


def settings_commands(bot: commands.Bot):

    @bot.slash_command(
        name="settings",
        description="Configure the backup bot",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def settings_root(interaction: Interaction):
        # Parent for subcommands; never invoked directly.
        pass

    # ── /settings role ──────────────────────────────────────────────────────

    @settings_root.subcommand(
        name="role",
        description="Set which role the bot tracks for backup",
    )
    async def settings_role(
        interaction: Interaction,
        role: nextcord.Role = SlashOption(
            name="role",
            description="Role to track (members holding this role are saved)",
            required=True,
        ),
    ):
        if not can_run(interaction.user, interaction.guild.id):
            await _refuse(interaction)
            return
        set_tracked_role(interaction.guild.id, role.id)
        emb = nextcord.Embed(color=ACCENT, title="Tracked role updated")
        emb.description = (
            f"{line('role', role.mention)}\n"
            f"the bot will now save users who hold this role.\n"
            f"run `/backup → Sync from Role` to import the current holders."
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)

    # ── /settings coowner ───────────────────────────────────────────────────

    @settings_root.subcommand(
        name="coowner",
        description="Add or remove a coowner role (extra permission tier)",
    )
    async def settings_coowner(
        interaction: Interaction,
        action: str = SlashOption(
            name="action",
            description="add or remove",
            required=True,
            choices={"add": "add", "remove": "remove", "list": "list"},
        ),
        role: nextcord.Role = SlashOption(
            name="role",
            description="Role to add/remove as coowner (omit for list)",
            required=False,
            default=None,
        ),
    ):
        if not can_run(interaction.user, interaction.guild.id):
            await _refuse(interaction)
            return

        if action == "list":
            ids = get_coowner_roles(interaction.guild.id)
            if not ids:
                await interaction.response.send_message(
                    embed=ok("no coowner roles configured"), ephemeral=True,
                )
                return
            mentions = " ".join(f"<@&{rid}>" for rid in ids)
            emb = nextcord.Embed(color=ACCENT, title="Coowner roles")
            emb.description = mentions
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return

        if role is None:
            await interaction.response.send_message(
                embed=err("pick a role"), ephemeral=True,
            )
            return

        if action == "add":
            added = add_coowner_role(interaction.guild.id, role.id)
            msg = f"added {role.mention} as coowner" if added else f"{role.mention} is already a coowner"
            await interaction.response.send_message(
                embed=ok(msg) if added else err(msg), ephemeral=True,
            )
        else:  # remove
            removed = remove_coowner_role(interaction.guild.id, role.id)
            msg = f"removed {role.mention} from coowners" if removed else f"{role.mention} wasn't a coowner"
            await interaction.response.send_message(
                embed=ok(msg) if removed else err(msg), ephemeral=True,
            )
