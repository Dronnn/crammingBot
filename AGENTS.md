# Project Rules: VocabTrAiBot

This file defines mandatory working rules for this repository and serves as a reusable baseline for similar bot projects.

## 1) Non-Negotiable Runtime Split

- This Mac (development machine) is for code/docs/git only.
- Do not run bot runtime, polling, webhook, background services, or deployment runtime here.
- Do not install project dependencies on this Mac.
- Runtime actions happen only on old Mac over SSH.

## 2) Old Mac Runtime Rules

- SSH host alias: `macbook-i7` (old Mac runtime host).
- Runtime project path: `~/apps/VocabTrAiBot`.
- Always use virtual environment: `~/apps/VocabTrAiBot/.venv`.
- Start command:
  - `.venv/bin/python -m bot.main`

## 3) Security Rules

- Secrets are stored only in env vars or local `.env`.
- Never commit real tokens/keys.
- Never print tokens/keys in logs or command output.
- Never commit full environment dumps.
- If any key is pasted in chat or exposed, rotate it.

## 4) Git Rules

- Never commit without explicit user request.
- Never push without explicit user request.
- Commit only safe files.
- For this repo:
  - `docs/` is local-only and must not be committed.
  - `telegram_bot_vocab_trainer_cramming_prompt.md` is local-only and must not be committed.

## 5) Session Start Checklist

At the beginning of each new session:

1. Read this file (`AGENTS.md`).
2. Check repo state:
   - `git status --short --branch`
3. Confirm runtime host connectivity (only if needed):
   - `ssh macbook-i7 'echo ok'`
4. Keep all runtime/test/deploy commands on old Mac only.

## 6) Deployment Checklist (Old Mac Only)

1. Sync code to old Mac (exclude secrets/venv/logs).
2. On old Mac:
   - `cd ~/apps/VocabTrAiBot`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
   - `pytest -q`
3. Restart bot process:
   - `pkill -f ' -m bot.main' || true`
   - `nohup .venv/bin/python -m bot.main >/dev/null 2>&1 < /dev/null &`
4. Verify:
   - `ps aux | grep '[b]ot.main'`
   - `tail -n 100 logs/bot.log`

## 7) Reuse For Similar Projects

To reuse this ruleset in another similar bot project:

1. Copy this file as `AGENTS.md` into the new repo root.
2. Update these fields only:
   - SSH alias
   - runtime project path
   - venv path
   - start command
   - secrets/env variable names
   - local-only (non-committed) files/folders

Keep the security and runtime-split principles unchanged.
