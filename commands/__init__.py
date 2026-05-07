from commands.backup import backup_commands
from commands.settings import settings_commands


def register_all(bot):
    backup_commands(bot)
    settings_commands(bot)
