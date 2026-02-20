from bot.domain.normalization import german_variants, normalize_text, search_variants


def test_normalize_text_removes_punctuation_and_spaces() -> None:
    assert normalize_text("  Der,  Hund!  ") == "der hund"


def test_german_variants_include_articleless_form() -> None:
    variants = german_variants("Der Hund")
    assert variants == {"der hund", "hund"}


def test_search_variants_ignore_case_punctuation_and_article() -> None:
    variants = search_variants("Die Erinnerung.")
    assert "die erinnerung" in variants
    assert "dieerinnerung" in variants
    assert "erinnerung" in variants
