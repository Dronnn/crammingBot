from __future__ import annotations

import re
from typing import Iterable

from bot.domain.models import CardAnswerContext
from bot.domain.normalization import german_variants, normalize_text


class AnswerValidationService:
    def is_correct(
        self,
        answer: str,
        expected: str,
        synonyms: Iterable[str] | None = None,
        language_code: str | None = None,
    ) -> bool:
        if not answer:
            return False

        expected_values = {normalize_text(expected)}
        if synonyms:
            expected_values.update(
                normalize_text(_synonym_base(item)) for item in synonyms if item
            )
        expected_values.discard("")

        if not expected_values:
            return False

        answer_candidates = self._variants(answer, language_code)
        expected_candidates: set[str] = set()
        for value in expected_values:
            expected_candidates.update(self._variants(value, language_code))

        return bool(answer_candidates & expected_candidates)

    def is_correct_for_card(self, answer: str, context: CardAnswerContext) -> bool:
        expected = context.word if context.direction == "forward" else context.translation
        compare_language = (
            context.target_lang if context.direction == "forward" else context.source_lang
        )
        synonyms: Iterable[str] | None = context.synonyms if context.direction == "forward" else None
        return self.is_correct(
            answer=answer,
            expected=expected,
            synonyms=synonyms,
            language_code=compare_language,
        )

    @staticmethod
    def _variants(value: str, language_code: str | None) -> set[str]:
        if language_code == "DE":
            return german_variants(value)
        normalized = normalize_text(value)
        return {normalized} if normalized else set()


_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _synonym_base(value: str) -> str:
    return _TRAILING_PARENS_RE.sub("", value).strip()
