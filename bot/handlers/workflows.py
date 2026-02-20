from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import UTC, datetime
import io
import logging
from math import ceil
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.constants import SUPPORTED_LANGUAGES
from bot.db.repositories.cards import CardsRepository
from bot.db.repositories.reminder_quiz_states import ReminderQuizStatesRepository
from bot.db.repositories.reviews import ReviewsRepository
from bot.db.repositories.sets import VocabularySetsRepository
from bot.db.repositories.users import UsersRepository
from bot.db.repositories.words import WordsRepository
from bot.domain.content import ExampleContent, GeneratedWordContent
from bot.domain.models import (
    CardAnswerContext,
    DueCardRecord,
    ExampleRecord,
    LanguagePairRecord,
    WordRecord,
)
from bot.domain.srs import SRSService
from bot.domain.validation import AnswerValidationService
from bot.handlers.common import get_active_pair, pairs_repo
from bot.runtime_keys import (
    CARDS_REPO_KEY,
    CONTENT_SERVICE_KEY,
    LLM_RATE_LIMITER_KEY,
    REMINDER_QUIZ_REPO_KEY,
    REVIEWS_REPO_KEY,
    SETS_REPO_KEY,
    SRS_SERVICE_KEY,
    TTS_SERVICE_KEY,
    USERS_REPO_KEY,
    VALIDATION_SERVICE_KEY,
    WORDS_REPO_KEY,
)
from bot.services.content_generation import ContentGenerationError, OpenAIContentGenerator
from bot.services.llm_rate_limiter import LLMRateLimiter
from bot.services.tts import GTTSService
from bot.utils.formatting import (
    format_declension,
    format_examples,
    format_next_review_delta,
    format_overdue,
)
from bot.utils.telegram_retry import with_telegram_retry

logger = logging.getLogger(__name__)

ADD_SET_SKIP = "add:set:skip"
ADD_SET_NEW = "add:set:new"
ADD_SET_EXISTING_PREFIX = "add:set:existing:"
ADD_SAVE = "add:save"
ADD_CANCEL = "add:cancel"

TRAIN_TTS = "train:tts"
TRAIN_SKIP = "train:skip"

LIST_PAGE_PREFIX = "list:page:"
DUELIST_PAGE_PREFIX = "duelist:page:"

SETS_SELECT_PREFIX = "sets:select:"
SETS_CLEAR = "sets:clear"
SETS_CREATE = "sets:create"

EDIT_TRANSLATION = "edit:field:translation"
EDIT_EXAMPLES = "edit:field:examples"
EDIT_NOTE = "edit:field:note"
EDIT_CANCEL = "edit:cancel"

PAGE_SIZE = 20
FULL_LANGUAGE_ORDER = ("RU", "EN", "DE", "HY")
MAX_IMPORT_FILE_BYTES = 512 * 1024
MAX_IMPORT_ROWS = 200


def _users_repo(context: ContextTypes.DEFAULT_TYPE) -> UsersRepository:
    return context.application.bot_data[USERS_REPO_KEY]


def _words_repo(context: ContextTypes.DEFAULT_TYPE) -> WordsRepository:
    return context.application.bot_data[WORDS_REPO_KEY]


def _cards_repo(context: ContextTypes.DEFAULT_TYPE) -> CardsRepository:
    return context.application.bot_data[CARDS_REPO_KEY]


def _reviews_repo(context: ContextTypes.DEFAULT_TYPE) -> ReviewsRepository:
    return context.application.bot_data[REVIEWS_REPO_KEY]


def _sets_repo(context: ContextTypes.DEFAULT_TYPE) -> VocabularySetsRepository:
    return context.application.bot_data[SETS_REPO_KEY]


def _srs_service(context: ContextTypes.DEFAULT_TYPE) -> SRSService:
    return context.application.bot_data[SRS_SERVICE_KEY]


def _validation_service(context: ContextTypes.DEFAULT_TYPE) -> AnswerValidationService:
    return context.application.bot_data[VALIDATION_SERVICE_KEY]


def _content_service(context: ContextTypes.DEFAULT_TYPE) -> OpenAIContentGenerator:
    return context.application.bot_data[CONTENT_SERVICE_KEY]


def _tts_service(context: ContextTypes.DEFAULT_TYPE) -> GTTSService:
    return context.application.bot_data[TTS_SERVICE_KEY]


def _reminder_quiz_repo(context: ContextTypes.DEFAULT_TYPE) -> ReminderQuizStatesRepository:
    return context.application.bot_data[REMINDER_QUIZ_REPO_KEY]


def _llm_rate_limiter(context: ContextTypes.DEFAULT_TYPE) -> LLMRateLimiter:
    return context.application.bot_data[LLM_RATE_LIMITER_KEY]


