from __future__ import annotations

from collections.abc import Iterable
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.constants import (
    DEFAULT_DAILY_REMINDER_HOUR,
    DEFAULT_INTRADAY_IDLE_HOURS,
    DEFAULT_INTRADAY_INTERVAL_MINUTES,
    DEFAULT_INTRADAY_MIN_DUE,
    DEFAULT_QUIET_HOURS_END,
    DEFAULT_QUIET_HOURS_START,
    SUPPORTED_LANGUAGES,
)
from bot.errors import RepositoryError
from bot.handlers.common import pairs_repo, users_repo
from bot.runtime_keys import REMINDER_QUIZ_REPO_KEY
from bot.utils.timezone import is_timezone_value_valid

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

_SETTINGS_REQUIRED_KEYS: tuple[str, ...] = (
    "timezone",
    "daily_reminder_hour",
    "intraday_min_due",
    "intraday_idle_hours",
    "intraday_interval_minutes",
    "quiet_hours_start",
    "quiet_hours_end",
)

_SETTINGS_KEY_ALIASES: dict[str, str] = {
    "timezone": "timezone",
    "таймзона": "timezone",
    "daily_reminder_hour": "daily_reminder_hour",
    "утренний_час": "daily_reminder_hour",
    "утреннее_напоминание_час": "daily_reminder_hour",
    "intraday_min_due": "intraday_min_due",
    "минимум_due": "intraday_min_due",
    "minimum_due": "intraday_min_due",
    "intraday_idle_hours": "intraday_idle_hours",
    "пауза_после_тренировки_часы": "intraday_idle_hours",
    "intraday_interval_minutes": "intraday_interval_minutes",
    "интервал_напоминаний_минуты": "intraday_interval_minutes",
    "quiet_hours_start": "quiet_hours_start",
    "тихие_часы_с": "quiet_hours_start",
    "quiet_hours_end": "quiet_hours_end",
    "тихие_часы_до": "quiet_hours_end",
}

_SIMPLE_TZ_OFFSET_RE = re.compile(r"^[+-]?\d{1,2}$")


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
        "settings_state",
        "delete_state",
        "edit_state",
        "fullword_state",
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
            "/settings - открыть и изменить настройки напоминаний\n"
            "/reminders - напоминания\n"
            "/stats - статистика\n"
            "/full - полная карточка последнего слова на 4 языках\n"
            "/fullword - полная карточка из памяти по введенному слову\n"
            "/cancel - отменить текущую операцию\n"
            "/help - показать команды"
        )
    )


def _settings_template(settings: dict[str, object] | None = None) -> str:
    timezone = _timezone_for_template(str((settings or {}).get("timezone") or "UTC+3"))
    daily_reminder_hour = int(
        (settings or {}).get("daily_reminder_hour") or DEFAULT_DAILY_REMINDER_HOUR
    )
    intraday_min_due = int(
        (settings or {}).get("intraday_min_due") or DEFAULT_INTRADAY_MIN_DUE
    )
    intraday_idle_hours = int(
        (settings or {}).get("intraday_idle_hours") or DEFAULT_INTRADAY_IDLE_HOURS
    )
    intraday_interval_minutes = int(
        (settings or {}).get("intraday_interval_minutes")
        or DEFAULT_INTRADAY_INTERVAL_MINUTES
    )
    quiet_hours_start = int(
        (settings or {}).get("quiet_hours_start") or DEFAULT_QUIET_HOURS_START
    )
    quiet_hours_end = int(
        (settings or {}).get("quiet_hours_end") or DEFAULT_QUIET_HOURS_END
    )
    return "\n".join(
        [
            f"timezone: {timezone}",
            f"daily_reminder_hour: {daily_reminder_hour}",
            f"intraday_min_due: {intraday_min_due}",
            f"intraday_idle_hours: {intraday_idle_hours}",
            f"intraday_interval_minutes: {intraday_interval_minutes}",
            f"quiet_hours_start: {quiet_hours_start}",
            f"quiet_hours_end: {quiet_hours_end}",
        ]
    )


def _timezone_for_template(value: str) -> str:
    normalized = value.strip().upper()
    if normalized.startswith("UTC") and len(normalized) >= 5 and normalized[3] in "+-":
        return normalized[3:]
    return value


def _normalize_timezone_input(value: str) -> str:
    raw = value.strip().upper().replace("UTC", "").strip()
    if _SIMPLE_TZ_OFFSET_RE.match(raw):
        hours = int(raw)
        if not (-14 <= hours <= 14):
            raise ValueError("timezone hour offset must be between -14 and +14")
        sign = "+" if hours >= 0 else "-"
        return f"UTC{sign}{abs(hours)}"
    # keep original value for named zones like Europe/Berlin
    return value.strip()


def _canonical_settings_key(raw_key: str) -> str | None:
    normalized = raw_key.strip().lower().replace(" ", "_")
    return _SETTINGS_KEY_ALIASES.get(normalized)


