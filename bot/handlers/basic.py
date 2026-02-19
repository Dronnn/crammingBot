from __future__ import annotations

from collections.abc import Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.constants import SUPPORTED_LANGUAGES
from bot.errors import RepositoryError
from bot.handlers.common import pairs_repo, users_repo

START_SOURCE_PREFIX = "start:src:"
START_TARGET_PREFIX = "start:tgt:"
PAIR_SWITCH_PREFIX = "pair:switch:"
PAIR_CREATE_PREFIX = "pair:create"
PAIR_SOURCE_PREFIX = "pair:src:"
PAIR_TARGET_PREFIX = "pair:tgt:"

START_SOURCE_PATTERN = r"^start:src:[A-Z]{2}$"
START_TARGET_PATTERN = r"^start:tgt:[A-Z]{2}:[A-Z]{2}$"
PAIR_SWITCH_PATTERN = r"^pair:switch:\d+$"
PAIR_CREATE_PATTERN = r"^pair:create$"
PAIR_SOURCE_PATTERN = r"^pair:src:[A-Z]{2}$"
PAIR_TARGET_PATTERN = r"^pair:tgt:[A-Z]{2}:[A-Z]{2}$"


def _chunked_buttons(
    buttons: Iterable[InlineKeyboardButton], columns: int = 2
) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for button in buttons:
        current_row.append(button)
        if len(current_row) == columns:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return rows


def _source_language_markup(prefix: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(label, callback_data=f"{prefix}{code}")
        for code, label in SUPPORTED_LANGUAGES.items()
    ]
    return InlineKeyboardMarkup(_chunked_buttons(buttons, columns=2))


def _target_language_markup(prefix: str, source_lang: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            label, callback_data=f"{prefix}{source_lang}:{target_lang}"
        )
        for target_lang, label in SUPPORTED_LANGUAGES.items()
        if target_lang != source_lang
    ]
    return InlineKeyboardMarkup(_chunked_buttons(buttons, columns=2))


def _parse_code(data: str, prefix: str) -> str | None:
    if not data.startswith(prefix):
        return None
    code = data.removeprefix(prefix)
    if code not in SUPPORTED_LANGUAGES:
        return None
    return code


