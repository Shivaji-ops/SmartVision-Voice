"""Making and caching the spoken version of a prompt."""
import threading
from collections import OrderedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import schemas
from .models import PromptAudio, VoicePrompt, utcnow
from .tts import SpeechUnavailable, Speaker


# The last few recordings made, so the audio a caregiver previews is the very audio that gets
# saved (speech can vary a little between two calls), and repeating a preview costs nothing.
_recent: "OrderedDict[tuple, bytes]" = OrderedDict()
_recent_lock = threading.Lock()
_RECENT_MAX = 32


def clear_recent() -> None:
    with _recent_lock:
        _recent.clear()


def speak_cached(speaker: Speaker, text: str, language: str) -> bytes:
    key = (speaker.voice, language, text.strip())
    with _recent_lock:
        if key in _recent:
            _recent.move_to_end(key)
            return _recent[key]
    wav = speaker.speak(text, language)
    with _recent_lock:
        _recent[key] = wav
        while len(_recent) > _RECENT_MAX:
            _recent.popitem(last=False)
    return wav


def current_audio(db: Session, prompt: VoicePrompt) -> PromptAudio | None:
    """The cached audio, only if it was made from the prompt's present wording."""
    row = db.scalar(select(PromptAudio).where(PromptAudio.prompt_id == prompt.id))
    if row and row.text == prompt.text and row.language == prompt.language:
        return row
    return None


def audio_for(db: Session, prompt: VoicePrompt, speaker: Speaker) -> PromptAudio:
    """Return audio for the prompt, making it when missing or out of date.

    If only the voice settings changed, a failure to remake keeps the earlier audio, so
    glasses that already work are not broken by a speech outage.
    """
    row = current_audio(db, prompt)
    if row and row.voice == speaker.voice:
        return row
    try:
        wav = speak_cached(speaker, prompt.text, prompt.language)
    except SpeechUnavailable:
        if row:
            return row
        raise
    row = db.scalar(select(PromptAudio).where(PromptAudio.prompt_id == prompt.id))
    if row is None:
        row = PromptAudio(prompt_id=prompt.id)
        db.add(row)
    row.text = prompt.text
    row.language = prompt.language
    row.voice = speaker.voice
    row.mime = "audio/wav"
    row.data = wav
    row.created_at = utcnow()
    db.commit()
    return row


def prompts_out(db: Session, prompts: list[VoicePrompt]) -> list[schemas.PromptOut]:
    """Prompts as the API returns them, each marked with whether its voice is ready."""
    ids = [p.id for p in prompts]
    made = {}
    if ids:
        rows = db.execute(
            select(PromptAudio.prompt_id, PromptAudio.text, PromptAudio.language).where(PromptAudio.prompt_id.in_(ids))
        ).all()
        made = {prompt_id: (text, language) for prompt_id, text, language in rows}
    out = []
    for p in prompts:
        item = schemas.PromptOut.model_validate(p)
        item.audio_ready = made.get(p.id) == (p.text, p.language)
        out.append(item)
    return out
