"""Create demo data:  python -m app.seed

Makes a caregiver, one patient with three contacts and three daily doses, and a
device. Past doses are recorded as taken so the missed-dose sweep stays quiet
until you run the simulator. The device key is printed once; copy it.
"""
import datetime as dt

from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .doses import dose_window
from .models import (
    Caregiver,
    Contact,
    Device,
    Event,
    MedicationSchedule,
    Patient,
    VoicePrompt,
    utcnow,
)
from .security import hash_device_key, hash_password, new_device_key

DEMO_EMAIL = "demo@smartvision.test"
DEMO_PASSWORD = "demo-password-1"


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(Caregiver.id).where(Caregiver.email == DEMO_EMAIL)):
            print(f"Demo data already exists. Sign in as {DEMO_EMAIL}.")
            print("To start fresh, stop the server and delete smartvision.db.")
            return

        now = utcnow()
        caregiver = Caregiver(email=DEMO_EMAIL, name="Asha", password_hash=hash_password(DEMO_PASSWORD))
        db.add(caregiver)
        db.flush()

        patient = Patient(caregiver_id=caregiver.id, name="Lakshmi", language="en", timezone="Asia/Kolkata")
        db.add(patient)
        db.flush()

        for priority, (name, phone) in enumerate(
            [("Asha (daughter)", "+910000000001"), ("Ravi (son)", "+910000000002"), ("Dr. Rao", "+910000000003")],
            start=1,
        ):
            db.add(Contact(patient_id=patient.id, name=name, phone=phone, priority=priority))

        long_ago = now - dt.timedelta(days=7)
        schedules = []
        for name, dose_text, time_of_day in [
            ("Metformin", "500 mg with breakfast", "08:00"),
            ("Amlodipine", "5 mg", "14:00"),
            ("Atorvastatin", "10 mg at night", "21:00"),
        ]:
            sched = MedicationSchedule(
                patient_id=patient.id, name=name, dose_text=dose_text, time_of_day=time_of_day, created_at=long_ago
            )
            db.add(sched)
            schedules.append(sched)
        db.flush()

        # Record every dose that is already due, today and yesterday, as taken.
        for sched in schedules:
            for offset in (-1, 0):
                due_utc, _, _ = dose_window(sched, patient, now, offset)
                if due_utc <= now:
                    db.add(
                        Event(
                            patient_id=patient.id,
                            schedule_id=sched.id,
                            type="med_taken",
                            payload={"name": sched.name},
                            occurred_at=due_utc + dt.timedelta(minutes=6),
                        )
                    )

        key = new_device_key()
        db.add(
            Device(
                patient_id=patient.id,
                name="Frame 1",
                key_hash=hash_device_key(key),
                last_seen=now,
                battery_pct=82,
                worn=True,
            )
        )
        db.add(
            Event(
                patient_id=patient.id,
                type="location",
                payload={"lat": 17.385, "lon": 78.4867},
                occurred_at=now - dt.timedelta(minutes=3),
            )
        )

        patient.prompt_version = 1
        db.add(
            VoicePrompt(
                patient_id=patient.id,
                key="greeting",
                language="en",
                text="Good morning, Lakshmi.",
                source_text="Good morning, Lakshmi.",
                source_language="en",
                version=1,
            )
        )
        db.commit()

    print("Demo data created.")
    print(f"  Dashboard sign-in : {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"  Device key (shown once): {key}")


if __name__ == "__main__":
    main()
