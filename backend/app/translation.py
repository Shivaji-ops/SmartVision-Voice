"""Translation hook and the dose-safety rule.

Rule: free machine translation is allowed for ordinary prompts ("Good morning,
time for a walk"). It is never allowed for anything about taking medicine. Those
prompts must come from a fixed template that a fluent speaker and a pharmacist
have reviewed, and a template only counts once its `verified` flag is True.

Only English is marked verified below. Telugu, Hindi and other languages are
deliberately absent: add each one only after that review, not before.
"""
from typing import Optional, Protocol

import httpx

from .config import settings


class TranslationUnavailable(Exception):
    """No translation backend is configured or reachable. The message is safe to show to a caregiver."""


class Translator(Protocol):
    def translate(self, text: str, source: str, target: str) -> str: ...


class UnconfiguredTranslator:
    """Used when no translator key is set.

    It refuses rather than returning the English text unchanged, so a Telugu
    patient never silently hears English labelled as Telugu.
    """

    def __init__(self, reason: str = ""):
        self._reason = reason or (
            "Translation is not set up on this server. Add a Sarvam API key (SARVAM_API_KEY) to "
            "backend/.env (see the README), or write the prompt directly in the wearer's language."
        )

    def translate(self, text: str, source: str, target: str) -> str:
        raise TranslationUnavailable(self._reason)


# Our language codes are two-letter ISO ones. Sarvam wants BCP-47 with a region.
SARVAM_CODES = {
    "en": "en-IN", "hi": "hi-IN", "bn": "bn-IN", "gu": "gu-IN", "kn": "kn-IN", "ml": "ml-IN",
    "mr": "mr-IN", "or": "od-IN", "od": "od-IN", "pa": "pa-IN", "ta": "ta-IN", "te": "te-IN",
    "ur": "ur-IN", "as": "as-IN", "brx": "brx-IN", "doi": "doi-IN", "kok": "kok-IN",
    "gom": "kok-IN", "ks": "ks-IN", "mai": "mai-IN", "mni": "mni-IN", "ne": "ne-IN",
    "sa": "sa-IN", "sat": "sat-IN", "sd": "sd-IN",
}
SARVAM_MAX_CHARS = 2000


class SarvamTranslator:
    """Sarvam Translate (https://api.sarvam.ai/translate).

    Only the prompt text is sent. Medicine prompts never come here: they use the
    reviewed templates below. Error messages never include the key.
    """

    def __init__(
        self,
        key: str,
        endpoint: str = "https://api.sarvam.ai",
        model: str = "sarvam-translate:v1",
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 15.0,
    ):
        self._key = key
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._transport = transport
        self._timeout = timeout

    def translate(self, text: str, source: str, target: str) -> str:
        src, tgt = SARVAM_CODES.get(source.lower()), SARVAM_CODES.get(target.lower())
        if not src or not tgt:
            raise TranslationUnavailable(f"Sarvam cannot translate between '{source}' and '{target}'.")
        if len(text) > SARVAM_MAX_CHARS:
            raise TranslationUnavailable(
                f"The message is too long to translate. The limit is {SARVAM_MAX_CHARS} characters."
            )
        headers = {"api-subscription-key": self._key, "Content-Type": "application/json"}
        body = {"input": text, "source_language_code": src, "target_language_code": tgt, "model": self._model}
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(f"{self._endpoint}/translate", headers=headers, json=body)
        except httpx.HTTPError:
            raise TranslationUnavailable(
                "Could not reach the translation service. Check the internet connection and try again."
            )

        if response.status_code in (401, 403):
            raise TranslationUnavailable(
                "Sarvam did not accept the key. Check SARVAM_API_KEY in backend/.env, and that the "
                "account still has credit."
            )
        if response.status_code == 429:
            raise TranslationUnavailable("The translation limit was reached. Try again later.")
        if response.status_code == 422:
            raise TranslationUnavailable(f"Sarvam cannot translate from {source} to {target}.")
        if response.status_code != 200:
            raise TranslationUnavailable(f"The translation service returned an error ({response.status_code}).")
        try:
            result = response.json()["translated_text"]
        except (ValueError, KeyError, TypeError):
            raise TranslationUnavailable("The translation service sent an unexpected reply.")
        if not isinstance(result, str) or not result.strip():
            raise TranslationUnavailable("The translation service sent an empty reply.")
        return result.strip()


