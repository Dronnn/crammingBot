from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_LANG_MAP = {
    "RU": "ru",
    "DE": "de",
    "EN": "en",
    "HY": "hy",
}


@dataclass(frozen=True, slots=True)
class GTTSService:
    enabled: bool = True

    async def synthesize_word(self, text: str, language_code: str) -> bytes | None:
        if not self.enabled:
            return None
        return await asyncio.to_thread(self._synthesize_sync, text, language_code)

    def _synthesize_sync(self, text: str, language_code: str) -> bytes | None:
        lang = _LANG_MAP.get(language_code)
        if not lang:
            return None
        try:
            from gtts import gTTS  # Imported lazily so bot can run when gTTS is absent.
        except Exception:
            logger.warning("gTTS is unavailable. TTS disabled.")
            return None

        try:
            buf = io.BytesIO()
            tts = gTTS(text=text, lang=lang)
            tts.write_to_fp(buf)
            return buf.getvalue()
        except Exception:
            logger.exception("gTTS generation failed")
            return None

