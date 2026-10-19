"""The translation adapters, tested against fake HTTP servers so no key or network is needed."""
import dataclasses
import json

import httpx
import pytest

from app.config import Settings
from app.translation import (
    AzureTranslator,
    SarvamTranslator,
    TranslationUnavailable,
    UnconfiguredTranslator,
    build_translator,
)

SECRET = "super-secret-key-123"

# ---------------------------------------------------------------- Azure ----


def azure_for(handler, region="centralindia"):
    return AzureTranslator(SECRET, region, "https://example.test/", transport=httpx.MockTransport(handler))


def test_azure_sends_the_request_azure_expects_and_returns_the_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[{"translations": [{"text": "  శుభోదయం ", "to": "te"}]}])

    result = azure_for(handler).translate("Good morning", "en", "te")

    assert result == "శుభోదయం"
    assert seen["url"].startswith("https://example.test/translate?")
    assert "api-version=3.0" in seen["url"] and "from=en" in seen["url"] and "to=te" in seen["url"]
    assert seen["headers"]["ocp-apim-subscription-key"] == SECRET
    assert seen["headers"]["ocp-apim-subscription-region"] == "centralindia"
    assert seen["body"] == [{"Text": "Good morning"}]


def test_azure_region_header_is_omitted_when_no_region_is_set():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        return httpx.Response(200, json=[{"translations": [{"text": "x"}]}])

    azure_for(handler, region="").translate("hi", "en", "hi")
    assert "ocp-apim-subscription-region" not in seen["headers"]


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "did not accept the key"),
        (403, "did not accept the key"),
        (429, "limit was reached"),
        (400, "cannot translate from en to te"),
        (500, "error (500)"),
    ],
)
def test_azure_error_statuses_become_readable_messages_without_leaking_the_key(status, expected):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": f"echo {SECRET}"}})

    with pytest.raises(TranslationUnavailable) as err:
        azure_for(handler).translate("Good morning", "en", "te")
    assert expected in str(err.value)
    assert SECRET not in str(err.value)


def test_azure_network_failure_is_reported_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(TranslationUnavailable) as err:
        azure_for(handler).translate("Good morning", "en", "te")
    assert "Could not reach" in str(err.value)


@pytest.mark.parametrize("payload", [{"unexpected": True}, [], [{"translations": []}], [{"translations": [{"text": "   "}]}]])
def test_azure_odd_replies_are_refused_instead_of_saved(payload):
    def handler(request):
        return httpx.Response(200, json=payload)

    with pytest.raises(TranslationUnavailable):
        azure_for(handler).translate("Good morning", "en", "te")


# --------------------------------------------------------------- Sarvam ----


def sarvam_for(handler):
    return SarvamTranslator(SECRET, "https://sarvam.test/", transport=httpx.MockTransport(handler))


def test_sarvam_sends_the_request_sarvam_expects_and_returns_the_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"request_id": "r1", "translated_text": "  శుభోదయం ", "source_language_code": "en-IN"}
        )

    result = sarvam_for(handler).translate("Good morning", "en", "te")

    assert result == "శుభోదయం"
    assert seen["url"] == "https://sarvam.test/translate"
    assert seen["headers"]["api-subscription-key"] == SECRET
    assert seen["body"] == {
        "input": "Good morning",
        "source_language_code": "en-IN",
        "target_language_code": "te-IN",
        "model": "sarvam-translate:v1",
    }


@pytest.mark.parametrize(
    "ours, theirs",
    [("en", "en-IN"), ("hi", "hi-IN"), ("te", "te-IN"), ("ur", "ur-IN"), ("or", "od-IN"), ("od", "od-IN"), ("gom", "kok-IN")],
)
def test_sarvam_language_codes_are_mapped(ours, theirs):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"translated_text": "x"})

    sarvam_for(handler).translate("hello", "en", ours)
    assert seen["body"]["target_language_code"] == theirs


def test_sarvam_back_translation_direction_is_supported():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"translated_text": "Good morning"})

    sarvam_for(handler).translate("శుభోదయం", "te", "en")
    assert seen["body"]["source_language_code"] == "te-IN" and seen["body"]["target_language_code"] == "en-IN"


def test_sarvam_refuses_unknown_languages_and_long_text_without_calling_out():
    def handler(request):
        raise AssertionError("no request should be made")

    t = sarvam_for(handler)
    with pytest.raises(TranslationUnavailable) as unknown:
        t.translate("hello", "en", "xx")
    assert "cannot translate between" in str(unknown.value)
    with pytest.raises(TranslationUnavailable) as long:
        t.translate("a" * 2001, "en", "te")
    assert "too long" in str(long.value)


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "did not accept the key"),
        (403, "did not accept the key"),
        (429, "limit was reached"),
        (422, "cannot translate from en to te"),
        (500, "error (500)"),
    ],
)
def test_sarvam_error_statuses_become_readable_messages_without_leaking_the_key(status, expected):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": f"echo {SECRET}"}})

    with pytest.raises(TranslationUnavailable) as err:
        sarvam_for(handler).translate("Good morning", "en", "te")
    assert expected in str(err.value)
    assert SECRET not in str(err.value)


def test_sarvam_network_failure_is_reported_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(TranslationUnavailable) as err:
        sarvam_for(handler).translate("Good morning", "en", "te")
    assert "Could not reach" in str(err.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, json={"translated_text": "   "}),
        httpx.Response(200, json={"translated_text": None}),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, content=b"<html>not json</html>"),
    ],
)
def test_sarvam_odd_replies_are_refused_instead_of_saved(response):
    with pytest.raises(TranslationUnavailable):
        sarvam_for(lambda request: response).translate("Good morning", "en", "te")


# ------------------------------------------------- choosing a provider ----

NO_KEYS = dataclasses.replace(
    Settings(), translator_provider="", sarvam_api_key="", azure_translator_key="", azure_translator_region=""
)


def pick(**changes):
    return build_translator(dataclasses.replace(NO_KEYS, **changes))


def refusal(translator) -> str:
    with pytest.raises(TranslationUnavailable) as err:
        translator.translate("hi", "en", "te")
    return str(err.value)


def test_no_keys_means_translation_is_not_set_up():
    t = pick()
    assert isinstance(t, UnconfiguredTranslator) and "SARVAM_API_KEY" in refusal(t)


def test_a_key_alone_picks_its_provider_and_sarvam_wins_when_both_are_set():
    assert isinstance(pick(sarvam_api_key="k"), SarvamTranslator)
    assert isinstance(pick(azure_translator_key="k"), AzureTranslator)
    assert isinstance(pick(sarvam_api_key="k", azure_translator_key="k"), SarvamTranslator)


def test_provider_setting_overrides_which_key_is_used():
    assert isinstance(pick(translator_provider="azure", sarvam_api_key="k", azure_translator_key="k"), AzureTranslator)
    assert isinstance(pick(translator_provider="sarvam", sarvam_api_key="k", azure_translator_key="k"), SarvamTranslator)
    assert isinstance(pick(translator_provider="none", sarvam_api_key="k"), UnconfiguredTranslator)


def test_a_chosen_provider_without_its_key_says_which_key_is_missing():
    assert "SARVAM_API_KEY is empty" in refusal(pick(translator_provider="sarvam", azure_translator_key="k"))
    assert "AZURE_TRANSLATOR_KEY is empty" in refusal(pick(translator_provider="azure", sarvam_api_key="k"))


def test_an_unknown_provider_is_reported_not_crashed_on():
    assert "'googel' is not recognised" in refusal(pick(translator_provider="googel", sarvam_api_key="k"))
