from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from bot.domain.content import ExampleContent, GeneratedWordContent
from bot.domain.models import LanguageCode

logger = logging.getLogger(__name__)


class ContentGenerationError(RuntimeError):
    """Raised when OpenAI content generation fails."""


@dataclass(frozen=True, slots=True)
class OpenAIContentGenerator:
    api_key: str
    model: str = "gpt-5.2-pro"
    fallback_models: tuple[str, ...] = ("gpt-4o",)
    timeout_seconds: int = 60

    async def generate(
        self,
        *,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        word: str,
        user_translation: str | None,
    ) -> GeneratedWordContent:
        return await asyncio.to_thread(
            self._generate_sync,
            source_lang,
            target_lang,
            word,
            user_translation,
        )

    async def regenerate_synonyms(
        self,
        *,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        word: str,
        translation: str,
    ) -> tuple[str, ...]:
        return await asyncio.to_thread(
            self._regenerate_synonyms_sync,
            source_lang,
            target_lang,
            word,
            translation,
        )

    async def build_multilingual_snapshot(
        self,
        *,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        word: str,
        translation: str,
        synonyms: tuple[str, ...],
        examples: tuple[dict[str, str], ...],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._build_multilingual_snapshot_sync,
            source_lang,
            target_lang,
            word,
            translation,
            synonyms,
            examples,
        )

    def _generate_sync(
        self,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        word: str,
        user_translation: str | None,
    ) -> GeneratedWordContent:
        schema_instructions = {
            "word": "word on target language",
            "translation": "main translation on source language",
            "synonyms": (
                "array of target-language synonyms with SOURCE-language translation in parentheses, "
                "e.g. 'schnell (fast)' when source language is EN"
            ),
            "part_of_speech": "part of speech or null",
            "gender": "for German target language: der/die/das else null",
            "declension": "for German target language: object with nominativ/akkusativ/dativ/genitiv else null",
            "transcription": "optional transcription or null",
            "examples": [
                {
                    "target_sentence": "sentence on target language",
                    "source_translation": "translation of the same sentence on source language",
                }
            ],
        }
        user_translation_text = user_translation if user_translation else "-"
        payload = {
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a linguistics assistant for a Telegram SRS vocabulary trainer. "
                        "Return strict JSON only without markdown. "
                        "Generate simple and accurate B1-level examples."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source language: {source_lang}\n"
                        f"Target language: {target_lang}\n"
                        f"Target word: {word}\n"
                        f"Provided translation on source language: {user_translation_text}\n"
                        "If translation is '-', generate it automatically.\n"
                        "Generate 2-3 examples.\n"
                        "Each example must contain only TWO aligned texts: "
                        "target_sentence and source_translation of the same sentence.\n"
                        "Synonyms must be on TARGET language and each must include SOURCE-language translation in parentheses.\n"
                        "For German target language include article and declension.\n"
                        f"Schema: {json.dumps(schema_instructions, ensure_ascii=False)}"
                    ),
                },
            ],
        }
        data = self._chat_completion_with_fallback(payload)
        return _parse_generated_word_content(
            data,
            source_lang=source_lang,
            target_lang=target_lang,
        )

    def _regenerate_synonyms_sync(
        self,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        word: str,
        translation: str,
    ) -> tuple[str, ...]:
        payload = {
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return strict JSON only. "
                        "Produce synonyms of the TARGET word in TARGET language with SOURCE-language translation in parentheses."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source language: {source_lang}\n"
                        f"Target language: {target_lang}\n"
                        f"Target word: {word}\n"
                        f"Translation on source language: {translation}\n"
                        "Return JSON: {\"synonyms\": [\"target synonym (source-language translation)\"]}"
                    ),
                },
            ],
        }
        data = self._chat_completion_with_fallback(payload)
        synonyms_raw = data.get("synonyms", [])
        if not isinstance(synonyms_raw, list):
            raise ContentGenerationError("Invalid synonyms payload")
        cleaned: list[str] = []
        seen_base: set[str] = set()
        for item in synonyms_raw:
            text = str(item).strip()
            if not text:
                continue
            base = _synonym_base(text).lower()
            if not base or base == word.lower() or base in seen_base:
                continue
            seen_base.add(base)
            cleaned.append(text)
        return tuple(cleaned)

    def _build_multilingual_snapshot_sync(
        self,
        source_lang: LanguageCode,
        target_lang: LanguageCode,
        word: str,
        translation: str,
        synonyms: tuple[str, ...],
        examples: tuple[dict[str, str], ...],
    ) -> dict[str, Any]:
        payload = {
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return strict JSON only. "
                        "Build multilingual card data for RU/EN/DE/HY."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source language: {source_lang}\n"
                        f"Target language: {target_lang}\n"
                        f"Target word: {word}\n"
                        f"Translation on source language: {translation}\n"
                        f"Target-language synonyms: {json.dumps(list(synonyms), ensure_ascii=False)}\n"
                        f"Examples: {json.dumps(list(examples), ensure_ascii=False)}\n"
                        "Rules:\n"
                        "1) Keep meaning aligned.\n"
                        "2) For each synonym provide translations to RU/EN/DE/HY.\n"
                        "3) For each example provide the same sentence in RU/EN/DE/HY.\n"
                        "4) Keep output concise.\n"
                        "Return JSON schema:\n"
                        "{\n"
                        "  \"word\": {\"RU\": \"\", \"EN\": \"\", \"DE\": \"\", \"HY\": \"\"},\n"
                        "  \"synonyms\": [\n"
                        "    {\"target\": \"\", \"RU\": \"\", \"EN\": \"\", \"DE\": \"\", \"HY\": \"\"}\n"
                        "  ],\n"
                        "  \"examples\": [\n"
                        "    {\"RU\": \"\", \"EN\": \"\", \"DE\": \"\", \"HY\": \"\"}\n"
                        "  ]\n"
                        "}\n"
                    ),
                },
            ],
        }
        data = self._chat_completion_with_fallback(payload)
        return _parse_multilingual_snapshot(data)

    def _chat_completion_with_fallback(self, payload: dict) -> dict:
        models: list[str] = []
        for candidate in (self.model, *self.fallback_models):
            name = candidate.strip()
            if name and name not in models:
                models.append(name)
        if not models:
            raise ContentGenerationError("No OpenAI model configured")

        last_error: ContentGenerationError | None = None
        for index, model_name in enumerate(models):
            request_payload = dict(payload)
            request_payload["model"] = model_name
            try:
                if _uses_responses_endpoint(model_name):
                    data = self._responses_completion_sync(request_payload)
                else:
                    data = self._chat_completion_sync(request_payload)
            except ContentGenerationError as exc:
                last_error = exc
                if _is_model_access_error(str(exc)) and index < (len(models) - 1):
                    logger.warning(
                        "OpenAI model '%s' unavailable, trying fallback model '%s'",
                        model_name,
                        models[index + 1],
                    )
                    continue
                raise
            if index > 0:
                logger.warning(
                    "OpenAI fallback model '%s' is being used",
                    model_name,
                )
            return data

        raise last_error or ContentGenerationError("OpenAI request failed")

    def _responses_completion_sync(self, payload: dict) -> dict:
        model_name = str(payload.get("model", "")).strip()
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise ContentGenerationError("Invalid Responses payload: messages missing")

        input_items: list[dict[str, str]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user")
            content = str(item.get("content") or "").strip()
            if content:
                input_items.append({"role": role, "content": content})
        if not input_items:
            raise ContentGenerationError("Invalid Responses payload: empty messages")

        body_payload: dict[str, object] = {
            "model": model_name,
            "input": input_items,
            "text": {"format": {"type": "json_object"}},
        }

        body = json.dumps(body_payload).encode("utf-8")
        req = request.Request(
            url="https://api.openai.com/v1/responses",
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=body,
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.exception("OpenAI HTTP error (responses): %s", exc.code)
            raise ContentGenerationError(f"OpenAI HTTP error {exc.code}: {detail}") from exc
        except Exception as exc:
            logger.exception("OpenAI responses request failed")
            raise ContentGenerationError("OpenAI request failed") from exc

        try:
            parsed = json.loads(raw)
            text = parsed.get("output_text")
            if not text:
                text = _extract_responses_output_text(parsed)
            if not text:
                raise ValueError("missing output text")
            return json.loads(text)
        except Exception as exc:
            logger.exception("Failed to parse OpenAI responses payload")
            raise ContentGenerationError("OpenAI response parsing failed") from exc

    def _chat_completion_sync(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url="https://api.openai.com/v1/chat/completions",
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=body,
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.exception("OpenAI HTTP error: %s", exc.code)
            raise ContentGenerationError(f"OpenAI HTTP error {exc.code}: {detail}") from exc
        except Exception as exc:
            logger.exception("OpenAI request failed")
            raise ContentGenerationError("OpenAI request failed") from exc

        try:
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as exc:
            logger.exception("Failed to parse OpenAI response payload")
            raise ContentGenerationError("OpenAI response parsing failed") from exc


def _uses_responses_endpoint(model_name: str) -> bool:
    normalized = model_name.strip().lower()
    return normalized.startswith("gpt-5")


def _extract_responses_output_text(payload: dict) -> str | None:
    output = payload.get("output")
    if not isinstance(output, list):
        return None
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    if not chunks:
        return None
    return "\n".join(chunks)


def _is_model_access_error(message: str) -> bool:
    text = message.lower()
    return (
        "model_not_found" in text
        or "does not have access to model" in text
        or "unknown model" in text
        or "not a chat model" in text
        or "not supported in the v1/chat/completions endpoint" in text
    )


def _parse_generated_word_content(
    payload: dict,
    *,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
) -> GeneratedWordContent:
    try:
        word = str(payload["word"]).strip()
        translation = str(payload["translation"]).strip()
    except Exception as exc:
        raise ContentGenerationError("Invalid LLM payload: missing word/translation") from exc

    if not word or not translation:
        raise ContentGenerationError("Invalid LLM payload: empty word/translation")

    examples_raw = payload.get("examples", [])
    if not isinstance(examples_raw, list) or len(examples_raw) < 2:
        raise ContentGenerationError("Invalid LLM payload: expected at least 2 examples")

    examples: list[ExampleContent] = []
    for item in examples_raw[:3]:
        try:
            source_translation = _extract_source_translation(
                item=item,
                source_lang=source_lang,
            )
            target_sentence = _extract_target_sentence(
                item=item,
                target_lang=target_lang,
            )
            if not target_sentence or not source_translation:
                raise ValueError("empty source/target example")
            lang_values = {"RU": "", "DE": "", "EN": "", "HY": ""}
            lang_values[source_lang] = source_translation
            lang_values[target_lang] = target_sentence
            examples.append(
                ExampleContent(
                    sentence=target_sentence,
                    translation_ru=lang_values["RU"],
                    translation_de=lang_values["DE"],
                    translation_en=lang_values["EN"],
                    translation_hy=lang_values["HY"],
                )
            )
        except Exception as exc:
            raise ContentGenerationError("Invalid LLM payload: malformed example") from exc

    synonyms_raw = payload.get("synonyms", [])
    if isinstance(synonyms_raw, list):
        cleaned: list[str] = []
        seen_base: set[str] = set()
        for item in synonyms_raw:
            text = str(item).strip()
            if not text:
                continue
            base = _synonym_base(text).lower()
            if not base or base == word.lower() or base in seen_base:
                continue
            seen_base.add(base)
            cleaned.append(text)
        synonyms = tuple(cleaned)
    else:
        synonyms = ()

    part_of_speech = _safe_optional_text(payload.get("part_of_speech"))
    gender = _safe_optional_text(payload.get("gender"))
    transcription = _safe_optional_text(payload.get("transcription"))

    declension_raw = payload.get("declension")
    declension: dict[str, str] | None = None
    if isinstance(declension_raw, dict):
        declension = {
            str(key): str(value).strip()
            for key, value in declension_raw.items()
            if str(value).strip()
        }
        if not declension:
            declension = None

    return GeneratedWordContent(
        word=word,
        translation=translation,
        synonyms=synonyms,
        part_of_speech=part_of_speech,
        gender=gender,
        declension=declension,
        transcription=transcription,
        examples=tuple(examples),
    )


def _safe_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_source_translation(*, item: object, source_lang: LanguageCode) -> str:
    if not isinstance(item, dict):
        return ""
    source_key = f"translation_{source_lang.lower()}"
    candidates = (
        item.get("source_translation"),
        item.get("translation_source"),
        item.get(source_key),
    )
    for candidate in candidates:
        text = str(candidate).strip() if candidate is not None else ""
        if text:
            return text
    return ""


def _extract_target_sentence(*, item: object, target_lang: LanguageCode) -> str:
    if not isinstance(item, dict):
        return ""
    target_key = f"translation_{target_lang.lower()}"
    candidates = (
        item.get("target_sentence"),
        item.get("sentence"),
        item.get(target_key),
    )
    for candidate in candidates:
        text = str(candidate).strip() if candidate is not None else ""
        if text:
            return text
    return ""


def _synonym_base(value: str) -> str:
    text = value.strip()
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    return text


def _parse_multilingual_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    word_payload = payload.get("word")
    if not isinstance(word_payload, dict):
        raise ContentGenerationError("Invalid multilingual payload: missing word map")
    word_map = {
        code: str(word_payload.get(code, "")).strip()
        for code in ("RU", "EN", "DE", "HY")
    }

    synonyms: list[dict[str, str]] = []
    synonyms_raw = payload.get("synonyms", [])
    if isinstance(synonyms_raw, list):
        for item in synonyms_raw:
            if not isinstance(item, dict):
                continue
            entry = {
                "target": str(item.get("target", "")).strip(),
                "RU": str(item.get("RU", "")).strip(),
                "EN": str(item.get("EN", "")).strip(),
                "DE": str(item.get("DE", "")).strip(),
                "HY": str(item.get("HY", "")).strip(),
            }
            if any(entry.values()):
                synonyms.append(entry)

    examples: list[dict[str, str]] = []
    examples_raw = payload.get("examples", [])
    if isinstance(examples_raw, list):
        for item in examples_raw:
            if not isinstance(item, dict):
                continue
            entry = {
                "RU": str(item.get("RU", "")).strip(),
                "EN": str(item.get("EN", "")).strip(),
                "DE": str(item.get("DE", "")).strip(),
                "HY": str(item.get("HY", "")).strip(),
            }
            if any(entry.values()):
                examples.append(entry)

    return {
        "word": word_map,
        "synonyms": synonyms,
        "examples": examples,
    }
