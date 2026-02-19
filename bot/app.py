from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import Settings
from bot.db.pool import DatabasePool
from bot.db.repositories.cards import CardsRepository
from bot.db.repositories.language_pairs import LanguagePairsRepository
from bot.db.repositories.reviews import ReviewsRepository
from bot.db.repositories.sets import VocabularySetsRepository
from bot.db.repositories.users import UsersRepository
from bot.db.repositories.words import WordsRepository
from bot.domain.srs import SRSService
from bot.domain.validation import AnswerValidationService
from bot.handlers.basic import (
    PAIR_CREATE_PATTERN,
    PAIR_SOURCE_PATTERN,
    PAIR_SWITCH_PATTERN,
    PAIR_TARGET_PATTERN,
    START_SOURCE_PATTERN,
    START_TARGET_PATTERN,
    cancel_command,
    help_command,
    pair_command,
    pair_create_callback,
    pair_source_callback,
    pair_switch_callback,
    pair_target_callback,
    start_command,
    start_source_callback,
    start_target_callback,
)
from bot.handlers.guard import active_pair_command_guard
from bot.handlers.workflows import (
    ADD_CANCEL,
    ADD_SAVE,
    ADD_SET_EXISTING_PREFIX,
    ADD_SET_NEW,
    ADD_SET_SKIP,
    DUELIST_PAGE_PREFIX,
    EDIT_CANCEL,
    EDIT_EXAMPLES,
    EDIT_NOTE,
    EDIT_TRANSLATION,
    LIST_PAGE_PREFIX,
    SETS_CLEAR,
    SETS_CREATE,
    SETS_SELECT_PREFIX,
    TRAIN_SKIP,
    TRAIN_TTS,
    add_callback_handler,
    add_command,
    delete_command,
    due_command,
    duelist_callback_handler,
    duelist_command,
    edit_callback_handler,
    edit_command,
    export_command,
    full_command,
    import_command,
    import_document_handler,
    list_callback_handler,
    list_command,
    reminders_command,
    sets_callback_handler,
    sets_command,
    stateful_text_router,
    stats_command,
    train_callback_handler,
    train_command,
)
from bot.runtime_keys import (
    CARDS_REPO_KEY,
    CONTENT_SERVICE_KEY,
    DB_POOL_KEY,
    LANGUAGE_PAIRS_REPO_KEY,
    REMINDER_SERVICE_KEY,
    REVIEWS_REPO_KEY,
    SETS_REPO_KEY,
    SRS_SERVICE_KEY,
    TTS_SERVICE_KEY,
    USERS_REPO_KEY,
    VALIDATION_SERVICE_KEY,
    WORDS_REPO_KEY,
)
from bot.services.content_generation import OpenAIContentGenerator
from bot.services.reminders import ReminderService
from bot.services.tts import GTTSService

logger = logging.getLogger(__name__)


