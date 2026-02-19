from bot.domain.normalization import german_variants, normalize_text


def test_normalize_text_removes_punctuation_and_spaces() -> None:
    assert normalize_text("  Der,  Hund!  ") == "der hund"


def test_german_variants_include_articleless_form() -> None:
    variants = german_variants("Der Hund")
    assert variants == {"der hund", "hund"}