def _command_argument(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    value = parts[1].strip()
    return value or None


def _state_clear(context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    if key in context.user_data:
        del context.user_data[key]


async def _safe_query_answer(
    query,
    *,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    try:
        await query.answer(text=text, show_alert=show_alert)
    except BadRequest as exc:
        lowered = str(exc).lower()
        if "query is too old" in lowered or "query id is invalid" in lowered:
            logger.debug("Ignoring stale callback query answer error: %s", exc)
            return
        raise


async def _show_generation_status(message, text: str) -> Any | None:
    try:
        return await message.reply_text(text)
    except Exception:
        return None


async def _update_generation_status(status_message: Any | None, text: str) -> None:
    if status_message is None:
        return
    try:
        await status_message.edit_text(text)
    except Exception:
        return


def _format_retry_after(seconds: int) -> str:
    remaining = max(1, int(seconds))
    minutes, secs = divmod(remaining, 60)
    hours, minutes = divmod(minutes, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if secs and not hours:
        parts.append(f"{secs} сек")
    return " ".join(parts) if parts else "1 сек"


async def _acquire_llm_slot(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    message,
    user_id: int,
) -> bool:
    decision = await _llm_rate_limiter(context).consume(user_id=user_id)
    if decision.allowed:
        return True
    retry_after = _format_retry_after(decision.retry_after_seconds)
    await message.reply_text(
        "Сейчас слишком много генераций. "
        f"Повторите попытку через {retry_after}."
    )
    return False


def _example_translation_for_lang(example: ExampleRecord, language: str) -> str:
    if language == "RU":
        return example.translation_ru
    if language == "EN":
        return example.translation_en
    if language == "DE":
        return example.translation_de
    if language == "HY":
        return example.translation_hy
    return ""


def _synonym_base_text(value: str) -> str:
    text = value.strip()
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    return text


def _format_full_snapshot_text(
    *,
    snapshot: dict[str, Any],
    word: Any,
) -> str:
    lines = ["Полная карточка (RU -> EN -> DE -> HY):", "", "Слово:"]
    word_map = snapshot.get("word", {})
    if isinstance(word_map, dict):
        for code in FULL_LANGUAGE_ORDER:
            lines.append(f"{code}: {word_map.get(code, '-') or '-'}")
    else:
        for code in FULL_LANGUAGE_ORDER:
            lines.append(f"{code}: -")
    if getattr(word, "part_of_speech", None):
        lines.append(f"Часть речи: {word.part_of_speech}")
    if getattr(word, "gender", None):
        lines.append(f"Род: {word.gender}")
    if getattr(word, "declension", None):
        lines.append("Склонение: " + format_declension(word.declension))

    lines.extend(["", "Синонимы:"])
    synonyms_raw = snapshot.get("synonyms", [])
    synonyms = synonyms_raw if isinstance(synonyms_raw, list) else []
    if not synonyms:
        lines.append("-")
    else:
        for index, item in enumerate(synonyms, start=1):
            if not isinstance(item, dict):
                continue
            lines.append(f"{index}. {item.get('target', '-') or '-'}")
            for code in FULL_LANGUAGE_ORDER:
                lines.append(f"   {code}: {item.get(code, '-') or '-'}")

    lines.extend(["", "Примеры:"])
    examples_raw = snapshot.get("examples", [])
    examples = examples_raw if isinstance(examples_raw, list) else []
    if not examples:
        lines.append("-")
    else:
        for index, item in enumerate(examples, start=1):
            if not isinstance(item, dict):
                continue
            lines.append(f"{index}.")
            for code in FULL_LANGUAGE_ORDER:
                lines.append(f"   {code}: {item.get(code, '-') or '-'}")
    return "\n".join(lines)


def _build_snapshot_from_stored_data(
    *,
    pair: LanguagePairRecord,
    word: WordRecord,
    examples: tuple[ExampleRecord, ...],
) -> dict[str, Any]:
    word_map: dict[str, str] = {code: "-" for code in FULL_LANGUAGE_ORDER}
    word_map[pair.target_lang] = word.word
    word_map[pair.source_lang] = word.translation

    synonyms_payload: list[dict[str, str]] = []
    for raw in word.synonyms:
        text = raw.strip()
        if not text:
            continue
        row = {code: "-" for code in FULL_LANGUAGE_ORDER}
        row[pair.target_lang] = text
        row["target"] = text
        synonyms_payload.append(row)

    examples_payload: list[dict[str, str]] = []
    for example in examples:
        row = {
            "RU": example.translation_ru or "-",
            "EN": example.translation_en or "-",
            "DE": example.translation_de or "-",
            "HY": example.translation_hy or "-",
        }
        sentence = example.sentence.strip()
        if sentence:
            row[pair.target_lang] = sentence
        examples_payload.append(row)

    return {
        "word": word_map,
        "synonyms": synonyms_payload,
        "examples": examples_payload,
    }


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return

    context.user_data["add_state"] = {
        "step": "word",
        "pair_id": pair.id,
        "source_lang": pair.source_lang,
        "target_lang": pair.target_lang,
    }
    await message.reply_text(f"Введите слово на {SUPPORTED_LANGUAGES[pair.target_lang]}.")


async def add_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    state = context.user_data.get("add_state")
    if not state:
        await _safe_query_answer(query, text="Добавление не активно.", show_alert=True)
        return

    pair_id = state["pair_id"]
    sets_repo = _sets_repo(context)

    if query.data == ADD_SET_SKIP:
        state["set_id"] = None
        await _safe_query_answer(query)
        await _finalize_add_preview(update, context)
        return

    if query.data == ADD_SET_NEW:
        state["step"] = "new_set_name"
        await _safe_query_answer(query)
        await query.edit_message_text("Введите название новой темы:")
        return

    if query.data.startswith(ADD_SET_EXISTING_PREFIX):
        raw_id = query.data.removeprefix(ADD_SET_EXISTING_PREFIX)
        if not raw_id.isdigit():
            await _safe_query_answer(query, text="Некорректные данные.", show_alert=True)
            return
        set_id = int(raw_id)
        existing = await sets_repo.get_by_id(user_id=user.id, pair_id=pair_id, set_id=set_id)
        if existing is None:
            await _safe_query_answer(query, text="Тема не найдена.", show_alert=True)
            return
        state["set_id"] = set_id
        await _safe_query_answer(query)
        await _finalize_add_preview(update, context)
        return

    if query.data == ADD_SAVE:
        await _safe_query_answer(query)
        await _save_add_word(update, context)
        return

    if query.data == ADD_CANCEL:
        _state_clear(context, "add_state")
        await _safe_query_answer(query)
        await query.edit_message_text("Добавление слова отменено.")
        return

    await _safe_query_answer(query, text="Неизвестное действие.", show_alert=True)


async def _show_set_selection(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    pair_id: int,
    reply,
) -> None:
    sets_repo = _sets_repo(context)
    sets = await sets_repo.list_for_pair(user_id, pair_id)
    buttons: list[list[InlineKeyboardButton]] = []
    for item in sets:
        buttons.append(
            [
                InlineKeyboardButton(
                    item.name,
                    callback_data=f"{ADD_SET_EXISTING_PREFIX}{item.id}",
                )
            ]
        )
    buttons.extend(
        [
            [InlineKeyboardButton("Создать новую тему", callback_data=ADD_SET_NEW)],
            [InlineKeyboardButton("Пропустить", callback_data=ADD_SET_SKIP)],
        ]
    )
    await reply(
        "Выберите тему для слова:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def _generated_preview_text(
    content: GeneratedWordContent,
    *,
    source_lang: str,
    target_lang: str,
) -> str:
    lines = [
        "Проверьте карточку:",
        f"Слово: {content.word}",
        f"Перевод: {content.translation}",
    ]
    if content.part_of_speech:
        lines.append(f"Часть речи: {content.part_of_speech}")
    if content.gender:
        lines.append(f"Род: {content.gender}")
    if content.declension:
        lines.append("Склонение: " + format_declension(content.declension))
    if content.synonyms:
        lines.append("Синонимы: " + ", ".join(content.synonyms))
    lines.append("Примеры:")
    lines.append(
        format_examples(
            tuple(
                ExampleRecord(
                    sentence=item.sentence,
                    translation_ru=item.translation_ru,
                    translation_de=item.translation_de,
                    translation_en=item.translation_en,
                    translation_hy=item.translation_hy,
                )
                for item in content.examples
            ),
            source_lang=source_lang,
            target_lang=target_lang,
        )
    )
    return "\n".join(lines)


async def _finalize_add_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.get("add_state")
    user = update.effective_user
    if state is None or user is None:
        return

    content_service = _content_service(context)
    tts_service = _tts_service(context)
    if "word" not in state:
        _state_clear(context, "add_state")
        target = update.effective_message or (update.callback_query.message if update.callback_query else None)
        if target:
            await target.reply_text("Состояние добавления повреждено. Начните /add заново.")
        return

    target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    status_message = None
    if target:
        status_message = await _show_generation_status(
            target,
            "Секунду, генерирую карточку. Это может занять несколько секунд...",
        )

    source_lang = state["source_lang"]
    target_lang = state["target_lang"]
    word = state["word"]
    translation = state.get("translation")

    if target and not await _acquire_llm_slot(context=context, message=target, user_id=user.id):
        return

    try:
        generated = await content_service.generate(
            source_lang=source_lang,
            target_lang=target_lang,
            word=word,
            user_translation=translation,
        )
    except ContentGenerationError:
        _state_clear(context, "add_state")
        if status_message is not None:
            await _update_generation_status(
                status_message,
                "Не удалось сгенерировать карточку. Попробуйте позже.",
            )
        elif target:
            await target.reply_text("Не удалось сгенерировать примеры. Попробуйте позже.")
        return

    state["generated"] = asdict(generated)
    state["step"] = "confirm"

    tts_bytes = await tts_service.synthesize_word(generated.word, target_lang)
    state["tts_bytes"] = tts_bytes

    await _update_generation_status(status_message, "Готово. Проверьте карточку ниже.")

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Сохранить", callback_data=ADD_SAVE)],
            [InlineKeyboardButton("Отмена", callback_data=ADD_CANCEL)],
        ]
    )
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if message:
        await message.reply_text(
            _generated_preview_text(
                generated,
                source_lang=source_lang,
                target_lang=target_lang,
            ),
            reply_markup=keyboard,
        )


def _generated_from_state(state_payload: dict[str, Any]) -> GeneratedWordContent:
    examples = tuple(
        ExampleContent(
            sentence=item["sentence"],
            translation_ru=item["translation_ru"],
            translation_de=item["translation_de"],
            translation_en=item["translation_en"],
            translation_hy=item["translation_hy"],
        )
        for item in state_payload.get("examples", [])
    )
    return GeneratedWordContent(
        word=state_payload["word"],
        translation=state_payload["translation"],
        synonyms=tuple(state_payload.get("synonyms", [])),
        part_of_speech=state_payload.get("part_of_speech"),
        gender=state_payload.get("gender"),
        declension=state_payload.get("declension"),
        transcription=state_payload.get("transcription"),
        examples=examples,
    )


async def _upload_tts_and_get_file_id(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    word: str,
    audio_bytes: bytes,
) -> str | None:
    try:
        sent = await with_telegram_retry(
            lambda: context.bot.send_audio(
                chat_id=chat_id,
                audio=InputFile(io.BytesIO(audio_bytes), filename=f"{word}.mp3"),
                disable_notification=True,
            )
        )
    except Exception:
        logger.exception("Failed to upload generated TTS")
        return None

    file_id = sent.audio.file_id if sent.audio else None
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
    except Exception:
        logger.debug("Could not delete temporary TTS upload message")
    return file_id


async def _save_add_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    state = context.user_data.get("add_state")
    if not state:
        await query.edit_message_text("Состояние добавления потеряно. Начните /add заново.")
        return

    words_repo = _words_repo(context)
    generated_payload = state.get("generated")
    if not generated_payload:
        await query.edit_message_text("Нет данных карточки. Начните /add заново.")
        _state_clear(context, "add_state")
        return
    generated = _generated_from_state(generated_payload)
    word_id = await words_repo.create_word_bundle(
        user_id=user.id,
        pair_id=state["pair_id"],
        set_id=state.get("set_id"),
        content=generated,
        next_review_at=datetime.now(UTC),
    )

    tts_bytes = state.get("tts_bytes")
    if isinstance(tts_bytes, (bytes, bytearray)) and tts_bytes:
        file_id = await _upload_tts_and_get_file_id(
            context=context,
            chat_id=query.message.chat_id if query.message else user.id,
            word=generated.word,
            audio_bytes=bytes(tts_bytes),
        )
        if file_id:
            await words_repo.update_tts_word_file_id(word_id=word_id, file_id=file_id)

    _state_clear(context, "add_state")
    context.user_data["last_word_ref"] = {
        "pair_id": state["pair_id"],
        "word_id": word_id,
    }
    await query.edit_message_text("Слово сохранено. Созданы прямая и обратная карточки.")


def _train_prompt(card: DueCardRecord) -> str:
    direction = f"{card.source_lang} -> {card.target_lang}"
    if card.direction == "forward":
        shown = card.translation
        ask_lang = SUPPORTED_LANGUAGES[card.target_lang]
    else:
        shown = card.word
        ask_lang = SUPPORTED_LANGUAGES[card.source_lang]
    return f"[Направление: {direction}]\n\nСлово: {shown}\n\nПереведите на {ask_lang}."


def _train_result_text(
    *,
    is_correct: bool,
    card: DueCardRecord,
    forced_prompt: bool = False,
) -> str:
    status = "Верно!" if is_correct else "Неверно."
    lines = [
        status,
        "",
        f"Правильный ответ: {card.word if card.direction == 'forward' else card.translation}",
    ]
    if card.gender:
        lines.append(f"Род: {card.gender}")
    if card.declension:
        lines.append("Склонение: " + format_declension(card.declension))
    lines.append("")
    lines.append("Примеры:")
    lines.append(
        format_examples(
            card.examples,
            source_lang=card.source_lang,
            target_lang=card.target_lang,
        )
    )
    if forced_prompt and not is_correct:
        lines.append("")
        lines.append("Введите правильный перевод:")
    return "\n".join(lines)


async def _send_train_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if message is None:
        return

    state = context.user_data.get("train_state")
    if not state:
        return

    index = state["index"]
    cards: list[DueCardRecord] = state["cards"]
    if index >= len(cards):
        _state_clear(context, "train_state")
        await message.reply_text("Тренировка завершена. Карточки из очереди закончились.")
        return

    card = cards[index]
    context.user_data["last_word_ref"] = {
        "pair_id": card.language_pair_id,
        "word_id": card.word_id,
    }
    buttons: list[list[InlineKeyboardButton]] = []
    if card.tts_word_file_id:
        buttons.append([InlineKeyboardButton("Озвучить", callback_data=TRAIN_TTS)])
    buttons.append([InlineKeyboardButton("Пропустить", callback_data=TRAIN_SKIP)])

    state["mode"] = "answer"
    state["card_started_at"] = datetime.now(UTC).timestamp()
    await message.reply_text(_train_prompt(card), reply_markup=InlineKeyboardMarkup(buttons))


async def train_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return

    # Any pending reminder quiz should not conflict with explicit full training.
    await _reminder_quiz_repo(context).clear(user.id)

    cards_repo = _cards_repo(context)
    set_id = context.user_data.get("active_set_id")
    now = datetime.now(UTC)
    due_cards = await cards_repo.list_due_cards(
        user_id=user.id,
        pair_id=pair.id,
        now=now,
        set_id=set_id,
        limit=500,
    )
    if not due_cards:
        total_cards = await cards_repo.count_all_for_pair(
            user_id=user.id,
            pair_id=pair.id,
            set_id=set_id,
        )
        if total_cards == 0:
            await message.reply_text("У вас пока нет карточек. Добавьте слово командой /add.")
            return
        next_review_at = await cards_repo.next_review_at(
            user_id=user.id,
            pair_id=pair.id,
            set_id=set_id,
        )
        if next_review_at is None:
            await message.reply_text("Нет карточек для повторения.")
            return
        await message.reply_text(
            f"Нет карточек для повторения. Следующее повторение через {format_next_review_delta(next_review_at)}."
        )
        return

    context.user_data["train_state"] = {
        "pair_id": pair.id,
        "set_id": set_id,
        "cards": due_cards,
        "index": 0,
        "mode": "answer",
    }
    await _send_train_card(update, context)


async def _handle_reminder_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return False

    reminder_repo = _reminder_quiz_repo(context)
    state = await reminder_repo.get(user.id)
    if not isinstance(state, dict):
        return False

    if context.user_data.get("train_state"):
        logger.info(
            "Pending reminder answer for user %s while train_state exists; clearing stale train_state",
            user.id,
        )
        _state_clear(context, "train_state")

    try:
        card_id = int(state["card_id"])
        direction = str(state["direction"])
        source_lang = str(state["source_lang"])
        target_lang = str(state["target_lang"])
        word = str(state["word"])
        translation = str(state["translation"])
        srs_index = int(state["srs_index"])
        synonyms = tuple(str(item) for item in state.get("synonyms", []))
    except Exception:
        await reminder_repo.clear(user.id)
        await message.reply_text("Мини-повторение сброшено. Я пришлю новый вопрос позже.")
        return True

    answer = message.text.strip()
    if not answer:
        await message.reply_text("Введите ответ текстом.")
        return True

    validator = _validation_service(context)
    is_correct = validator.is_correct_for_card(
        answer=answer,
        context=CardAnswerContext(
            direction=direction,  # type: ignore[arg-type]
            source_lang=source_lang,  # type: ignore[arg-type]
            target_lang=target_lang,  # type: ignore[arg-type]
            word=word,
            translation=translation,
            synonyms=synonyms,
        ),
    )

    now = datetime.now(UTC)
    sent_at = state.get("sent_at")
    response_time_ms = None
    if isinstance(sent_at, datetime):
        sent_at_utc = sent_at.replace(tzinfo=UTC) if sent_at.tzinfo is None else sent_at.astimezone(UTC)
        response_time_ms = max(0, int((now - sent_at_utc).total_seconds() * 1000))

    cards_repo = _cards_repo(context)
    reviews_repo = _reviews_repo(context)
    users_repo = _users_repo(context)
    srs = _srs_service(context)

    if is_correct:
        next_state = srs.apply_correct(srs_index, now=now)
        await cards_repo.update_after_correct(
            card_id=card_id,
            next_index=next_state.srs_index,
            next_review_at=next_state.next_review_at,
        )
        await reviews_repo.add_review(
            card_id=card_id,
            user_id=user.id,
            answer=answer,
            is_correct=True,
            response_time_ms=response_time_ms,
        )
        await users_repo.touch_training_activity(user.id, now)
        await message.reply_text("Верно. Мини-повторение завершено.")
    else:
        next_state = srs.apply_wrong(srs_index, now=now)
        await cards_repo.update_after_wrong(
            card_id=card_id,
            next_index=next_state.srs_index,
            next_review_at=next_state.next_review_at,
        )
        await reviews_repo.add_review(
            card_id=card_id,
            user_id=user.id,
            answer=answer,
            is_correct=False,
            response_time_ms=response_time_ms,
        )
        await users_repo.touch_training_activity(user.id, now)
        correct_answer = word if direction == "forward" else translation
        await message.reply_text(
            f"Неверно. Правильный ответ: {correct_answer}\nМини-повторение завершено."
        )

    await reminder_repo.clear(user.id)
    return True


async def train_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    state = context.user_data.get("train_state")
    if not state:
        await query.answer("Тренировка не активна.", show_alert=True)
        return

    cards: list[DueCardRecord] = state["cards"]
    index = state["index"]
    if index >= len(cards):
        _state_clear(context, "train_state")
        await query.answer()
        return

    current = cards[index]
    if query.data == TRAIN_TTS:
        await query.answer()
        if current.tts_word_file_id and query.message is not None:
            await query.message.reply_audio(audio=current.tts_word_file_id)
        return

    if query.data == TRAIN_SKIP:
        if state.get("mode") == "forced_retry":
            await query.answer("Сначала введите правильный ответ.", show_alert=True)
            return
        skipped = cards.pop(index)
        cards.append(skipped)
        state["index"] = index
        await query.answer("Карточка пропущена.")
        await _send_train_card(update, context)
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def _finish_train_after_answer(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    is_correct: bool,
    card: DueCardRecord,
    answer: str,
    response_time_ms: int | None,
) -> None:
    cards_repo = _cards_repo(context)
    reviews_repo = _reviews_repo(context)
    users_repo = _users_repo(context)
    srs = _srs_service(context)
    now = datetime.now(UTC)

    if is_correct:
        next_state = srs.apply_correct(card.srs_index, now=now)
        await cards_repo.update_after_correct(
            card_id=card.id,
            next_index=next_state.srs_index,
            next_review_at=next_state.next_review_at,
        )
        await reviews_repo.add_review(
            card_id=card.id,
            user_id=card.user_id,
            answer=answer,
            is_correct=True,
            response_time_ms=response_time_ms,
        )
        await users_repo.touch_training_activity(card.user_id, now)
        target = update.effective_message or (update.callback_query.message if update.callback_query else None)
        if target:
            await target.reply_text(_train_result_text(is_correct=True, card=card))
        state = context.user_data["train_state"]
        state["index"] += 1
        await _send_train_card(update, context)
        return

    wrong_state = srs.apply_wrong(card.srs_index, now=now)
    context.user_data["train_state"]["mode"] = "forced_retry"
    context.user_data["train_state"]["pending_wrong"] = {
        "card_id": card.id,
        "next_index": wrong_state.srs_index,
        "next_review_at": wrong_state.next_review_at,
    }
    await reviews_repo.add_review(
        card_id=card.id,
        user_id=card.user_id,
        answer=answer,
        is_correct=False,
        response_time_ms=response_time_ms,
    )
    target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(_train_result_text(is_correct=False, card=card, forced_prompt=True))


async def _handle_train_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return False
    state = context.user_data.get("train_state")
    if not state:
        return False
    cards: list[DueCardRecord] = state["cards"]
    index = state["index"]
    if index >= len(cards):
        _state_clear(context, "train_state")
        return False

    card = cards[index]
    validator = _validation_service(context)

    if state.get("mode") == "forced_retry":
        ok = validator.is_correct_for_card(
            answer=message.text,
            context=CardAnswerContext(
                direction=card.direction,
                source_lang=card.source_lang,
                target_lang=card.target_lang,
                word=card.word,
                translation=card.translation,
                synonyms=card.synonyms,
            ),
        )
        if not ok:
            await message.reply_text(
                f"Неверно. Правильный ответ: {card.word if card.direction == 'forward' else card.translation}. Попробуйте ещё раз:"
            )
            return True

        pending = state.get("pending_wrong")
        if pending:
            await _cards_repo(context).update_after_wrong(
                card_id=pending["card_id"],
                next_index=pending["next_index"],
                next_review_at=pending["next_review_at"],
            )
            await _users_repo(context).touch_training_activity(user.id, datetime.now(UTC))
        state["mode"] = "answer"
        state["pending_wrong"] = None
        state["index"] += 1
        await message.reply_text("Принято. Переходим к следующей карточке.")
        await _send_train_card(update, context)
        return True

    started_ts = state.get("card_started_at")
    response_time_ms = None
    if isinstance(started_ts, (int, float)):
        response_time_ms = max(0, int((datetime.now(UTC).timestamp() - started_ts) * 1000))

    is_correct = validator.is_correct_for_card(
        answer=message.text,
        context=CardAnswerContext(
            direction=card.direction,
            source_lang=card.source_lang,
            target_lang=card.target_lang,
            word=card.word,
            translation=card.translation,
            synonyms=card.synonyms,
        ),
    )
    await _finish_train_after_answer(
        update=update,
        context=context,
        is_correct=is_correct,
        card=card,
        answer=message.text,
        response_time_ms=response_time_ms,
    )
    return True


async def due_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return
    due_count = await _cards_repo(context).count_due_for_pair(
        user_id=user.id,
        pair_id=pair.id,
        now=datetime.now(UTC),
        set_id=context.user_data.get("active_set_id"),
    )
    await message.reply_text(f"Карточек к повторению: {due_count}")


def _pagination_buttons(prefix: str, page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    buttons: list[InlineKeyboardButton] = []
    if page > 0:
        buttons.append(InlineKeyboardButton("Назад", callback_data=f"{prefix}{page - 1}"))
    if page < (total_pages - 1):
        buttons.append(InlineKeyboardButton("Вперед", callback_data=f"{prefix}{page + 1}"))
    return InlineKeyboardMarkup([buttons]) if buttons else None


async def _render_list_page(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
    edit: bool,
) -> None:
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    user = update.effective_user
    if message is None or user is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return
    words_repo = _words_repo(context)
    set_id = context.user_data.get("active_set_id")
    total = await words_repo.count_words(user_id=user.id, pair_id=pair.id, set_id=set_id)
    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    rows = await words_repo.list_words_page(
        user_id=user.id,
        pair_id=pair.id,
        page=page,
        page_size=PAGE_SIZE,
        set_id=set_id,
    )
    if not rows:
        text = "Список слов пуст."
    else:
        lines = [
            f"{idx + 1 + page * PAGE_SIZE}. {row['word']} -- {row['translation']} ({row['forward_srs_index']})"
            for idx, row in enumerate(rows)
        ]
        text = "\n".join(lines)
    markup = _pagination_buttons(LIST_PAGE_PREFIX, page, total_pages)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _render_list_page(update=update, context=context, page=0, edit=False)


async def list_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    raw = query.data.removeprefix(LIST_PAGE_PREFIX)
    if not raw.isdigit():
        await query.answer("Некорректная страница.", show_alert=True)
        return
    await query.answer()
    await _render_list_page(update=update, context=context, page=int(raw), edit=True)


async def _render_duelist_page(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
    edit: bool,
) -> None:
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    user = update.effective_user
    if message is None or user is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return
    cards_repo = _cards_repo(context)
    set_id = context.user_data.get("active_set_id")
    now = datetime.now(UTC)
    total = await cards_repo.count_due_for_pair(
        user_id=user.id,
        pair_id=pair.id,
        now=now,
        set_id=set_id,
    )
    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    rows = await cards_repo.list_due_page(
        user_id=user.id,
        pair_id=pair.id,
        now=now,
        page=page,
        page_size=PAGE_SIZE,
        set_id=set_id,
    )
    if not rows:
        text = "Нет карточек для повторения."
    else:
        lines = []
        for idx, row in enumerate(rows, start=1 + page * PAGE_SIZE):
            overdue = format_overdue(row["next_review_at"], now=now)
            lines.append(
                f"{idx}. {row['word']} -- {row['translation']} ({row['direction']}, просрочено {overdue})"
            )
        text = "\n".join(lines)
    markup = _pagination_buttons(DUELIST_PAGE_PREFIX, page, total_pages)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup)


async def duelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _render_duelist_page(update=update, context=context, page=0, edit=False)


async def duelist_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    raw = query.data.removeprefix(DUELIST_PAGE_PREFIX)
    if not raw.isdigit():
        await query.answer("Некорректная страница.", show_alert=True)
        return
    await query.answer()
    await _render_duelist_page(update=update, context=context, page=int(raw), edit=True)


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return

    arg = _command_argument(message.text)
    if arg:
        await _delete_by_word_text(update, context, arg, pair.id)
        return

    context.user_data["delete_state"] = {"step": "await_word", "pair_id": pair.id}
    await message.reply_text("Введите слово для удаления.")


async def _delete_by_word_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, word_text: str, pair_id: int
) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    words_repo = _words_repo(context)
    word = await words_repo.find_by_word(user_id=user.id, pair_id=pair_id, word=word_text)
    if word is None:
        await message.reply_text("Слово не найдено.")
        return
    deleted = await words_repo.delete_word(user_id=user.id, pair_id=pair_id, word_id=word.id)
    if deleted:
        await message.reply_text(f"Удалено: {word.word}")
    else:
        await message.reply_text("Не удалось удалить слово.")


async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return

    arg = _command_argument(message.text)
    if arg:
        await _begin_edit_for_word(
            update,
            context,
            pair.id,
            arg,
            source_lang=pair.source_lang,
            target_lang=pair.target_lang,
        )
        return
    context.user_data["edit_state"] = {
        "step": "await_word",
        "pair_id": pair.id,
        "source_lang": pair.source_lang,
        "target_lang": pair.target_lang,
    }
    await message.reply_text("Введите слово для редактирования.")


def _edit_fields_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Перевод", callback_data=EDIT_TRANSLATION)],
            [InlineKeyboardButton("Примеры", callback_data=EDIT_EXAMPLES)],
            [InlineKeyboardButton("Примечание", callback_data=EDIT_NOTE)],
            [InlineKeyboardButton("Отмена", callback_data=EDIT_CANCEL)],
        ]
    )