class AzureTranslator:
    """Azure AI Translator, Text Translation API v3.

    Only the prompt text is sent. Medicine prompts never come here: they use the
    reviewed templates below. Error messages never include the key.
    """

    def __init__(
        self,
        key: str,
        region: str = "",
        endpoint: str = "https://api.cognitive.microsofttranslator.com",
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 10.0,
    ):
        self._key = key
        self._region = region
        self._endpoint = endpoint.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    def translate(self, text: str, source: str, target: str) -> str:
        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": "application/json; charset=UTF-8",
        }
        if self._region:
            headers["Ocp-Apim-Subscription-Region"] = self._region
        params = {"api-version": "3.0", "from": source, "to": target}
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(
                    f"{self._endpoint}/translate", params=params, headers=headers, json=[{"Text": text}]
                )
        except httpx.HTTPError:
            raise TranslationUnavailable("Could not reach the translation service. Check the internet connection and try again.")

        if response.status_code in (401, 403):
            raise TranslationUnavailable(
                "The translation service did not accept the key. Check AZURE_TRANSLATOR_KEY and "
                "AZURE_TRANSLATOR_REGION in backend/.env."
            )
        if response.status_code == 429:
            raise TranslationUnavailable("The translation limit was reached. Try again later.")
        if response.status_code == 400:
            raise TranslationUnavailable(f"The translation service cannot translate from {source} to {target}.")
        if response.status_code != 200:
            raise TranslationUnavailable(f"The translation service returned an error ({response.status_code}).")
        try:
            result = response.json()[0]["translations"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise TranslationUnavailable("The translation service sent an unexpected reply.")
        if not isinstance(result, str) or not result.strip():
            raise TranslationUnavailable("The translation service sent an empty reply.")
        return result.strip()


def build_translator(cfg=settings) -> Translator:
    """Pick the translator from settings. Never raises: a mistake becomes a clear message later."""
    provider = cfg.translator_provider
    explicit = bool(provider)
    if not provider:
        provider = "sarvam" if cfg.sarvam_api_key else "azure" if cfg.azure_translator_key else "none"

    if provider == "none":
        return UnconfiguredTranslator()
    if provider == "sarvam":
        if not cfg.sarvam_api_key:
            return UnconfiguredTranslator("TRANSLATOR_PROVIDER is sarvam but SARVAM_API_KEY is empty in backend/.env.")
        return SarvamTranslator(cfg.sarvam_api_key, cfg.sarvam_endpoint, cfg.sarvam_model)
    if provider == "azure":
        if not cfg.azure_translator_key:
            return UnconfiguredTranslator(
                "TRANSLATOR_PROVIDER is azure but AZURE_TRANSLATOR_KEY is empty in backend/.env."
            )
        return AzureTranslator(cfg.azure_translator_key, cfg.azure_translator_region, cfg.azure_translator_endpoint)
    return UnconfiguredTranslator(
        f"TRANSLATOR_PROVIDER '{provider}' is not recognised. Use sarvam, azure or none in backend/.env."
        if explicit
        else ""
    )


_translator: Translator = build_translator()


def set_translator(translator: Translator) -> None:
    global _translator
    _translator = translator


def get_translator() -> Translator:
    return _translator


# template key -> {"description": ..., "texts": {lang: {"text": ..., "verified": bool}}}
DOSE_TEMPLATES: dict[str, dict] = {
    "take_now": {
        "description": "It is time to take your medicine.",
        "texts": {"en": {"text": "It is time to take your medicine.", "verified": True}},
    },
    "take_after_food": {
        "description": "Take your medicine after food.",
        "texts": {"en": {"text": "Please take your medicine after food.", "verified": True}},
    },
    "take_before_food": {
        "description": "Take your medicine before food.",
        "texts": {"en": {"text": "Please take your medicine before food.", "verified": True}},
    },
    "check_label": {
        "description": "That does not look like the right medicine.",
        "texts": {
            "en": {
                "text": "That does not look like the right medicine. Please check the label.",
                "verified": True,
            }
        },
    },
}


def get_verified_template(key: str, language: str) -> Optional[str]:
    entry = DOSE_TEMPLATES.get(key, {}).get("texts", {}).get(language)
    if entry and entry.get("verified"):
        return entry["text"]
    return None


def list_templates() -> list[dict]:
    return [
        {
            "key": key,
            "description": tpl["description"],
            "verified_languages": sorted(
                lang for lang, t in tpl["texts"].items() if t.get("verified")
            ),
        }
        for key, tpl in DOSE_TEMPLATES.items()
    ]
