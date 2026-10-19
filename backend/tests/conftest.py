"""Keep the tests offline, whatever is in the developer's backend/.env.

Without this, a real SARVAM_API_KEY in .env would make the suite call the real services
(costing money) and break the tests that expect "not set up".
"""
import pytest

from app import audio, translation, tts


@pytest.fixture(autouse=True)
def offline_services():
    audio.clear_recent()
    before = (translation.get_translator(), tts.get_speaker())
    translation.set_translator(translation.UnconfiguredTranslator())
    tts.set_speaker(tts.UnconfiguredSpeaker())
    yield
    translation.set_translator(before[0])
    tts.set_speaker(before[1])
