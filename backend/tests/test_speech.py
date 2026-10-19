"""The speech adapter, tested against a fake HTTP server so no key or network is needed."""
import base64
import dataclasses
import io
import json
import wave

import httpx
import pytest

from app.config import Settings
from app.tts import SarvamSpeaker, SpeechUnavailable, UnconfiguredSpeaker, build_speaker

SECRET = "super-secret-key-123"


def make_wav(seconds: float = 0.1, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def ok(wav: bytes) -> httpx.Response:
    return httpx.Response(200, json={"request_id": "r1", "audios": [base64.b64encode(wav).decode()]})


def speaker_for(handler, **kw):
    return SarvamSpeaker(SECRET, "https://sarvam.test/", transport=httpx.MockTransport(handler), **kw)


def test_sends_the_request_sarvam_expects_and_returns_the_wav():
    seen = {}
    wav = make_wav()

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return ok(wav)

    result = speaker_for(handler).speak("  శుభోదయం  ", "te")

    assert result == wav
    assert seen["url"] == "https://sarvam.test/text-to-speech"
    assert seen["headers"]["api-subscription-key"] == SECRET
    assert seen["body"] == {
        "text": "శుభోదయం",
        "language_code": "te-IN",
        "model": "bulbul:v3",
        "speaker": "shubh",
        "pace": 0.9,
        "speech_sample_rate": 16000,
        "output_audio_codec": "wav",
    }


def test_voice_settings_are_sent_and_identify_the_voice():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ok(make_wav())

    s = speaker_for(handler, model="bulbul:v4-flash", speaker="kavitha_te_narration", pace=0.8, sample_rate=22050)
    s.speak("hello", "en")
    assert seen["body"]["model"] == "bulbul:v4-flash" and seen["body"]["speaker"] == "kavitha_te_narration"
    assert seen["body"]["pace"] == 0.8 and seen["body"]["speech_sample_rate"] == 22050
    assert s.voice == "sarvam:bulbul:v4-flash:kavitha_te_narration:0.8:22050"
    assert speaker_for(handler).voice != s.voice


@pytest.mark.parametrize("ours, theirs", [("en", "en-IN"), ("hi", "hi-IN"), ("te", "te-IN"), ("or", "od-IN"), ("od", "od-IN")])
def test_language_codes_are_mapped(ours, theirs):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ok(make_wav())

    speaker_for(handler).speak("hello", ours)
    assert seen["body"]["language_code"] == theirs


def test_refuses_unsupported_languages_empty_and_long_text_without_calling_out():
    def handler(request):
        raise AssertionError("no request should be made")

    s = speaker_for(handler)
    for language in ("ur", "xx", "kok"):
        with pytest.raises(SpeechUnavailable) as err:
            s.speak("hello", language)
        assert "no voice" in str(err.value)
    with pytest.raises(SpeechUnavailable):
        s.speak("   ", "te")
    with pytest.raises(SpeechUnavailable) as err:
        s.speak("a" * 2501, "te")
    assert "too long" in str(err.value)


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "did not accept the key"),
        (403, "did not accept the key"),
        (429, "limit was reached"),
        (400, "SARVAM_TTS_SPEAKER"),
        (422, "SARVAM_TTS_SPEAKER"),
        (500, "error (500)"),
    ],
)
def test_error_statuses_become_readable_messages_without_leaking_the_key(status, expected):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": f"echo {SECRET}"}})

    with pytest.raises(SpeechUnavailable) as err:
        speaker_for(handler).speak("hello", "te")
    assert expected in str(err.value)
    assert SECRET not in str(err.value)


def test_network_failure_is_reported_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(SpeechUnavailable) as err:
        speaker_for(handler).speak("hello", "te")
    assert "Could not reach" in str(err.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, json={"audios": []}),
        httpx.Response(200, json={"audios": [None]}),
        httpx.Response(200, json={"audios": ["!!! not base64 !!!"]}),
        httpx.Response(200, json={"audios": [base64.b64encode(b"this is not a wav file").decode()]}),
        httpx.Response(200, content=b"<html>not json</html>"),
    ],
)
def test_odd_replies_are_refused_instead_of_stored(response):
    with pytest.raises(SpeechUnavailable):
        speaker_for(lambda request: response).speak("hello", "te")


# ------------------------------------------------- choosing a provider ----

NO_KEYS = dataclasses.replace(Settings(), speech_provider="", sarvam_api_key="")


def pick(**changes):
    return build_speaker(dataclasses.replace(NO_KEYS, **changes))


def refusal(speaker) -> str:
    with pytest.raises(SpeechUnavailable) as err:
        speaker.speak("hi", "te")
    return str(err.value)


def test_no_key_means_speech_is_not_set_up():
    s = pick()
    assert isinstance(s, UnconfiguredSpeaker) and "SARVAM_API_KEY" in refusal(s)


def test_a_key_alone_turns_speech_on_and_settings_pass_through():
    s = pick(sarvam_api_key="k", sarvam_tts_speaker="priya", sarvam_tts_pace=0.8)
    assert isinstance(s, SarvamSpeaker) and "priya" in s.voice and "0.8" in s.voice


def test_provider_none_turns_speech_off_even_with_a_key():
    assert isinstance(pick(speech_provider="none", sarvam_api_key="k"), UnconfiguredSpeaker)


def test_sarvam_without_a_key_and_unknown_providers_are_explained():
    assert "SARVAM_API_KEY is empty" in refusal(pick(speech_provider="sarvam"))
    assert "'googel' is not recognised" in refusal(pick(speech_provider="googel", sarvam_api_key="k"))
