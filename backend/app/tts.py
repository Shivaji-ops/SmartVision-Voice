"""Text to speech for voice prompts.

The glasses play recorded audio, so the backend turns each saved prompt into a WAV file
and the glasses download it. Only the prompt text is sent to the speech service.
Error messages never include the key.
"""
import base64
import binascii
import logging
from typing import Optional, Protocol

import httpx

from .config import settings
from .translation import SARVAM_CODES

logger = logging.getLogger("smartvision")


class SpeechUnavailable(Exception):
    """Speech is not set up or could not be made. The message is safe to show to a caregiver."""


class Speaker(Protocol):
    # Identifies the voice settings, so audio made with other settings can be remade.
    voice: str

    def speak(self, text: str, language: str) -> bytes: ...


class UnconfiguredSpeaker:
    voice = "none"

    def __init__(self, reason: str = ""):
        self._reason = reason or (
            "Spoken prompts are not set up on this server. Add a Sarvam API key (SARVAM_API_KEY) to "
            "backend/.env (see the README)."
        )

    def speak(self, text: str, language: str) -> bytes:
        raise SpeechUnavailable(self._reason)


# Languages Sarvam's Bulbul voices speak. Urdu and the smaller languages are not among them.
SARVAM_TTS_LANGUAGES = {"en", "hi", "bn", "gu", "kn", "ml", "mr", "or", "od", "pa", "ta", "te"}
SARVAM_TTS_MAX_CHARS = 2500


class SarvamSpeaker:
    """Sarvam Bulbul (https://api.sarvam.ai/text-to-speech). Returns a mono 16-bit WAV."""

    def __init__(
        self,
        key: str,
        endpoint: str = "https://api.sarvam.ai",
        model: str = "bulbul:v3",
        speaker: str = "shubh",
        pace: float = 0.9,
        sample_rate: int = 16000,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 30.0,
    ):
        self._key = key
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._speaker = speaker
        self._pace = pace
        self._rate = sample_rate
        self._transport = transport
        self._timeout = timeout
        self.voice = f"sarvam:{model}:{speaker}:{pace}:{sample_rate}"

    def speak(self, text: str, language: str) -> bytes:
        lang = language.lower()
        code = SARVAM_CODES.get(lang) if lang in SARVAM_TTS_LANGUAGES else None
        if not code:
            raise SpeechUnavailable(f"Sarvam has no voice for '{language}' yet.")
        text = text.strip()
        if not text:
            raise SpeechUnavailable("There is no text to speak.")
        if len(text) > SARVAM_TTS_MAX_CHARS:
            raise SpeechUnavailable(f"The message is too long to speak. The limit is {SARVAM_TTS_MAX_CHARS} characters.")

        headers = {"api-subscription-key": self._key, "Content-Type": "application/json"}
        body = {
            "text": text,
            "language_code": code,
            "model": self._model,
            "speaker": self._speaker,
            "pace": self._pace,
            "speech_sample_rate": self._rate,
            "output_audio_codec": "wav",
        }
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(f"{self._endpoint}/text-to-speech", headers=headers, json=body)
        except httpx.HTTPError:
            raise SpeechUnavailable("Could not reach the speech service. Check the internet connection and try again.")

        if response.status_code != 200:
            # The reply is logged on the server only, to help find a wrong voice or model name.
            logger.warning("Sarvam text-to-speech returned %s: %.300s", response.status_code, response.text)
        if response.status_code in (401, 403):
            raise SpeechUnavailable(
                "Sarvam did not accept the key. Check SARVAM_API_KEY in backend/.env, and that the "
                "account still has credit."
            )
        if response.status_code == 429:
            raise SpeechUnavailable("The speech limit was reached. Try again later.")
        if response.status_code in (400, 422):
            raise SpeechUnavailable(
                "Sarvam could not make speech for this message. Check SARVAM_TTS_MODEL and "
                "SARVAM_TTS_SPEAKER in backend/.env."
            )
        if response.status_code != 200:
            raise SpeechUnavailable(f"The speech service returned an error ({response.status_code}).")

        try:
            encoded = response.json()["audios"][0]
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, KeyError, IndexError, TypeError, binascii.Error):
            raise SpeechUnavailable("The speech service sent an unexpected reply.")
        if not (audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"):
            raise SpeechUnavailable("The speech service sent audio in an unexpected format.")
        return audio


def build_speaker(cfg=settings) -> Speaker:
    """Pick the speech service from settings. Never raises: a mistake becomes a clear message later."""
    provider = cfg.speech_provider
    explicit = bool(provider)
    if not provider:
        provider = "sarvam" if cfg.sarvam_api_key else "none"

    if provider == "none":
        return UnconfiguredSpeaker()
    if provider == "sarvam":
        if not cfg.sarvam_api_key:
            return UnconfiguredSpeaker("SPEECH_PROVIDER is sarvam but SARVAM_API_KEY is empty in backend/.env.")
        return SarvamSpeaker(
            cfg.sarvam_api_key,
            cfg.sarvam_endpoint,
            cfg.sarvam_tts_model,
            cfg.sarvam_tts_speaker,
            cfg.sarvam_tts_pace,
            cfg.sarvam_tts_sample_rate,
        )
    return UnconfiguredSpeaker(
        f"SPEECH_PROVIDER '{provider}' is not recognised. Use sarvam or none in backend/.env." if explicit else ""
    )


_speaker: Speaker = build_speaker()


def set_speaker(speaker: Speaker) -> None:
    global _speaker
    _speaker = speaker


def get_speaker() -> Speaker:
    return _speaker
