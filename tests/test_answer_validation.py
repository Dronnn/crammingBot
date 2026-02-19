from bot.domain.models import CardAnswerContext
from bot.domain.validation import AnswerValidationService


def test_validation_accepts_synonym() -> None:
    service = AnswerValidationService()
    assert service.is_correct(
        answer="собачка",
        expected="собака",
        synonyms=["пес", "собачка"],
        language_code="RU",
    )


def test_validation_accepts_german_without_article() -> None:
    service = AnswerValidationService()
    assert service.is_correct(
        answer="Hund",
        expected="der Hund",
        synonyms=[],
        language_code="DE",
    )


def test_validation_uses_card_direction() -> None:
    service = AnswerValidationService()
    context = CardAnswerContext(
        direction="forward",
        source_lang="RU",
        target_lang="DE",
        word="der Hund",
        translation="собака",
        synonyms=("hund",),
    )
    assert service.is_correct_for_card("Hund", context)


def test_validation_accepts_synonym_with_ru_hint() -> None:
    service = AnswerValidationService()
    context = CardAnswerContext(
        direction="forward",
        source_lang="RU",
        target_lang="DE",
        word="das Haus",
        translation="дом",
        synonyms=("Heim (дом)",),
    )
    assert service.is_correct_for_card("Heim", context)


def test_validation_ignores_target_synonyms_in_reverse_direction() -> None:
    service = AnswerValidationService()
    context = CardAnswerContext(
        direction="reverse",
        source_lang="RU",
        target_lang="DE",
        word="das Haus",
        translation="дом",
        synonyms=("Heim (дом)",),
    )
    assert not service.is_correct_for_card("Heim", context)


def test_validation_accepts_any_single_expected_variant_in_reverse() -> None:
    service = AnswerValidationService()
    context = CardAnswerContext(
        direction="reverse",
        source_lang="RU",
        target_lang="DE",
        word="die Frist",
        translation="срок, крайний срок",
        synonyms=(),
    )
    assert service.is_correct_for_card("срок", context)
    assert service.is_correct_for_card("крайний срок", context)


def test_validation_accepts_combined_expected_variants_with_any_separator() -> None:
    service = AnswerValidationService()
    context = CardAnswerContext(
        direction="reverse",
        source_lang="RU",
        target_lang="DE",
        word="die Frist",
        translation="срок; крайний срок",
        synonyms=(),
    )
    assert service.is_correct_for_card("срок, крайний срок", context)
    assert service.is_correct_for_card("срок; крайний срок", context)
    assert service.is_correct_for_card("срок крайний срок", context)
