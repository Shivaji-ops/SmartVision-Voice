import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import escalation
from app.db import Base, get_db
from app.doses import todays_doses
from app.escalation import escalate_pending, sweep_missed_doses
from app.main import app
from app.models import Alert, Event, MedicationSchedule, Patient
from app.models import PromptAudio
from app.translation import get_translator
from app.tts import SpeechUnavailable, get_speaker


class RecordingNotifier:
    def __init__(self):
        self.sent = []

    def send(self, channel, target, message):
        self.sent.append((channel, target, message))


class BrokenNotifier:
    def send(self, channel, target, message):
        raise RuntimeError("provider down")


class FakeTranslator:
    def translate(self, text, source, target):
        return f"[{target}] {text}"


class FakeSpeaker:
    """Stands in for text to speech. The "audio" is a tiny WAV-looking blob that contains the text."""

    def __init__(self, voice="fake:1"):
        self.voice = voice
        self.calls = []
        self.fail = None

    def speak(self, text, language):
        if self.fail:
            raise SpeechUnavailable(self.fail)
        self.calls.append((text, language))
        return b"RIFF\x00\x00\x00\x00WAVE" + text.encode("utf-8")


def use_speaker(speaker):
    app.dependency_overrides[get_speaker] = lambda: speaker
    return speaker


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    notifier = RecordingNotifier()
    app.dependency_overrides[get_db] = override_db
    escalation.set_notifier(notifier)
    yield TestClient(app), Session, notifier
    app.dependency_overrides.clear()
    escalation.set_notifier(escalation.LogNotifier())


