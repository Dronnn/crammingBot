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

        expected_values = set(self._expand_expected_values(expected))
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

        if answer_candidates & expected_candidates:
            return True

        normalized_answer = normalize_text(answer)
        return _can_compose_from_expected_alternatives(
            answer=normalized_answer,
            alternatives=expected_candidates,
        )

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

    @staticmethod
    def _expand_expected_values(value: str) -> set[str]:
        normalized_value = normalize_text(value)
        if not normalized_value:
            return set()
        parts = [_alt.strip() for _alt in _ALT_SEPARATORS_RE.split(value) if _alt.strip()]
        normalized_parts = {normalize_text(part) for part in parts if normalize_text(part)}
        if normalized_parts:
            return normalized_parts
        return {normalized_value}


_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")
_ALT_SEPARATORS_RE = re.compile(r"(?:\s+или\s+|\s+or\s+|\s+oder\s+|[;,./|])+",
                                re.IGNORECASE)


def _synonym_base(value: str) -> str:
    return _TRAILING_PARENS_RE.sub("", value).strip()


def _can_compose_from_expected_alternatives(
    *,
    answer: str,
    alternatives: set[str],
) -> bool:
    answer_words = answer.split()
    if not answer_words:
        return False
    alternative_words = [alt.split() for alt in alternatives if alt]
    if not alternative_words:
        return False

    max_index = len(answer_words)
    dp = [False] * (max_index + 1)
    dp[0] = True
    for index in range(max_index):
        if not dp[index]:
            continue
        for alt_words in alternative_words:
            end = index + len(alt_words)
            if end > max_index:
                continue
            if answer_words[index:end] == alt_words:
                dp[end] = True
    return dp[max_index]
