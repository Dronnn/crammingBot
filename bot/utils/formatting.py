from __future__ import annotations

from datetime import UTC, datetime

from bot.domain.models import ExampleRecord

_DECLENSION_DISPLAY_ORDER = ("nominativ", "akkusativ", "dativ", "genitiv")
_VERB_GOVERNANCE_KEYS = ("government", "governance", "regierung", "rektion", "управление")
_LANG_TO_TRANSLATION_FIELD = {
    "RU": "translation_ru",
    "DE": "translation_de",
    "EN": "translation_en",
    "HY": "translation_hy",
}


def format_declension(declension: dict[str, str] | None) -> str:
    if not declension:
        return ""
    values: list[tuple[str, str]] = []
    normalized = {str(key).strip().lower(): str(value).strip() for key, value in declension.items()}
    normalized = {
        key: value
        for key, value in normalized.items()
        if key not in _VERB_GOVERNANCE_KEYS
    }
    if not normalized:
        return ""
    for key in _DECLENSION_DISPLAY_ORDER:
        value = normalized.get(key, "")
        if value:
            values.append((key, value))
    for key, value in normalized.items():
        if key in _DECLENSION_DISPLAY_ORDER or not value:
            continue
        values.append((key, value))
    return ", ".join(f"{key}: {value}" for key, value in values)


def extract_verb_governance(declension: dict[str, str] | None) -> str | None:
    if not declension:
        return None
    normalized = {str(key).strip().lower(): str(value).strip() for key, value in declension.items()}
    for key in _VERB_GOVERNANCE_KEYS:
        value = normalized.get(key)
        if value:
            return value
    return None


def _translation_for_lang(example: ExampleRecord, language: str) -> str:
    field_name = _LANG_TO_TRANSLATION_FIELD.get(language)
    if field_name is None:
        return ""
    value = getattr(example, field_name, "")
    return value.strip() if isinstance(value, str) else ""


def format_examples(
    examples: tuple[ExampleRecord, ...],
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
) -> str:
    lines: list[str] = []
    for index, example in enumerate(examples, start=1):
        if source_lang and target_lang:
            target_text = example.sentence.strip() if example.sentence else ""
            source_text = _translation_for_lang(example, source_lang)
            lines.append(f"{index}.")
            if target_text:
                lines.append(f"   {target_lang}: {target_text}")
            if source_text:
                lines.append(f"   {source_lang}: {source_text}")
            continue
        lines.extend(
            [
                f"{index}. {example.sentence}",
                f"   RU: {example.translation_ru}",
                f"   DE: {example.translation_de}",
                f"   EN: {example.translation_en}",
                f"   HY: {example.translation_hy}",
            ]
        )
    return "\n".join(lines)


def format_overdue(next_review_at: datetime, now: datetime | None = None) -> str:
    reference = now or datetime.now(UTC)
    delta = reference - next_review_at.astimezone(UTC)
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return f"{seconds}с"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}м"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}ч"
    days = hours // 24
    return f"{days}д"


def format_next_review_delta(next_review_at: datetime, now: datetime | None = None) -> str:
    reference = now or datetime.now(UTC)
    delta = next_review_at.astimezone(UTC) - reference
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "меньше минуты"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} минут"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} часов"
    days = hours // 24
    return f"{days} дней"
