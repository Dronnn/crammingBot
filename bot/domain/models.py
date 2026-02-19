from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

LanguageCode = Literal["RU", "DE", "EN", "HY"]
CardDirection = Literal["forward", "reverse"]


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: int
    username: str | None
    first_name: str | None
    active_pair_id: int | None
    reminders_enabled: bool
    timezone: str


@dataclass(frozen=True, slots=True)
class LanguagePairRecord:
    id: int
    user_id: int
    source_lang: LanguageCode
    target_lang: LanguageCode
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CardAnswerContext:
    direction: CardDirection
    source_lang: LanguageCode
    target_lang: LanguageCode
    word: str
    translation: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExampleRecord:
    sentence: str
    translation_ru: str
    translation_de: str
    translation_en: str
    translation_hy: str
    tts_file_id: str | None = None
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class WordRecord:
    id: int
    user_id: int
    language_pair_id: int
    vocabulary_set_id: int | None
    word: str
    translation: str
    synonyms: tuple[str, ...]
    part_of_speech: str | None
    gender: str | None
    declension: dict[str, str] | None
    transcription: str | None
    note: str | None
    tts_word_file_id: str | None


@dataclass(frozen=True, slots=True)
class DueCardRecord:
    id: int
    user_id: int
    word_id: int
    language_pair_id: int
    direction: CardDirection
    srs_index: int
    next_review_at: datetime
    correct_count: int
    incorrect_count: int
    source_lang: LanguageCode
    target_lang: LanguageCode
    word: str
    translation: str
    synonyms: tuple[str, ...]
    gender: str | None
    declension: dict[str, str] | None
    tts_word_file_id: str | None
    examples: tuple[ExampleRecord, ...]


@dataclass(frozen=True, slots=True)
class VocabularySetRecord:
    id: int
    user_id: int
    language_pair_id: int
    name: str