async def _begin_edit_for_word(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pair_id: int,
    word_text: str,
    *,
    source_lang: str,
    target_lang: str,
) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    words_repo = _words_repo(context)
    word = await words_repo.find_by_word(user_id=user.id, pair_id=pair_id, word=word_text)
    if word is None:
        await message.reply_text("Слово не найдено.")
        return

    examples = await words_repo.list_examples(word_id=word.id)
    context.user_data["edit_state"] = {
        "step": "choose_field",
        "pair_id": pair_id,
        "word_id": word.id,
        "word": word.word,
        "translation": word.translation,
    }
    preview = [
        f"Слово: {word.word}",
        f"Перевод: {word.translation}",
        f"Примечание: {word.note or '-'}",
        "Примеры:",
        format_examples(
            examples,
            source_lang=source_lang,
            target_lang=target_lang,
        ),
        "",
        "Выберите поле для редактирования:",
    ]
    await message.reply_text("\n".join(preview), reply_markup=_edit_fields_keyboard())


async def edit_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    state = context.user_data.get("edit_state")
    if not state:
        await query.answer("Редактирование не активно.", show_alert=True)
        return

    if query.data == EDIT_CANCEL:
        _state_clear(context, "edit_state")
        await query.answer()
        await query.edit_message_text("Редактирование отменено.")
        return

    if query.data == EDIT_TRANSLATION:
        state["step"] = "await_translation"
        await query.answer()
        await query.edit_message_text("Введите новый перевод:")
        return
    if query.data == EDIT_EXAMPLES:
        state["step"] = "await_examples"
        await query.answer()
        await query.edit_message_text(
            (
                "Введите примеры, по одному на строку в формате:\n"
                "sentence | ru | de | en | hy"
            )
        )
        return
    if query.data == EDIT_NOTE:
        state["step"] = "await_note"
        await query.answer()
        await query.edit_message_text("Введите новое примечание (или '-' чтобы очистить):")
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def sets_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return
    await _render_sets_panel(update=update, context=context, pair_id=pair.id, edit=False)


