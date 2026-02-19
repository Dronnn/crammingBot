from datetime import UTC, datetime, timedelta

from bot.domain.models import ExampleRecord
from bot.utils.formatting import format_declension, format_examples, format_overdue


def test_format_examples_renders_all_languages() -> None:
    text = format_examples(
        (
            ExampleRecord(
                sentence="Der Hund spielt.",
                translation_ru="Собака играет.",
                translation_de="Der Hund spielt.",
                translation_en="The dog is playing.",
                translation_hy="Շունը խաղում է։",
            ),
        )
    )
    assert "RU:" in text
    assert "DE:" in text
    assert "EN:" in text
    assert "HY:" in text


def test_format_examples_renders_pair_only() -> None:
    text = format_examples(
        (
            ExampleRecord(
                sentence="Der Hund spielt.",
                translation_ru="Собака играет.",
                translation_de="Der Hund spielt.",
                translation_en="",
                translation_hy="",
            ),
        ),
        source_lang="RU",
        target_lang="DE",
    )
    assert "DE: Der Hund spielt." in text
    assert "RU: Собака играет." in text
    assert "EN:" not in text
    assert "HY:" not in text


def test_format_declension_uses_required_order() -> None:
    value = format_declension(
        {
            "genitiv": "des Hauses",
            "dativ": "dem Haus",
            "nominativ": "das Haus",
            "akkusativ": "das Haus",
        }
    )
    assert value == "nominativ: das Haus, akkusativ: das Haus, dativ: dem Haus, genitiv: des Hauses"


def test_format_overdue_minutes() -> None:
    now = datetime.now(UTC)
    value = format_overdue(now - timedelta(minutes=7), now=now)
    assert value == "7м"
