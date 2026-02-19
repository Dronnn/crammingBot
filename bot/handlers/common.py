from __future__ import annotations

from telegram.ext import ContextTypes

from bot.db.repositories.language_pairs import LanguagePairsRepository
from bot.db.repositories.users import UsersRepository
from bot.runtime_keys import LANGUAGE_PAIRS_REPO_KEY, USERS_REPO_KEY


def users_repo(context: ContextTypes.DEFAULT_TYPE) -> UsersRepository:
    return context.application.bot_data[USERS_REPO_KEY]


def pairs_repo(context: ContextTypes.DEFAULT_TYPE) -> LanguagePairsRepository:
    return context.application.bot_data[LANGUAGE_PAIRS_REPO_KEY]


async def get_active_pair(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    user_repository = users_repo(context)
    pair_repository = pairs_repo(context)
    active_pair_id = await user_repository.get_active_pair_id(user_id)
    if active_pair_id is None:
        return None
    return await pair_repository.get_by_id(active_pair_id)

