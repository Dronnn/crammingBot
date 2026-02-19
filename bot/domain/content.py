from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExampleContent:
    sentence: str
    translation_ru: str
    translation_de: str
    translation_en: str
    translation_hy: str


@dataclass(frozen=True, slots=True)
class GeneratedWordContent:
    word: str
    translation: str
    synonyms: tuple[str, ...]
    part_of_speech: str | None
    gender: str | None
    declension: dict[str, str] | None
    transcription: str | None
    examples: tuple[ExampleContent, ...]