def create_application(settings: Settings) -> Application:
    db_pool = DatabasePool(settings.database_url)
    users_repo = UsersRepository(db_pool.pool)
    pairs_repo = LanguagePairsRepository(db_pool.pool)
    words_repo = WordsRepository(db_pool.pool)
    cards_repo = CardsRepository(db_pool.pool)
    reviews_repo = ReviewsRepository(db_pool.pool)
    sets_repo = VocabularySetsRepository(db_pool.pool)
    srs_service = SRSService()
    validation_service = AnswerValidationService()
    content_service = OpenAIContentGenerator(api_key=settings.openai_api_key)
    tts_service = GTTSService(enabled=True)
    reminder_service = ReminderService(
        users_repo=users_repo,
        cards_repo=cards_repo,
        default_timezone=settings.default_timezone,
    )

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.bot_data[DB_POOL_KEY] = db_pool
    app.bot_data[USERS_REPO_KEY] = users_repo
    app.bot_data[LANGUAGE_PAIRS_REPO_KEY] = pairs_repo
    app.bot_data[WORDS_REPO_KEY] = words_repo
    app.bot_data[CARDS_REPO_KEY] = cards_repo
    app.bot_data[REVIEWS_REPO_KEY] = reviews_repo
    app.bot_data[SETS_REPO_KEY] = sets_repo
    app.bot_data[SRS_SERVICE_KEY] = srs_service
    app.bot_data[VALIDATION_SERVICE_KEY] = validation_service
    app.bot_data[CONTENT_SERVICE_KEY] = content_service
    app.bot_data[TTS_SERVICE_KEY] = tts_service
    app.bot_data[REMINDER_SERVICE_KEY] = reminder_service

    app.add_handler(MessageHandler(filters.COMMAND, active_pair_command_guard), group=-100)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("pair", pair_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("train", train_command))
    app.add_handler(CommandHandler("due", due_command))
    app.add_handler(CommandHandler("duelist", duelist_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("edit", edit_command))
    app.add_handler(CommandHandler("import", import_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("sets", sets_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("full", full_command))

    app.add_handler(CallbackQueryHandler(start_source_callback, pattern=START_SOURCE_PATTERN))
    app.add_handler(CallbackQueryHandler(start_target_callback, pattern=START_TARGET_PATTERN))
    app.add_handler(CallbackQueryHandler(pair_switch_callback, pattern=PAIR_SWITCH_PATTERN))
    app.add_handler(CallbackQueryHandler(pair_create_callback, pattern=PAIR_CREATE_PATTERN))
    app.add_handler(CallbackQueryHandler(pair_source_callback, pattern=PAIR_SOURCE_PATTERN))
    app.add_handler(CallbackQueryHandler(pair_target_callback, pattern=PAIR_TARGET_PATTERN))
    app.add_handler(
        CallbackQueryHandler(
            add_callback_handler,
            pattern=rf"^({ADD_SET_SKIP}|{ADD_SET_NEW}|{ADD_SET_EXISTING_PREFIX}\d+|{ADD_SAVE}|{ADD_CANCEL})$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            train_callback_handler,
            pattern=rf"^({TRAIN_TTS}|{TRAIN_SKIP})$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(list_callback_handler, pattern=rf"^{LIST_PAGE_PREFIX}\d+$")
    )
    app.add_handler(
        CallbackQueryHandler(
            duelist_callback_handler,
            pattern=rf"^{DUELIST_PAGE_PREFIX}\d+$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            sets_callback_handler,
            pattern=rf"^({SETS_CLEAR}|{SETS_CREATE}|{SETS_SELECT_PREFIX}\d+)$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            edit_callback_handler,
            pattern=rf"^({EDIT_TRANSLATION}|{EDIT_EXAMPLES}|{EDIT_NOTE}|{EDIT_CANCEL})$",
        )
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, stateful_text_router),
        group=100,
    )
    app.add_handler(
        MessageHandler(filters.Document.ALL, import_document_handler),
        group=100,
    )

    app.add_error_handler(_error_handler)
    return app


async def _post_init(app: Application) -> None:
    db_pool: DatabasePool = app.bot_data[DB_POOL_KEY]
    await db_pool.open()
    logger.info("Database connection pool opened.")
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Первый запуск и выбор языковой пары"),
            BotCommand("pair", "Сменить активную языковую пару"),
            BotCommand("add", "Добавить новое слово"),
            BotCommand("train", "Начать тренировку"),
            BotCommand("due", "Показать количество карточек к повторению"),
            BotCommand("duelist", "Список карточек к повторению"),
            BotCommand("list", "Список слов"),
            BotCommand("delete", "Удалить слово"),
            BotCommand("edit", "Редактировать слово"),
            BotCommand("import", "Импорт слов из CSV"),
            BotCommand("export", "Экспорт слов в CSV"),
            BotCommand("sets", "Управление тематическими наборами"),
            BotCommand("reminders", "Включить/выключить напоминания"),
            BotCommand("stats", "Статистика по текущей паре"),
            BotCommand("full", "Полная карточка на 4 языках для последнего слова"),
            BotCommand("cancel", "Отменить текущую операцию"),
            BotCommand("help", "Показать список команд"),
        ]
    )
    logger.info("Telegram command menu registered.")
    if app.job_queue:
        app.job_queue.run_repeating(
            _daily_reminder_job,
            interval=900,
            first=30,
            name="daily-reminders",
        )
        app.job_queue.run_repeating(
            _intraday_reminder_job,
            interval=600,
            first=45,
            name="intraday-reminders",
        )
        logger.info("Reminder jobs scheduled.")


async def _post_shutdown(app: Application) -> None:
    db_pool: DatabasePool = app.bot_data[DB_POOL_KEY]
    await db_pool.close()
    logger.info("Database connection pool closed.")


async def _error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:  # pragma: no cover - framework callback
    logger.exception("Unhandled telegram error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Произошла ошибка. Попробуйте позже."
        )


async def _daily_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    reminder_service: ReminderService = context.application.bot_data[REMINDER_SERVICE_KEY]
    await reminder_service.run_daily(context.application)


async def _intraday_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    reminder_service: ReminderService = context.application.bot_data[REMINDER_SERVICE_KEY]
    await reminder_service.run_intraday(context.application)
