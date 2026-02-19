from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_GERMAN_ARTICLE_RE = re.compile(r"^(der|die|das)\s+", flags=re.IGNORECASE)


def normalize_text(text: str) -> str:
    normalized = text.strip().lower()
    normalized = _PUNCTUATION_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def strip_german_article(text: str) -> str:
    return _GERMAN_ARTICLE_RE.sub("", text, count=1).strip()


def german_variants(text: str) -> set[str]:
    base = normalize_text(text)
    if not base:
        return set()
    without_article = strip_german_article(base)
    if without_article:
        return {base, without_article}
    return {base}

