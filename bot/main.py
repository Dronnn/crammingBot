from __future__ import annotations

import argparse
import logging

from telegram import Update

from bot.app import create_application
from bot.config import ConfigError, load_settings
from bot.db.migrate import apply_migrations
from bot.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Vocabulary trainer bot")
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Apply SQL migrations before starting bot.",
    )
    args = parser.parse_args()

    try:
        settings = load_settings()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc

    configure_logging(settings.log_level)
    logger.info("Loaded configuration: %s", settings.safe_log_values())
    if args.migrate:
        apply_migrations(settings.database_url)
        logger.info("Migrations applied.")

    application = create_application(settings)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