def _parse_settings_payload(raw: str) -> tuple[dict[str, object] | None, str | None]:
    provided: dict[str, str] = {}
    unknown_keys: list[str] = []
    malformed_lines: list[str] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            malformed_lines.append(stripped)
            continue
        key_part, value_part = stripped.split(":", 1)
        canonical = _canonical_settings_key(key_part)
        if canonical is None:
            unknown_keys.append(key_part.strip())
            continue
        provided[canonical] = value_part.strip()

    if malformed_lines:
        return None, (
            "Некорректные строки (нужен формат key: value): "
            + ", ".join(malformed_lines[:3])
        )
    if unknown_keys:
        return None, "Неизвестные ключи: " + ", ".join(unknown_keys[:5])

    missing = [key for key in _SETTINGS_REQUIRED_KEYS if key not in provided]
    if missing:
        return None, "Не хватает ключей: " + ", ".join(missing)

    try:
        timezone = _normalize_timezone_input(provided["timezone"])
    except ValueError:
        return None, "timezone смещение должно быть в диапазоне от -14 до +14."
    if not timezone or not is_timezone_value_valid(timezone):
        return None, "Некорректная timezone. Пример: +4, -2, UTC+4 или Europe/Berlin."

    int_fields: dict[str, int] = {}
    for key in _SETTINGS_REQUIRED_KEYS:
        if key == "timezone":
            continue
        value = provided[key]
        try:
            int_fields[key] = int(value)
        except ValueError:
            return None, f"Поле {key} должно быть целым числом."

    if not (0 <= int_fields["daily_reminder_hour"] <= 23):
        return None, "daily_reminder_hour должен быть от 0 до 23."
    if int_fields["intraday_min_due"] < 1:
        return None, "intraday_min_due должен быть >= 1."
    if not (0 <= int_fields["intraday_idle_hours"] <= 72):
        return None, "intraday_idle_hours должен быть от 0 до 72."
    if not (15 <= int_fields["intraday_interval_minutes"] <= 1440):
        return None, "intraday_interval_minutes должен быть от 15 до 1440."
    if not (0 <= int_fields["quiet_hours_start"] <= 23):
        return None, "quiet_hours_start должен быть от 0 до 23."
    if not (0 <= int_fields["quiet_hours_end"] <= 23):
        return None, "quiet_hours_end должен быть от 0 до 23."

    parsed: dict[str, object] = {
        "timezone": timezone,
        "daily_reminder_hour": int_fields["daily_reminder_hour"],
        "intraday_min_due": int_fields["intraday_min_due"],
        "intraday_idle_hours": int_fields["intraday_idle_hours"],
        "intraday_interval_minutes": int_fields["intraday_interval_minutes"],
        "quiet_hours_start": int_fields["quiet_hours_start"],
        "quiet_hours_end": int_fields["quiet_hours_end"],
    }
    return parsed, None


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    users_repository = users_repo(context)
    await users_repository.get_or_create(user.id, user.username, user.first_name)
    settings = await users_repository.get_reminder_settings(user.id)
    template = _settings_template(settings)
    context.user_data["settings_state"] = {"step": "await_payload"}
    await message.reply_text(
        (
            "Скопируйте следующее сообщение, поменяйте значения после двоеточий и отправьте его в чат.\n"
            "Для timezone используйте простой формат +4 / -2."
        )
    )
    await message.reply_text(template)


async def settings_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return
    state = context.user_data.get("settings_state")
    if not isinstance(state, dict) or state.get("step") != "await_payload":
        return

    parsed, error = _parse_settings_payload(message.text)
    if error:
        current = await users_repo(context).get_reminder_settings(user.id)
        await message.reply_text(
            "Не удалось применить настройки: "
            + error
            + "\n\nИсправьте и отправьте снова. Шаблон:\n"
            + _settings_template(current)
        )
        raise ApplicationHandlerStop

    await users_repo(context).update_reminder_settings(
        user_id=user.id,
        timezone=str(parsed["timezone"]),
        daily_reminder_hour=int(parsed["daily_reminder_hour"]),
        intraday_min_due=int(parsed["intraday_min_due"]),
        intraday_idle_hours=int(parsed["intraday_idle_hours"]),
        intraday_interval_minutes=int(parsed["intraday_interval_minutes"]),
        quiet_hours_start=int(parsed["quiet_hours_start"]),
        quiet_hours_end=int(parsed["quiet_hours_end"]),
    )
    context.user_data.pop("settings_state", None)
    await message.reply_text("Настройки сохранены.\n\n" + _settings_template(parsed))
    raise ApplicationHandlerStop


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None:
        return
    if user is not None:
        reminder_quiz_repo = context.application.bot_data.get(REMINDER_QUIZ_REPO_KEY)
        if reminder_quiz_repo is not None and hasattr(reminder_quiz_repo, "clear"):
            await reminder_quiz_repo.clear(user.id)
    for key in (
        "add_state",
        "train_state",
        "settings_state",
        "delete_state",
        "edit_state",
        "fullword_state",
        "sets_state",
        "import_state",
    ):
        context.user_data.pop(key, None)
    await message.reply_text("Текущая операция отменена.")