async def _render_sets_panel(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pair_id: int,
    edit: bool,
) -> None:
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    user = update.effective_user
    if message is None or user is None:
        return
    sets_repo = _sets_repo(context)
    items = await sets_repo.list_for_pair(user.id, pair_id)
    active_set_id = context.user_data.get("active_set_id")
    buttons: list[list[InlineKeyboardButton]] = []
    for item in items:
        marker = "✅ " if item.id == active_set_id else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{marker}{item.name}",
                    callback_data=f"{SETS_SELECT_PREFIX}{item.id}",
                )
            ]
        )
    buttons.extend(
        [
            [InlineKeyboardButton("Сбросить фильтр", callback_data=SETS_CLEAR)],
            [InlineKeyboardButton("Создать тему", callback_data=SETS_CREATE)],
        ]
    )
    current_filter = "нет"
    if active_set_id:
        for item in items:
            if item.id == active_set_id:
                current_filter = item.name
                break
    text = f"Тематические наборы. Активный фильтр для /list и /train: {current_filter}"
    markup = InlineKeyboardMarkup(buttons)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup)


async def sets_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await query.answer("Сначала /start", show_alert=True)
        return

    data = query.data
    if data == SETS_CLEAR:
        context.user_data["active_set_id"] = None
        await query.answer("Фильтр сброшен.")
        await _render_sets_panel(update=update, context=context, pair_id=pair.id, edit=True)
        return
    if data == SETS_CREATE:
        context.user_data["sets_state"] = {"step": "create_name", "pair_id": pair.id}
        await query.answer()
        await query.edit_message_text("Введите название новой темы:")
        return
    if data.startswith(SETS_SELECT_PREFIX):
        raw = data.removeprefix(SETS_SELECT_PREFIX)
        if not raw.isdigit():
            await query.answer("Некорректная тема.", show_alert=True)
            return
        set_id = int(raw)
        existing = await _sets_repo(context).get_by_id(
            user_id=user.id,
            pair_id=pair.id,
            set_id=set_id,
        )
        if existing is None:
            await query.answer("Тема не найдена.", show_alert=True)
            return
        context.user_data["active_set_id"] = set_id
        await query.answer("Фильтр обновлен.")
        await _render_sets_panel(update=update, context=context, pair_id=pair.id, edit=True)
        return
    await query.answer("Неизвестное действие.", show_alert=True)


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return

    rows = await _words_repo(context).list_export_rows(user_id=user.id, pair_id=pair.id)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "word",
            "translation",
            "part_of_speech",
            "theme",
            "srs_index",
            "correct_count",
            "incorrect_count",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    buffer = io.BytesIO(output.getvalue().encode("utf-8"))
    filename = f"vocab_export_{pair.source_lang}_{pair.target_lang}.csv"
    await message.reply_document(
        document=InputFile(buffer, filename=filename),
        filename=filename,
    )


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return
    context.user_data["import_state"] = {
        "step": "await_document",
        "pair_id": pair.id,
        "source_lang": pair.source_lang,
        "target_lang": pair.target_lang,
    }
    await message.reply_text("Отправьте CSV-файл. Минимальные колонки: word,translation.")


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    users_repo = _users_repo(context)
    user_record = await users_repo.get_or_create(user.id, user.username, user.first_name)
    new_state = not user_record.reminders_enabled
    await users_repo.set_reminders_enabled(user.id, new_state)
    await message.reply_text(
        "Напоминания включены." if new_state else "Напоминания выключены."
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return
    stats = await _words_repo(context).stats_for_pair(user_id=user.id, pair_id=pair.id)
    text = (
        f"Статистика для пары {pair.source_lang} -> {pair.target_lang}:\n"
        f"Всего слов: {stats['total_words']}\n"
        f"Выучено: {stats['learned_words']}\n"
        f"В процессе: {stats['in_progress_words']}\n"
        f"Среднее количество ошибок: {stats['avg_mistakes']:.2f}"
    )
    await message.reply_text(text)


async def fullword_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    pair = await get_active_pair(context, user.id)
    if pair is None:
        await message.reply_text("Сначала выберите языковую пару с помощью /start.")
        return

    arg = _command_argument(message.text)
    if arg:
        await _send_full_snapshot_by_word(
            update,
            context,
            pair_id=pair.id,
            word_text=arg,
        )
        return

    context.user_data["fullword_state"] = {
        "step": "await_word",
        "pair_id": pair.id,
    }
    await message.reply_text(
        "Для какого слова показать полную карточку из памяти? Введите слово."
    )


async def _send_full_snapshot_by_word(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    pair_id: int,
    word_text: str,
) -> None:
    message = update.effective_message or (
        update.callback_query.message if update.callback_query else None
    )
    user = update.effective_user
    if message is None or user is None:
        return

    words_repo = _words_repo(context)
    word = await words_repo.find_by_word_for_lookup(
        user_id=user.id,
        pair_id=pair_id,
        word=word_text,
    )
    if word is None:
        await message.reply_text("Слово не найдено в активной паре.")
        return

    snapshot = await words_repo.get_full_snapshot(word_id=word.id)
    if snapshot is None:
        pair = await pairs_repo(context).get_by_id(pair_id)
        if pair is None or pair.user_id != user.id:
            await message.reply_text("Активная языковая пара не найдена.")
            return

        examples = await words_repo.list_examples(word_id=word.id)
        example_input = tuple(
            {
                "target_sentence": item.sentence,
                "source_translation": _example_translation_for_lang(item, pair.source_lang),
            }
            for item in examples
            if item.sentence.strip()
        )
        synonyms_for_snapshot = tuple(
            base
            for base in (_synonym_base_text(item) for item in word.synonyms)
            if base
        )

        if await _acquire_llm_slot(context=context, message=message, user_id=user.id):
            status_message = await _show_generation_status(
                message,
                (
                    "Для этого слова нет готового полного snapshot в памяти. "
                    "Формирую и сохраняю, подождите..."
                ),
            )
            try:
                snapshot = await _content_service(context).build_multilingual_snapshot(
                    source_lang=pair.source_lang,
                    target_lang=pair.target_lang,
                    word=word.word,
                    translation=word.translation,
                    synonyms=synonyms_for_snapshot,
                    examples=example_input,
                )
                await words_repo.upsert_full_snapshot(word_id=word.id, payload=snapshot)
                await _update_generation_status(
                    status_message,
                    "Готово. Snapshot сохранен в памяти, ниже полная карточка.",
                )
            except ContentGenerationError:
                snapshot = _build_snapshot_from_stored_data(
                    pair=pair,
                    word=word,
                    examples=examples,
                )
                await _update_generation_status(
                    status_message,
                    "Не удалось сформировать полный snapshot, показываю сохраненные данные из БД.",
                )
        else:
            snapshot = _build_snapshot_from_stored_data(
                pair=pair,
                word=word,
                examples=examples,
            )

    text = _format_full_snapshot_text(snapshot=snapshot, word=word)
    chunk_size = 3600
    for start in range(0, len(text), chunk_size):
        await message.reply_text(text[start : start + chunk_size])


async def full_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    last_ref = context.user_data.get("last_word_ref")
    if not isinstance(last_ref, dict):
        await message.reply_text(
            "Пока нет последней карточки. Начните /train или сохраните слово через /add."
        )
        return

    pair_id = last_ref.get("pair_id")
    word_id = last_ref.get("word_id")
    if not isinstance(pair_id, int) or not isinstance(word_id, int):
        await message.reply_text("Не удалось определить последнюю карточку. Попробуйте /train.")
        return

    pair = await pairs_repo(context).get_by_id(pair_id)
    if pair is None or pair.user_id != user.id:
        await message.reply_text("Последняя карточка больше не доступна.")
        return

    words_repo = _words_repo(context)
    word = await words_repo.get_by_id(user_id=user.id, pair_id=pair_id, word_id=word_id)
    if word is None:
        await message.reply_text("Слово не найдено.")
        return

    examples = await words_repo.list_examples(word_id=word_id)
    example_input = tuple(
        {
            "target_sentence": item.sentence,
            "source_translation": _example_translation_for_lang(item, pair.source_lang),
        }
        for item in examples
        if item.sentence.strip()
    )
    synonyms_for_snapshot = tuple(
        base
        for base in (_synonym_base_text(item) for item in word.synonyms)
        if base
    )
    snapshot = await words_repo.get_full_snapshot(word_id=word_id)
    if snapshot is None:
        if not await _acquire_llm_slot(context=context, message=message, user_id=user.id):
            return
        status_message = await _show_generation_status(
            message,
            "Секунду, собираю полную карточку на 4 языках. Это может занять несколько секунд...",
        )
        try:
            snapshot = await _content_service(context).build_multilingual_snapshot(
                source_lang=pair.source_lang,
                target_lang=pair.target_lang,
                word=word.word,
                translation=word.translation,
                synonyms=synonyms_for_snapshot,
                examples=example_input,
            )
        except ContentGenerationError:
            await _update_generation_status(
                status_message,
                "Не удалось сформировать полную карточку на 4 языках. Попробуйте позже.",
            )
            if status_message is None:
                await message.reply_text(
                    "Не удалось сформировать полную карточку на 4 языках. Попробуйте позже."
                )
            return
        await words_repo.upsert_full_snapshot(word_id=word_id, payload=snapshot)
        await _update_generation_status(
            status_message,
            "Готово. Ниже полная карточка.",
        )

    text = _format_full_snapshot_text(snapshot=snapshot, word=word)
    chunk_size = 3600
    for start in range(0, len(text), chunk_size):
        await message.reply_text(text[start : start + chunk_size])


def _parse_examples_input(raw: str) -> tuple[ExampleContent, ...] | None:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    examples: list[ExampleContent] = []
    for line in lines:
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 5:
            return None
        examples.append(
            ExampleContent(
                sentence=parts[0],
                translation_ru=parts[1],
                translation_de=parts[2],
                translation_en=parts[3],
                translation_hy=parts[4],
            )
        )
    return tuple(examples) if examples else None


async def _handle_add_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return False
    state = context.user_data.get("add_state")
    if not state:
        return False

    step = state.get("step")
    if step == "word":
        word = message.text.strip()
        if not word:
            await message.reply_text("Введите непустое слово.")
            return True
        state["word"] = word
        state["step"] = "translation"
        await message.reply_text("Введите перевод или отправьте '-' для автоподбора.")
        return True

    if step == "translation":
        state["translation"] = None if message.text.strip() == "-" else message.text.strip()
        state["step"] = "set_choice"
        await _show_set_selection(
            context=context,
            user_id=user.id,
            pair_id=state["pair_id"],
            reply=message.reply_text,
        )
        return True

    if step == "new_set_name":
        set_name = message.text.strip()
        if not set_name:
            await message.reply_text("Название темы не может быть пустым.")
            return True
        created = await _sets_repo(context).create_or_get(
            user_id=user.id,
            pair_id=state["pair_id"],
            name=set_name,
        )
        state["set_id"] = created.id
        await _finalize_add_preview(update, context)
        return True

    if step in {"set_choice", "confirm"}:
        await message.reply_text("Используйте кнопки под сообщением.")
        return True
    return False


async def _handle_delete_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    if message is None or not message.text:
        return False
    state = context.user_data.get("delete_state")
    user = update.effective_user
    if not state or user is None:
        return False
    if state.get("step") != "await_word":
        return False
    await _delete_by_word_text(update, context, message.text.strip(), state["pair_id"])
    _state_clear(context, "delete_state")
    return True


async def _handle_fullword_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    if message is None or not message.text:
        return False
    state = context.user_data.get("fullword_state")
    if not state:
        return False
    if state.get("step") != "await_word":
        return False

    pair_id = state.get("pair_id")
    if not isinstance(pair_id, int):
        _state_clear(context, "fullword_state")
        return True

    word_text = message.text.strip()
    if not word_text:
        await message.reply_text("Введите непустое слово.")
        return True

    await _send_full_snapshot_by_word(
        update,
        context,
        pair_id=pair_id,
        word_text=word_text,
    )
    _state_clear(context, "fullword_state")
    return True


async def _handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return False
    state = context.user_data.get("edit_state")
    if not state:
        return False

    step = state.get("step")
    words_repo = _words_repo(context)
    content_service = _content_service(context)
    pair = await get_active_pair(context, user.id)
    if pair is None:
        _state_clear(context, "edit_state")
        return True

    if step == "await_word":
        await _begin_edit_for_word(
            update,
            context,
            state["pair_id"],
            message.text.strip(),
            source_lang=state.get("source_lang", pair.source_lang),
            target_lang=state.get("target_lang", pair.target_lang),
        )
        return True

    if step == "await_translation":
        new_translation = message.text.strip()
        if not new_translation:
            await message.reply_text("Перевод не может быть пустым.")
            return True
        word = await words_repo.get_by_id(
            user_id=user.id,
            pair_id=pair.id,
            word_id=state["word_id"],
        )
        if word is None:
            _state_clear(context, "edit_state")
            await message.reply_text("Слово не найдено.")
            return True
        if not await _acquire_llm_slot(context=context, message=message, user_id=user.id):
            await words_repo.update_translation_and_synonyms(
                word_id=word.id,
                translation=new_translation,
                synonyms=word.synonyms,
            )
            await words_repo.clear_full_snapshot(word_id=word.id)
            _state_clear(context, "edit_state")
            await message.reply_text(
                "Перевод обновлен. Синонимы оставлены прежними из-за лимита генерации."
            )
            return True
        status_message = await _show_generation_status(
            message,
            "Обновляю перевод и генерирую синонимы. Подождите...",
        )
        try:
            new_synonyms = await content_service.regenerate_synonyms(
                source_lang=pair.source_lang,
                target_lang=pair.target_lang,
                word=word.word,
                translation=new_translation,
            )
        except ContentGenerationError:
            new_synonyms = word.synonyms
            await _update_generation_status(
                status_message,
                "Не удалось обновить синонимы, сохраняю старые.",
            )
            await message.reply_text(
                "Перевод сохранен, но синонимы не удалось обновить. Старые синонимы сохранены."
            )
        else:
            await _update_generation_status(status_message, "Готово.")
        await words_repo.update_translation_and_synonyms(
            word_id=word.id,
            translation=new_translation,
            synonyms=new_synonyms,
        )
        await words_repo.clear_full_snapshot(word_id=word.id)
        _state_clear(context, "edit_state")
        await message.reply_text("Перевод обновлен.")
        return True

    if step == "await_examples":
        parsed = _parse_examples_input(message.text)
        if not parsed:
            await message.reply_text("Неверный формат. Используйте: sentence | ru | de | en | hy")
            return True
        word = await words_repo.get_by_id(
            user_id=user.id,
            pair_id=pair.id,
            word_id=state["word_id"],
        )
        if word is None:
            _state_clear(context, "edit_state")
            await message.reply_text("Слово не найдено.")
            return True

        await words_repo.replace_examples(word_id=word.id, examples=parsed)
        await words_repo.clear_full_snapshot(word_id=word.id)
        if not await _acquire_llm_slot(context=context, message=message, user_id=user.id):
            _state_clear(context, "edit_state")
            await message.reply_text("Примеры сохранены. Синонимы не обновлялись из-за лимита генерации.")
            return True
        status_message = await _show_generation_status(
            message,
            "Примеры обновлены. Генерирую новые синонимы, подождите...",
        )
        try:
            new_synonyms = await content_service.regenerate_synonyms(
                source_lang=pair.source_lang,
                target_lang=pair.target_lang,
                word=word.word,
                translation=word.translation,
            )
            await words_repo.update_translation_and_synonyms(
                word_id=word.id,
                translation=word.translation,
                synonyms=new_synonyms,
            )
            await _update_generation_status(status_message, "Готово.")
        except ContentGenerationError:
            await _update_generation_status(
                status_message,
                "Примеры обновлены, но синонимы не удалось перегенерировать.",
            )
            await message.reply_text(
                "Примеры обновлены, но синонимы не удалось перегенерировать."
            )
        _state_clear(context, "edit_state")
        await message.reply_text("Примеры обновлены.")
        return True

    if step == "await_note":
        note = message.text.strip()
        await words_repo.update_note(
            word_id=state["word_id"],
            note=None if note == "-" else note,
        )
        _state_clear(context, "edit_state")
        await message.reply_text("Примечание обновлено.")
        return True

    return False


async def _handle_sets_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return False
    state = context.user_data.get("sets_state")
    if not state:
        return False
    if state.get("step") != "create_name":
        return False
    name = message.text.strip()
    if not name:
        await message.reply_text("Название не может быть пустым.")
        return True
    created = await _sets_repo(context).create_or_get(
        user_id=user.id,
        pair_id=state["pair_id"],
        name=name,
    )
    context.user_data["active_set_id"] = created.id
    _state_clear(context, "sets_state")
    await message.reply_text(f"Тема '{created.name}' создана и установлена как фильтр.")
    return True


async def _handle_import_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    if message is None:
        return False
    state = context.user_data.get("import_state")
    if not state or state.get("step") != "await_document":
        return False
    await message.reply_text("Ожидаю CSV-файл документом.")
    return True


async def stateful_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for handler in (
        _handle_reminder_text,
        _handle_train_text,
        _handle_add_text,
        _handle_fullword_text,
        _handle_delete_text,
        _handle_edit_text,
        _handle_sets_text,
        _handle_import_text,
    ):
        try:
            handled = await handler(update, context)
        except Exception:
            logger.exception("Stateful text handler failed")
            raise
        if handled:
            return


async def import_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.document is None:
        return
    state = context.user_data.get("import_state")
    if not state or state.get("step") != "await_document":
        return

    file_size = int(message.document.file_size or 0)
    if file_size > MAX_IMPORT_FILE_BYTES:
        _state_clear(context, "import_state")
        await message.reply_text(
            f"CSV слишком большой. Максимум: {MAX_IMPORT_FILE_BYTES // 1024} KB."
        )
        return

    file = await context.bot.get_file(message.document.file_id)
    data = await file.download_as_bytearray()
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        _state_clear(context, "import_state")
        await message.reply_text("Файл должен быть в UTF-8.")
        return

    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "word" not in reader.fieldnames or "translation" not in reader.fieldnames:
        _state_clear(context, "import_state")
        await message.reply_text("CSV должен содержать колонки word и translation.")
        return

    words_repo = _words_repo(context)
    content_service = _content_service(context)
    tts_service = _tts_service(context)
    pair_id = state["pair_id"]
    source_lang = state["source_lang"]
    target_lang = state["target_lang"]

    imported = 0
    skipped = 0
    processed = 0
    limit_reached = False
    await message.reply_text(
        (
            "Импорт запущен. Генерирую карточки, это может занять время...\n"
            f"Лимит за один импорт: {MAX_IMPORT_ROWS} строк."
        )
    )
    for row in reader:
        if processed >= MAX_IMPORT_ROWS:
            limit_reached = True
            break
        processed += 1
        word = (row.get("word") or "").strip()
        translation = (row.get("translation") or "").strip()
        if not word or not translation:
            skipped += 1
            continue

        exists = await words_repo.exists_word_translation(
            user_id=user.id,
            pair_id=pair_id,
            word=word,
            translation=translation,
        )
        if exists:
            skipped += 1
            continue

        if not await _acquire_llm_slot(context=context, message=message, user_id=user.id):
            _state_clear(context, "import_state")
            await message.reply_text(
                f"Импорт остановлен из-за лимита генерации. Добавлено: {imported}. Пропущено: {skipped}."
            )
            return

        try:
            generated = await content_service.generate(
                source_lang=source_lang,
                target_lang=target_lang,
                word=word,
                user_translation=translation,
            )
        except ContentGenerationError:
            _state_clear(context, "import_state")
            await message.reply_text(
                f"Импорт остановлен: LLM недоступен. Успешно импортировано: {imported}."
            )
            return

        word_id = await words_repo.create_word_bundle(
            user_id=user.id,
            pair_id=pair_id,
            set_id=None,
            content=generated,
            next_review_at=datetime.now(UTC),
        )
        tts_bytes = await tts_service.synthesize_word(generated.word, target_lang)
        if tts_bytes:
            file_id = await _upload_tts_and_get_file_id(
                context=context,
                chat_id=message.chat_id,
                word=generated.word,
                audio_bytes=tts_bytes,
            )
            if file_id:
                await words_repo.update_tts_word_file_id(word_id=word_id, file_id=file_id)
        imported += 1

        if processed % 5 == 0:
            await message.reply_text(f"Импорт: {processed} обработано...")

    _state_clear(context, "import_state")
    tail = ""
    if limit_reached:
        tail = f"\nДостигнут лимит {MAX_IMPORT_ROWS} строк за один импорт."
    await message.reply_text(
        f"Импорт завершен. Добавлено: {imported}. Пропущено: {skipped}.{tail}"
    )
