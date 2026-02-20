# Cramming Bot

Telegram vocabulary trainer bot with:

- language-pair scoped vocabulary
- bidirectional cards (`forward` + `reverse`)
- spaced repetition (SRS)
- strict cramming retry (must type correct answer after a mistake)
- reminders
- CSV import/export
- PostgreSQL persistence

## Runtime Split (Mandatory)

- New Mac (this repository workspace): code, docs, git only.
- Old Mac (`macbook-i7`): dependency install, tests, runtime, deploy.

Do not run runtime/test/deploy/install flows on this new Mac.

## Tech Stack

- Python 3.12
- `python-telegram-bot` (async API + job queue)
- PostgreSQL (`psycopg`, `psycopg_pool`)
- OpenAI API for generation
- gTTS for optional TTS

## Project Layout

- `bot/main.py`: app entrypoint
- `bot/app.py`: handler wiring and scheduler setup
- `bot/handlers/`: Telegram command and callback handlers
- `bot/services/`: OpenAI content, TTS, reminders
- `bot/db/repositories/`: persistence layer
- `migrations/`: SQL schema
- `docs/`: architecture/commands/deploy notes (local-only in this repo)

## Environment Variables

Create `.env` from `.env.example` on runtime host:

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `DATABASE_URL`
- `LOG_LEVEL` (optional, default `INFO`)
- `DEFAULT_TIMEZONE` (optional, default `UTC+3`)

## Runtime Commands (Old Mac Only)

### Venv runtime

```bash
.venv/bin/python -m bot.main --migrate
```

### Docker runtime

```bash
docker compose build
docker compose up -d
```

## Old Mac Deploy Checklist

Run from new Mac (code sync only):

```bash
rsync -az --delete \
  --exclude '.env' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'logs' \
  --exclude '.git' \
  --exclude 'docs' \
  ./ macbook-i7:~/apps/VocabTrAiBot/
```

Run on old Mac:

```bash
cd ~/apps/VocabTrAiBot
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
pkill -f ' -m bot.main' || true
nohup .venv/bin/python -m bot.main >/dev/null 2>&1 < /dev/null &
ps aux | grep '[b]ot.main'
tail -n 100 logs/bot.log
```

## Supported Commands

- `/start`
- `/pair`
- `/settings` (показать/применить настройки напоминаний шаблоном `key: value`)
- `/add`
- `/train`
- `/due`
- `/duelist`
- `/list`
- `/delete`
- `/edit`
- `/import`
- `/export`
- `/sets`
- `/reminders`
- `/stats`
- `/full` (полная карточка последнего слова на 4 языках; кэшируется в БД после первого запроса)
- `/help`
- `/cancel`

## Reminder Behavior

- Daily reminder: once per day at `daily_reminder_hour` in user timezone.
- Intraday reminder: repeats through the day if due cards remain and rate-limit allows.
- Reminder sends a mini-question in chat and waits for one answer.
- This mini-question does not start full `/train`.

### Mini-Question Example

Bot:

```text
Мини-повторение (без запуска /train).
[Направление: DE -> RU]

Слово: Frist

Переведите на Русский и отправьте ответ одним сообщением.
```

User:

```text
срок
```

Bot:

```text
Верно. Мини-повторение завершено.
```

## `/settings` Example

1. Send `/settings`.
2. Copy template message from bot.
3. Edit values and send it back in one message.

Template:

```text
timezone: +4
daily_reminder_hour: 10
intraday_min_due: 1
intraday_idle_hours: 2
intraday_interval_minutes: 180
quiet_hours_start: 22
quiet_hours_end: 9
```

## Notes

- Before pair selection, only `/start` is allowed.
- TTS is optional by design: if unavailable, bot keeps working without audio.
- During long LLM operations (`/add`, `/full`, synonym regeneration in `/edit`, import generation), bot shows a short "generating" status message.
- Newly added words become available for `/train` immediately.
- `/full` for the last studied word is generated once and then read from DB cache on next calls.
- CSV import safety limits: max `512 KB` file size and max `200` rows per import operation.
- Reminder delivery sends a mini-question directly in chat (without starting `/train`); the answer is checked in one message and applied to SRS.
- Reminder schedule is user-configurable via `/settings` (`timezone` as `+4/-2`, morning hour, intraday thresholds/interval, quiet hours).
- For reverse direction answers, multiple expected variants in translation (for example, comma/semicolon-separated) are accepted as:
  - any single valid variant
  - several valid variants together with or without punctuation separators
- Secrets must stay in `.env`; never commit real credentials.