def _reset_runtime_states(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["active_set_id"] = None
    for key in (
        "add_state",
        "train_state",
        "delete_state",
        "edit_state",
        "sets_state",
        "import_state",
        "last_word_ref",
    ):
        context.user_data.pop(key, None)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    users_repository = users_repo(context)
    pairs_repository = pairs_repo(context)
    user_record = await users_repository.get_or_create(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    if user_record.active_pair_id is not None:
        pair = await pairs_repository.get_by_id(user_record.active_pair_id)
        if pair is not None:
            await message.reply_text(
                (
                    "Текущая активная пара: "
                    f"{pair.source_lang} -> {pair.target_lang}\n"
                    "Сменить пару: /pair\n"
                    "Продолжить тренировку: /train"
                )
            )
            return
        await users_repository.set_active_pair_id(user_record.id, None)
        _reset_runtime_states(context)

    _reset_runtime_states(context)
    await message.reply_text(
        (
            "Добро пожаловать! Для начала нужно выбрать языковую пару.\n"
            "Шаг 1/2: выберите исходный язык."
        ),
        reply_markup=_source_language_markup(START_SOURCE_PREFIX),
    )


async def start_source_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    source_lang = _parse_code(query.data, START_SOURCE_PREFIX)
    if source_lang is None:
        await query.answer("Некорректные данные.", show_alert=True)
        return

    await query.answer()
    await query.edit_message_text(
        "Шаг 2/2: выберите целевой язык.",
        reply_markup=_target_language_markup(START_TARGET_PREFIX, source_lang),
    )


async def start_target_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    payload = query.data.removeprefix(START_TARGET_PREFIX)
    source_lang, _, target_lang = payload.partition(":")
    if source_lang not in SUPPORTED_LANGUAGES or target_lang not in SUPPORTED_LANGUAGES:
        await query.answer("Некорректные данные.", show_alert=True)
        return
    if source_lang == target_lang:
        await query.answer("Языки должны отличаться.", show_alert=True)
        return

    pairs_repository = pairs_repo(context)
    users_repository = users_repo(context)
    pair = await pairs_repository.create_or_get(user.id, source_lang, target_lang)
    await users_repository.set_active_pair_id(user.id, pair.id)
    _reset_runtime_states(context)

    await query.answer()
    await query.edit_message_text(
        (
            f"Языковая пара: {source_lang} -> {target_lang}.\n"
            "Теперь можно добавлять слова командой /add."
        )
    )


async def pair_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    users_repository = users_repo(context)
    pairs_repository = pairs_repo(context)
    user_record = await users_repository.get_or_create(user.id, user.username, user.first_name)
    pairs = await pairs_repository.list_for_user(user.id)

    buttons: list[list[InlineKeyboardButton]] = []
    for pair in pairs:
        marker = "✅ " if pair.id == user_record.active_pair_id else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{marker}{pair.source_lang} -> {pair.target_lang}",
                    callback_data=f"{PAIR_SWITCH_PREFIX}{pair.id}",
                )
            ]
        )
    buttons.append(
        [InlineKeyboardButton("Создать новую пару", callback_data=PAIR_CREATE_PREFIX)]
    )

    await message.reply_text(
        "Выберите существующую пару или создайте новую:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def pair_switch_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return

    raw_id = query.data.removeprefix(PAIR_SWITCH_PREFIX)
    if not raw_id.isdigit():
        await query.answer("Некорректные данные.", show_alert=True)
        return
    pair_id = int(raw_id)

    users_repository = users_repo(context)
    pairs_repository = pairs_repo(context)
    try:
        await pairs_repository.ensure_belongs_to_user(pair_id, user.id)
    except RepositoryError:
        await query.answer("Пара не найдена.", show_alert=True)
        return
    await users_repository.set_active_pair_id(user.id, pair_id)
    _reset_runtime_states(context)
    pair = await pairs_repository.get_by_id(pair_id)

    await query.answer()
    if pair is None:
        await query.edit_message_text("Пара не найдена.")
        return
    await query.edit_message_text(
        f"Активная пара изменена: {pair.source_lang} -> {pair.target_lang}"
    )


async def pair_create_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await query.edit_message_text(
        "Выберите исходный язык:",
        reply_markup=_source_language_markup(PAIR_SOURCE_PREFIX),
    )


async def pair_source_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    source_lang = _parse_code(query.data, PAIR_SOURCE_PREFIX)
    if source_lang is None:
        await query.answer("Некорректные данные.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        "Выберите целевой язык:",
        reply_markup=_target_language_markup(PAIR_TARGET_PREFIX, source_lang),
    )


async def pair_target_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or query.data is None or user is None:
        return

    payload = query.data.removeprefix(PAIR_TARGET_PREFIX)
    source_lang, _, target_lang = payload.partition(":")
    if source_lang not in SUPPORTED_LANGUAGES or target_lang not in SUPPORTED_LANGUAGES:
        await query.answer("Некорректные данные.", show_alert=True)
        return
    if source_lang == target_lang:
        await query.answer("Языки должны отличаться.", show_alert=True)
        return

    pairs_repository = pairs_repo(context)
    users_repository = users_repo(context)
    pair = await pairs_repository.create_or_get(user.id, source_lang, target_lang)
    await users_repository.set_active_pair_id(user.id, pair.id)
    _reset_runtime_states(context)

    await query.answer()
    await query.edit_message_text(
        f"Активная пара: {source_lang} -> {target_lang}\nМожете продолжать: /add или /train"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(
        (
            "Команды:\n"
            "/start - первый запуск и выбор пары\n"
            "/pair - сменить активную пару\n"
            "/add - добавить слово\n"
            "/train - тренировка\n"
            "/due - количество карточек к повторению\n"
            "/duelist - список карточек к повторению\n"
            "/list - список слов\n"
            "/delete - удалить слово\n"
            "/edit - редактировать карточку\n"
            "/import - импорт CSV\n"
            "/export - экспорт CSV\n"
            "/sets - тематические наборы\n"
            "/reminders - напоминания\n"
            "/stats - статистика\n"
            "/full - полная карточка последнего слова на 4 языках\n"
            "/cancel - отменить текущую операцию\n"
            "/help - показать команды"
        )
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    for key in (
        "add_state",
        "train_state",
        "delete_state",
        "edit_state",
        "sets_state",
        "import_state",
    ):
        context.user_data.pop(key, None)
    await message.reply_text("Текущая операция отменена.")