def register(client, email="asha@example.com"):
    r = client.post("/api/auth/register", json={"email": email, "name": "Asha", "password": "correct-horse"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_patient(client, headers, language="te", with_contacts=True):
    r = client.post("/api/patients", headers=headers, json={"name": "Lakshmi", "language": language})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    if with_contacts:
        for priority, phone in ((1, "+911111111111"), (2, "+912222222222"), (3, "+913333333333")):
            r = client.post(
                f"/api/patients/{pid}/contacts",
                headers=headers,
                json={"name": f"Contact {priority}", "phone": phone, "priority": priority},
            )
            assert r.status_code == 201, r.text
    return pid


def make_device(client, headers, pid):
    r = client.post(f"/api/patients/{pid}/devices", headers=headers, json={"name": "Frame 1"})
    assert r.status_code == 201, r.text
    return {"X-Device-Key": r.json()["api_key"]}


@pytest.fixture()
def world(env):
    client, Session, notifier = env
    headers = register(client)
    pid = make_patient(client, headers)
    device = make_device(client, headers, pid)
    return client, Session, notifier, headers, pid, device


# ---- auth and ownership -----------------------------------------------------
def test_register_login_and_protected_routes(env):
    client, _, _ = env
    register(client)
    assert client.post("/api/auth/register", json={"email": "ASHA@example.com", "name": "x", "password": "correct-horse"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": "asha@example.com", "password": "correct-horse"})
    assert ok.status_code == 200
    assert client.get("/api/patients").status_code == 401
    assert client.get("/api/patients", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_caregiver_cannot_see_another_caregivers_patient(env):
    client, _, _ = env
    a = register(client, "a@example.com")
    b = register(client, "b@example.com")
    pid = make_patient(client, a)
    assert client.get(f"/api/patients/{pid}", headers=b).status_code == 404
    assert client.get(f"/api/patients/{pid}/summary", headers=b).status_code == 404
    assert client.get(f"/api/patients/{pid}", headers=a).status_code == 200


def test_device_key_required(world):
    client, *_ = world
    assert client.post("/api/device/heartbeat", json={}).status_code == 401
    assert client.post("/api/device/heartbeat", json={}, headers={"X-Device-Key": "sv_nope"}).status_code == 401


# ---- falls, wear gating, alerts ----------------------------------------------
def test_confirmed_fall_raises_critical_alert_and_texts_first_contact(world):
    client, _, notifier, headers, pid, device = world
    r = client.post("/api/device/events", headers=device, json={"type": "fall_confirmed", "payload": {"worn": True}})
    assert r.status_code == 201
    alerts = client.get("/api/alerts", headers=headers).json()
    assert len(alerts) == 1
    assert alerts[0]["level"] == "critical" and alerts[0]["tier"] == 1
    assert notifier.sent == [("sms", "+911111111111", "Smart Vision: Lakshmi - Fall detected")]
    assert alerts[0]["notifications"][0]["channel"] == "sms"


def test_suppressed_and_cancelled_falls_never_alert(world):
    client, _, notifier, headers, pid, device = world
    for kind in ("fall_suppressed", "fall_cancelled"):
        assert client.post("/api/device/events", headers=device, json={"type": kind}).status_code == 201
    assert client.get("/api/alerts", headers=headers).json() == []
    assert notifier.sent == []
    events = client.get(f"/api/patients/{pid}/events", headers=headers).json()
    assert {e["type"] for e in events} == {"fall_suppressed", "fall_cancelled"}


def test_server_only_event_type_is_rejected_from_device(world):
    client, _, _, _, _, device = world
    assert client.post("/api/device/events", headers=device, json={"type": "med_missed"}).status_code == 422


def test_future_device_clock_is_clamped(world):
    client, *_, device = world
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).isoformat()
    r = client.post("/api/device/events", headers=device, json={"type": "obstacle", "occurred_at": future})
    assert r.status_code == 201
    assert r.json()["occurred_at"] <= dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def test_alert_still_created_when_sms_provider_is_down(env):
    client, _, _ = env
    escalation.set_notifier(BrokenNotifier())
    headers = register(client)
    pid = make_patient(client, headers)
    device = make_device(client, headers, pid)
    assert client.post("/api/device/events", headers=device, json={"type": "sos"}).status_code == 201
    alerts = client.get("/api/alerts", headers=headers).json()
    assert len(alerts) == 1 and alerts[0]["notifications"] == []


def test_unacknowledged_critical_alert_escalates_then_stops_at_max_tier(world):
    client, Session, notifier, headers, pid, device = world
    client.post("/api/device/events", headers=device, json={"type": "sos"})
    with Session() as db:
        alert = db.query(Alert).one()
        t0 = alert.created_at
        assert escalate_pending(db, t0 + dt.timedelta(seconds=60)) == 0
        assert escalate_pending(db, t0 + dt.timedelta(seconds=130)) == 1
        db.commit()
    assert ("voice", "+912222222222", "Smart Vision: Lakshmi - SOS button pressed") in notifier.sent
    with Session() as db:
        assert escalate_pending(db, t0 + dt.timedelta(seconds=300)) == 1
        db.commit()
    assert ("voice", "+913333333333", "Smart Vision: Lakshmi - SOS button pressed") in notifier.sent
    with Session() as db:
        assert escalate_pending(db, t0 + dt.timedelta(seconds=900)) == 0  # already at tier 3
        assert db.query(Alert).one().tier == 3


def test_acknowledging_stops_escalation(world):
    client, Session, notifier, headers, pid, device = world
    client.post("/api/device/events", headers=device, json={"type": "fall_confirmed"})
    alert_id = client.get("/api/alerts", headers=headers).json()[0]["id"]
    acked = client.post(f"/api/alerts/{alert_id}/ack", headers=headers).json()
    assert acked["status"] == "acknowledged" and acked["acknowledged_at"]
    with Session() as db:
        later = db.query(Alert).one().created_at + dt.timedelta(hours=1)
        assert escalate_pending(db, later) == 0
    assert client.get("/api/alerts", headers=headers).json() == []
    assert len(client.get("/api/alerts?state=acknowledged", headers=headers).json()) == 1


def test_other_caregiver_cannot_acknowledge_alert(world):
    client, _, _, _, _, device = world
    client.post("/api/device/events", headers=device, json={"type": "sos"})
    intruder = register(client, "intruder@example.com")
    assert client.post("/api/alerts/1/ack", headers=intruder).status_code == 404


# ---- medication -------------------------------------------------------------
# 08:00 Asia/Kolkata on 2026-10-13 is 02:30 UTC; a 30 minute window ends 03:00 UTC.
DUE_UTC = dt.datetime(2026, 10, 13, 2, 30)


def add_morning_dose(client, Session, headers, pid):
    r = client.post(
        f"/api/patients/{pid}/schedules",
        headers=headers,
        json={"name": "Metformin", "dose_text": "500 mg", "time_of_day": "08:00", "window_minutes": 30},
    )
    assert r.status_code == 201, r.text
    sched_id = r.json()["id"]
    with Session() as db:  # pretend the schedule existed before this dose came due
        db.get(MedicationSchedule, sched_id).created_at = dt.datetime(2026, 10, 13, 0, 0)
        db.commit()
    return sched_id


def test_schedule_validation(world):
    client, _, _, headers, pid, _ = world
    bad = client.post(f"/api/patients/{pid}/schedules", headers=headers, json={"name": "x", "time_of_day": "25:00"})
    assert bad.status_code == 422


def test_missed_dose_is_flagged_once(world):
    client, Session, notifier, headers, pid, _ = world
    add_morning_dose(client, Session, headers, pid)
    now = dt.datetime(2026, 10, 13, 3, 15)  # 08:45 local, window closed at 08:30
    with Session() as db:
        assert sweep_missed_doses(db, now) == 1
        db.commit()
    with Session() as db:
        assert sweep_missed_doses(db, now + dt.timedelta(minutes=5)) == 0  # idempotent
    alerts = client.get("/api/alerts", headers=headers).json()
    assert len(alerts) == 1 and alerts[0]["level"] == "warning"
    assert "Missed dose: Metformin at 08:00" in alerts[0]["title"]
    assert notifier.sent[0][0:2] == ("sms", "+911111111111")


def test_taken_dose_is_not_flagged_missed(world):
    client, Session, notifier, headers, pid, _ = world
    sched_id = add_morning_dose(client, Session, headers, pid)
    with Session() as db:
        db.add(Event(patient_id=pid, schedule_id=sched_id, type="med_taken", occurred_at=dt.datetime(2026, 10, 13, 2, 40)))
        db.commit()
    with Session() as db:
        assert sweep_missed_doses(db, dt.datetime(2026, 10, 13, 3, 15)) == 0
    assert notifier.sent == []


def test_dose_not_flagged_before_window_closes_or_before_schedule_existed(world):
    client, Session, _, headers, pid, _ = world
    add_morning_dose(client, Session, headers, pid)
    with Session() as db:
        assert sweep_missed_doses(db, dt.datetime(2026, 10, 13, 2, 50)) == 0  # still inside the window
    # Yesterday's 08:00 was before the schedule existed, so only today's can ever be flagged.
    with Session() as db:
        assert sweep_missed_doses(db, dt.datetime(2026, 10, 13, 3, 15)) == 1


def test_todays_dose_statuses_through_the_day(world):
    client, Session, _, headers, pid, _ = world
    sched_id = add_morning_dose(client, Session, headers, pid)

    def status_at(hour, minute):
        with Session() as db:
            patient = db.get(Patient, pid)
            return todays_doses(db, patient, dt.datetime(2026, 10, 13, hour, minute))[0]["status"]

    assert status_at(1, 30) == "upcoming"  # 07:00 local
    assert status_at(2, 40) == "pending"  # 08:10 local
    assert status_at(3, 15) == "missed"  # 08:45 local
    with Session() as db:
        db.add(Event(patient_id=pid, schedule_id=sched_id, type="med_taken", occurred_at=dt.datetime(2026, 10, 13, 2, 45)))
        db.commit()
    assert status_at(3, 15) == "taken"


# ---- voice prompts ----------------------------------------------------------
def test_dose_prompt_needs_a_template(world):
    client, _, _, headers, pid, _ = world
    r = client.post(f"/api/patients/{pid}/prompts", headers=headers, json={"key": "med", "text": "take two", "is_dose_related": True})
    assert r.status_code == 422 and "reviewed template" in r.json()["detail"]


def test_dose_prompt_refused_when_no_verified_template_in_patient_language(world):
    client, _, _, headers, pid, _ = world  # patient language is Telugu
    app.dependency_overrides[get_translator] = lambda: FakeTranslator()
    try:
        r = client.post(
            f"/api/patients/{pid}/prompts",
            headers=headers,
            json={"key": "med", "is_dose_related": True, "template_key": "take_now"},
        )
    finally:
        app.dependency_overrides.pop(get_translator, None)
    assert r.status_code == 422 and "not machine translated" in r.json()["detail"]
    assert client.get(f"/api/patients/{pid}/prompts", headers=headers).json() == []


def test_dose_prompt_published_from_verified_template(env):
    client, _, _ = env
    headers = register(client)
    pid = make_patient(client, headers, language="en", with_contacts=False)
    r = client.post(
        f"/api/patients/{pid}/prompts",
        headers=headers,
        json={"key": "med_reminder", "is_dose_related": True, "template_key": "take_after_food"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Please take your medicine after food."
    assert r.json()["template_key"] == "take_after_food"


def reviewed_prompt(client, headers, pid, key, text):
    """What the dashboard does: preview the translation, then save what the caregiver approved."""
    preview = client.post(f"/api/patients/{pid}/prompts/preview", headers=headers, json={"text": text})
    assert preview.status_code == 200, preview.text
    return client.post(
        f"/api/patients/{pid}/prompts",
        headers=headers,
        json={"key": key, "text": text, "translated_text": preview.json()["translated_text"]},
    )


def test_preview_is_503_when_no_translator_configured(world):
    client, _, _, headers, pid, _ = world
    r = client.post(f"/api/patients/{pid}/prompts/preview", headers=headers, json={"text": "Good morning"})
    assert r.status_code == 503 and "not set up" in r.json()["detail"]
    assert client.get(f"/api/patients/{pid}/prompts", headers=headers).json() == []


def test_translated_prompt_cannot_be_saved_without_review(world):
    client, _, _, headers, pid, _ = world
    app.dependency_overrides[get_translator] = lambda: FakeTranslator()
    try:
        r = client.post(f"/api/patients/{pid}/prompts", headers=headers, json={"key": "greeting", "text": "Good morning"})
    finally:
        app.dependency_overrides.pop(get_translator, None)
    assert r.status_code == 422 and "check the result" in r.json()["detail"]
    assert client.get(f"/api/patients/{pid}/prompts", headers=headers).json() == []


def test_preview_returns_translation_and_back_translation_without_saving(world):
    client, _, _, headers, pid, _ = world  # patient language is Telugu
    app.dependency_overrides[get_translator] = lambda: FakeTranslator()
    try:
        r = client.post(f"/api/patients/{pid}/prompts/preview", headers=headers, json={"text": "Good morning"})
    finally:
        app.dependency_overrides.pop(get_translator, None)
    body = r.json()
    assert r.status_code == 200
    assert body["needs_translation"] is True and body["target_language"] == "te"
    assert body["translated_text"] == "[te] Good morning"
    assert body["back_translation"] == "[en] [te] Good morning"
    assert client.get(f"/api/patients/{pid}/prompts", headers=headers).json() == []


def test_preview_of_an_edited_translation_only_translates_it_back(world):
    client, _, _, headers, pid, _ = world
    app.dependency_overrides[get_translator] = lambda: FakeTranslator()
    try:
        r = client.post(
            f"/api/patients/{pid}/prompts/preview",
            headers=headers,
            json={"text": "Good morning", "translated_text": "my own wording"},
        )
    finally:
        app.dependency_overrides.pop(get_translator, None)
    assert r.json()["translated_text"] == "my own wording"
    assert r.json()["back_translation"] == "[en] my own wording"


def test_preview_in_the_wearers_language_needs_no_translator(env):
    client, _, _ = env
    headers = register(client)
    pid = make_patient(client, headers, language="en", with_contacts=False)
    r = client.post(f"/api/patients/{pid}/prompts/preview", headers=headers, json={"text": "Good morning"})
    assert r.status_code == 200
    assert r.json()["needs_translation"] is False and r.json()["back_translation"] is None


def test_preview_is_not_available_for_another_caregivers_patient(env):
    client, _, _ = env
    a = register(client, "a@example.com")
    b = register(client, "b@example.com")
    pid = make_patient(client, a)
    r = client.post(f"/api/patients/{pid}/prompts/preview", headers=b, json={"text": "Hello"})
    assert r.status_code == 404


def test_caregiver_edit_of_the_translation_is_what_gets_saved(world):
    client, _, _, headers, pid, _ = world
    r = client.post(
        f"/api/patients/{pid}/prompts",
        headers=headers,
        json={"key": "greeting", "text": "Good morning", "translated_text": "  caregiver fixed this  "},
    )
    assert r.status_code == 200
    assert r.json()["text"] == "caregiver fixed this" and r.json()["source_text"] == "Good morning"


def test_dose_prompt_ignores_any_supplied_translation(env):
    client, _, _ = env
    headers = register(client)
    pid = make_patient(client, headers, language="en", with_contacts=False)
    r = client.post(
        f"/api/patients/{pid}/prompts",
        headers=headers,
        json={"key": "med", "is_dose_related": True, "template_key": "take_now", "translated_text": "double the dose"},
    )
    assert r.status_code == 200 and r.json()["text"] == "It is time to take your medicine."


def test_free_text_prompt_translated_versioned_and_synced_to_device(world):
    client, _, _, headers, pid, device = world
    app.dependency_overrides[get_translator] = lambda: FakeTranslator()
    try:
        first = reviewed_prompt(client, headers, pid, "greeting", "Good morning")
        second = reviewed_prompt(client, headers, pid, "walk", "Time for a walk")
        edited = reviewed_prompt(client, headers, pid, "greeting", "Good evening")
    finally:
        app.dependency_overrides.pop(get_translator, None)
    assert first.json()["text"] == "[te] Good morning" and first.json()["source_text"] == "Good morning"
    assert (first.json()["version"], second.json()["version"], edited.json()["version"]) == (1, 2, 3)

    everything = client.get("/api/device/prompts", headers=device).json()
    assert everything["version"] == 3 and everything["language"] == "te"
    assert {p["key"] for p in everything["prompts"]} == {"greeting", "walk"}

    delta = client.get("/api/device/prompts?since_version=2", headers=device).json()
    assert [p["key"] for p in delta["prompts"]] == ["greeting"]
    assert delta["prompts"][0]["text"] == "[te] Good evening"
    assert client.get("/api/device/prompts?since_version=3", headers=device).json()["prompts"] == []


def test_same_language_prompt_needs_no_translator(env):
    client, _, _ = env
    headers = register(client)
    pid = make_patient(client, headers, language="en", with_contacts=False)
    r = client.post(f"/api/patients/{pid}/prompts", headers=headers, json={"key": "greeting", "text": "Good morning"})
    assert r.status_code == 200 and r.json()["text"] == "Good morning"


# ---- dashboard summary and heartbeat ----------------------------------------
def test_summary_reflects_heartbeat_location_and_alerts(world):
    client, _, _, headers, pid, device = world
    before = client.get(f"/api/patients/{pid}/summary", headers=headers).json()
    assert before["device"]["online"] is False and before["last_location"] is None

    client.post("/api/device/heartbeat", headers=device, json={"battery_pct": 71, "worn": True})
    client.post("/api/device/events", headers=device, json={"type": "location", "payload": {"lat": 17.385, "lon": 78.4867}})
    client.post("/api/device/events", headers=device, json={"type": "sos"})

    after = client.get(f"/api/patients/{pid}/summary", headers=headers).json()
    assert after["device"]["online"] is True
    assert after["device"]["battery_pct"] == 71 and after["device"]["worn"] is True
    assert after["last_location"]["lat"] == 17.385
    assert after["open_alerts"] == 1
    assert all(e["type"] != "location" for e in after["recent_events"])  # kept off the activity feed
    assert after["recent_events"][0]["type"] == "sos"


def test_timezone_is_validated(env):
    client, _, _ = env
    headers = register(client)
    r = client.post("/api/patients", headers=headers, json={"name": "X", "timezone": "Mars/Olympus"})
    assert r.status_code == 422


# ---- spoken prompts -----------------------------------------------------------
def save_text_prompt(client, headers, pid, key="greeting", text="Good morning"):
    """A prompt written in the wearer's own language, so no translation is involved."""
    r = client.post(
        f"/api/patients/{pid}/prompts", headers=headers, json={"key": key, "text": text, "source_language": "te"}
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_speech_preview_is_503_when_speech_is_not_set_up(world):
    client, _, _, headers, pid, _ = world
    r = client.post(f"/api/patients/{pid}/speech/preview", headers=headers, json={"text": "hello"})
    assert r.status_code == 503 and "not set up" in r.json()["detail"]


def test_speech_preview_speaks_in_the_wearers_language_and_saves_nothing(world):
    client, Session, _, headers, pid, _ = world
    speaker = use_speaker(FakeSpeaker())
    r = client.post(f"/api/patients/{pid}/speech/preview", headers=headers, json={"text": "శుభోదయం"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content.startswith(b"RIFF") and "శుభోదయం".encode() in r.content
    assert speaker.calls == [("శుభోదయం", "te")]
    with Session() as db:
        assert db.query(PromptAudio).count() == 0
    assert client.get(f"/api/patients/{pid}/prompts", headers=headers).json() == []


def test_speech_preview_hides_other_caregivers_patients_and_needs_sign_in(env):
    client, _, _ = env
    a, b = register(client, "a@example.com"), register(client, "b@example.com")
    pid = make_patient(client, a)
    use_speaker(FakeSpeaker())
    assert client.post(f"/api/patients/{pid}/speech/preview", headers=b, json={"text": "hi"}).status_code == 404
    assert client.post(f"/api/patients/{pid}/speech/preview", json={"text": "hi"}).status_code == 401


def test_saving_a_prompt_also_makes_its_voice(world):
    client, Session, _, headers, pid, _ = world
    speaker = use_speaker(FakeSpeaker())
    saved = save_text_prompt(client, headers, pid, text="శుభోదయం")
    assert saved["audio_ready"] is True and saved["audio_error"] is None
    assert speaker.calls == [("శుభోదయం", "te")]
    assert client.get(f"/api/patients/{pid}/prompts", headers=headers).json()[0]["audio_ready"] is True
    r = client.get(f"/api/patients/{pid}/prompts/greeting/audio", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert len(speaker.calls) == 1  # served from the cache


def test_a_prompt_is_still_saved_when_the_voice_cannot_be_made_and_can_be_made_later(world):
    client, _, _, headers, pid, device = world
    saved = save_text_prompt(client, headers, pid, text="శుభోదయం")  # no speech service
    assert saved["audio_ready"] is False and "not set up" in saved["audio_error"]
    assert client.get(f"/api/patients/{pid}/prompts", headers=headers).json()[0]["text"] == "శుభోదయం"
    assert client.get(f"/api/patients/{pid}/prompts/greeting/audio", headers=headers).status_code == 503
    assert client.get("/api/device/prompts/greeting/audio", headers=device).status_code == 503

    speaker = use_speaker(FakeSpeaker())
    assert client.get(f"/api/patients/{pid}/prompts/greeting/audio", headers=headers).status_code == 200
    assert client.get("/api/device/prompts/greeting/audio", headers=device).status_code == 200
    assert len(speaker.calls) == 1
    assert client.get(f"/api/patients/{pid}/prompts", headers=headers).json()[0]["audio_ready"] is True


def test_changing_the_wording_makes_new_audio_and_the_old_is_not_served(world):
    client, _, _, headers, pid, _ = world
    speaker = use_speaker(FakeSpeaker())
    save_text_prompt(client, headers, pid, text="first wording")
    speaker.fail = "down"
    save_text_prompt(client, headers, pid, text="second wording")  # voice fails this time
    prompts = client.get(f"/api/patients/{pid}/prompts", headers=headers).json()
    assert prompts[0]["text"] == "second wording" and prompts[0]["audio_ready"] is False
    assert client.get(f"/api/patients/{pid}/prompts/greeting/audio", headers=headers).status_code == 503
    speaker.fail = None
    r = client.get(f"/api/patients/{pid}/prompts/greeting/audio", headers=headers)
    assert b"second wording" in r.content and b"first wording" not in r.content


def test_a_changed_voice_remakes_audio_but_an_outage_keeps_the_earlier_audio(world):
    client, _, _, headers, pid, _ = world
    use_speaker(FakeSpeaker("voice:a"))
    save_text_prompt(client, headers, pid, text="hello there")
    newer = use_speaker(FakeSpeaker("voice:b"))
    assert client.get(f"/api/patients/{pid}/prompts/greeting/audio", headers=headers).status_code == 200
    assert len(newer.calls) == 1  # remade in the new voice
    newer.voice = "voice:c"
    newer.fail = "speech service down"
    r = client.get(f"/api/patients/{pid}/prompts/greeting/audio", headers=headers)
    assert r.status_code == 200 and b"hello there" in r.content  # earlier audio still served


def test_audio_for_a_missing_prompt_or_another_caregivers_prompt_is_404(env):
    client, _, _ = env
    a, b = register(client, "a@example.com"), register(client, "b@example.com")
    pid = make_patient(client, a)
    use_speaker(FakeSpeaker())
    save_text_prompt(client, a, pid)
    assert client.get(f"/api/patients/{pid}/prompts/nothing/audio", headers=a).status_code == 404
    assert client.get(f"/api/patients/{pid}/prompts/greeting/audio", headers=b).status_code == 404
    assert client.get(f"/api/patients/{pid}/prompts/greeting/audio").status_code == 401


def test_the_glasses_download_audio_with_an_etag_and_only_their_own(env):
    client, _, _ = env
    a, b = register(client, "a@example.com"), register(client, "b@example.com")
    pid_a, pid_b = make_patient(client, a), make_patient(client, b)
    glasses_a, glasses_b = make_device(client, a, pid_a), make_device(client, b, pid_b)
    use_speaker(FakeSpeaker())
    save_text_prompt(client, a, pid_a, text="for patient a")

    assert client.get("/api/device/prompts/greeting/audio").status_code == 401
    assert client.get("/api/device/prompts/greeting/audio", headers=glasses_b).status_code == 404
    r = client.get("/api/device/prompts/greeting/audio", headers=glasses_a)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and b"for patient a" in r.content
    again = client.get("/api/device/prompts/greeting/audio", headers={**glasses_a, "If-None-Match": r.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    stale = client.get("/api/device/prompts/greeting/audio", headers={**glasses_a, "If-None-Match": '"old"'})
    assert stale.status_code == 200

    listing = client.get("/api/device/prompts", headers=glasses_a).json()
    assert listing["prompts"][0]["audio_ready"] is True


def test_medicine_prompts_are_spoken_from_their_reviewed_wording(env):
    client, _, _ = env
    headers = register(client)
    pid = client.post("/api/patients", headers=headers, json={"name": "Lakshmi", "language": "en"}).json()["id"]
    speaker = use_speaker(FakeSpeaker())
    r = client.post(
        f"/api/patients/{pid}/prompts",
        headers=headers,
        json={"key": "dose", "is_dose_related": True, "template_key": "take_now", "text": "ignored"},
    )
    assert r.status_code == 200 and r.json()["audio_ready"] is True
    assert speaker.calls == [("It is time to take your medicine.", "en")]


def test_the_saved_audio_is_the_very_recording_that_was_previewed(world):
    client, _, _, headers, pid, _ = world

    class VaryingSpeaker(FakeSpeaker):
        def speak(self, text, language):  # a different recording every time, like real speech can be
            wav = super().speak(text, language)
            return wav + str(len(self.calls)).encode()

    speaker = use_speaker(VaryingSpeaker())
    heard = client.post(f"/api/patients/{pid}/speech/preview", headers=headers, json={"text": "శుభోదయం"}).content
    again = client.post(f"/api/patients/{pid}/speech/preview", headers=headers, json={"text": "శుభోదయం"}).content
    assert again == heard and len(speaker.calls) == 1  # repeating a preview costs nothing
    save_text_prompt(client, headers, pid, text="శుభోదయం")
    saved = client.get(f"/api/patients/{pid}/prompts/greeting/audio", headers=headers).content
    assert saved == heard and len(speaker.calls) == 1  # saving did not make a second, different recording
