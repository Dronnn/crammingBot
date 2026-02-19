from __future__ import annotations

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.constants import ACTIVE_PAIR_REQUIRED_COMMANDS_EXCEPTIONS
from bot.runtime_keys import USERS_REPO_KEY


async def active_pair_command_guard(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return

    command = message.text.split(maxsplit=1)[0].split("@")[0]
    if command in ACTIVE_PAIR_REQUIRED_COMMANDS_EXCEPTIONS:
        return

    users_repo = context.application.bot_data.get(USERS_REPO_KEY)
    if users_repo is None:
        return

    active_pair_id = await users_repo.get_active_pair_id(user.id)
    if active_pair_id is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        raise ApplicationHandlerStop

