"""Voice notes -> text, on your own server (free, private).

Uses the open-source Whisper model through the `faster-whisper` package.
It's optional: install it with  pip install faster-whisper
The first voice note downloads the model (~150 MB for "base").
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
_model = None


def transcribe(path: Path, settings: dict[str, Any]) -> str:
    global _model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.warning("Voice note received but faster-whisper is not installed")
        return ""
    if _model is None:
        _model = WhisperModel(settings.get("model", "base"), device="cpu", compute_type="int8")
    segments, _info = _model.transcribe(str(path), vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()
