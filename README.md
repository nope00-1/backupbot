# backup_bot

A small Discord bot that keeps a backup list of every user who has ever
held a chosen role on your server — so you can recover if that role is
ever deleted (by accident or by a bad actor).

The list fills itself: anyone who acquires the tracked role is added
automatically. From there, `/backup` opens an admin-only wizard that
lets you ping all members on the list, mass-DM them, grant a fresh
role to all of them, export the list to a file, sync from the current
role holders, or import from a `.txt`.

## Features

- **Automatic tracking** — listens for the configured role being added
  to a member and appends them to the saved list. No command required.
- **7-day grace on leave** — when a member leaves, they stay on the
  list for a week. If they come back and still hold the tracked role
  they're kept; otherwise they're dropped. After 7 days without a
  return, they're pruned.
- **`/backup` wizard** — six actions, all output is private (DM by
  default, ephemeral followup if your DMs are closed):
  - **Ping All Hitters** — DMs you a chunked mention list you can paste
    into whatever channel you want to ping
  - **Export File** — DMs you a `.txt` with `user_id, username, dates`
  - **Mass DM** — modal form: pick `plain` or `embed` format, write a
    message body supporting `{user}` for mention. Live progress, failed
    sends reported as a file
  - **Role All** — pick any role (RoleSelect), it's granted to every
    member on the list. Recovers from a deleted tracked role
  - **Sync from Role** — scans current holders of the tracked role and
    adds anyone missing from the list
  - **Import File** — bulk-add from a `.txt` of user IDs
- **`/settings`** — `role @role` sets the tracked role; `coowner` adds
  / removes / lists coowner roles (extra permission tier alongside
  admin).

## Setup

You need Python 3.10+ and a Discord bot application.

```sh
# 1. clone
git clone https://github.com/nope00-1/backupbot.git
cd backupbot

# 2. install deps
pip install -r requirements.txt

# 3. config
cp config.yaml.example config.yaml
# edit config.yaml — paste your bot token, optionally set owner_id

# 4. run
python3 main.py
```

When the bot starts, invite it to your server with these scopes:
`bot`, `applications.commands`. It needs the **Members** privileged
intent (toggle it on at
https://discord.com/developers/applications/<your-app-id>/bot under
"Privileged Gateway Intents").

Required permissions on the bot's role:
- View Channels
- Send Messages
- Manage Roles _(for `Role All`)_
- The bot's role must sit above any role you want it to grant

Then in your server, as an admin:

```
/settings role @your-tracked-role
```

That's it. As anyone holding `@your-tracked-role` joins / gets the
role, the bot remembers them. Run `/backup` whenever you need to
recover or message the list.

## Permissions

Only three principals can use `/backup` and `/settings`:

- The **bot owner** (`owner_id` in `config.yaml`)
- The **server owner**
- Anyone holding a **coowner role** configured via `/settings coowner add`

Discord's `Administrator` permission **does not** grant access on its
own — admins without a coowner role get refused with a helpful
message pointing them at `/settings coowner add`.

The slash commands themselves are visible only to admins in Discord's
command picker (`default_member_permissions=Administrator`). If you
want non-admin coowners to see the commands in their menu, grant
their role access via **Server Settings → Integrations → backup_bot →
/backup → Add Role** (Discord's command permissions UI).

**Bootstrapping:** on a fresh install nobody is a coowner yet, so the
**server owner** has to run `/settings coowner add @role` first to
unlock the bot for the rest of the team.

## Data storage

One SQLite file at `data/backup_bot.db`. Two doc types per guild:
`settings` (tracked role + coowner roles) and `hitters` (the list).
The cache is process-local, so subsequent reads of the same doc are
free. WAL mode + 256 MB mmap.

`config.yaml` and the `data/` directory are git-ignored.

## License

MIT — see `LICENSE`.
