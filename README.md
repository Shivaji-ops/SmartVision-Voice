# Smart Vision: caregiver backend and dashboard

The software side of AU Smart Vision. A caregiver signs in, sees how the wearer is doing, manages medicines and contacts, and changes what the glasses say. The glasses talk to the same backend through a small device API. Nothing here needs hardware: `app.simulate` plays the part of the glasses.

```
backend/     FastAPI + SQLite. Caregiver API, device API, escalation, missed-dose sweeper, tests
dashboard/   React + Vite caregiver dashboard
```

## Run it (Windows PowerShell)

You need Python 3.10 or newer and Node 18 or newer. Use three PowerShell windows.

**Window 1: backend**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload
```

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.

`app.seed` prints a **device key** once. Copy it. To start over, stop the server, delete `backend\smartvision.db`, and seed again.

**Window 2: dashboard**

```powershell
cd dashboard
npm install
npm run dev
```

Open http://localhost:5173 and sign in with `demo@smartvision.test` / `demo-password-1`.

**Window 3: pretend to be the glasses**

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.simulate --key sv_PASTE_YOUR_KEY heartbeat --battery 80
python -m app.simulate --key sv_PASTE_YOUR_KEY fall
python -m app.simulate --key sv_PASTE_YOUR_KEY fall --unworn
python -m app.simulate --key sv_PASTE_YOUR_KEY sos
python -m app.simulate --key sv_PASTE_YOUR_KEY took --schedule 1
python -m app.simulate --key sv_PASTE_YOUR_KEY location --lat 17.385 --lon 78.4867
python -m app.simulate --key sv_PASTE_YOUR_KEY prompts --since 0
```

Things to try:

1. `heartbeat`, then watch the Glasses panel go online.
2. `fall`. The page turns red within five seconds, an SMS is logged to the first contact in the backend window, and it moves up to the next contact every two minutes until you press "I'm on it" on the Alerts page.
3. `fall --unworn`. It is recorded but nobody is alerted, because frames lying on a table are not a fall.
4. Add a medicine on the Medication page for a time that has already passed. Within 30 seconds of its window closing, the dashboard shows "missed a dose".
5. On the Setup page, scroll to "Add another person" and add someone whose language is Telugu (the demo wearer, Lakshmi, hears English). The page switches to them. Then on the Prompts page type a message and press "Translate and check". Until a translator is connected (next section) this stops with a clear message, and nothing is saved.

## Connect a translator (for messages in other languages)

Without this, everything else works. You can still write a prompt directly in the wearer's language, and medicine prompts use their reviewed templates. Only the free-text messages need translation.

The default is [Sarvam](https://docs.sarvam.ai), which is built for Indian languages. New accounts get some free credit; check the pricing page for what it covers and for how long.

1. Create an account at [docs.sarvam.ai](https://docs.sarvam.ai) and make an API key from the dashboard.
2. In the `backend` folder, copy `.env.example` to `.env` and fill it in:

```
copy .env.example .env
notepad .env
```

```
TRANSLATOR_PROVIDER=sarvam
SARVAM_API_KEY=paste-your-key-here
```

3. Stop the backend with Ctrl+C and start it again with `uvicorn app.main:app --reload`. The `.env` file is read only at startup. Keep it private, never paste it into a chat, and never commit it.

Save the file as plain text. If you create it with `echo ... > .env` in PowerShell it is saved as UTF-16; the backend copes with that, but Notepad is the safer choice.

If the backend cannot translate, the Prompts page says why: no key set, key rejected, limit reached, or the service could not be reached. Nothing is saved in those cases.

How it behaves: you write a message, the backend translates it into the wearer's language and translates that back into yours, and you see both. You can edit the wording and press "Check my edit". Only when you press "Save this wording" does it reach the glasses. The server refuses to save a machine translation that was not sent back by a caregiver. Only the prompt text is sent to the translation service, never medicine prompts, health information or names of contacts. Messages are limited to 2000 characters, and the dashboard allows 500.

Machine translation of Telugu, Hindi and the other languages has not been checked by a fluent speaker for this project. Have one read the results before the glasses are used for real.

### Using Azure Translator instead

Set `TRANSLATOR_PROVIDER=azure`, then `AZURE_TRANSLATOR_KEY` and `AZURE_TRANSLATOR_REGION` (for example `centralindia`) from your Translator resource's **Keys and Endpoint** page in the Azure portal. The free F0 tier includes 2 million characters a month. With `TRANSLATOR_PROVIDER` empty, the backend uses whichever key is filled in, Sarvam first. `none` turns translation off.

## Spoken prompts

The glasses play recorded audio, so each prompt is also turned into a speech file. It uses the same Sarvam key as translation, so there is nothing more to set up: with `SARVAM_API_KEY` in `backend/.env`, speech is on.

- **Hear it before you save it.** On the Prompts page, **Listen in Telugu** (or whichever language the wearer hears) plays the wording in the box, including your edits. The recording you hear is the one that gets saved.
- **Saving makes the voice.** If the voice cannot be made (no key, no credit, no connection), the words are still saved and the page says why. **Listen** on that prompt tries again, and the glasses ask for it when they need it.
- **Changing the wording** makes a new recording. The old one is never played for new wording.
- **Languages with a voice:** English, Hindi, Bengali, Gujarati, Kannada, Malayalam, Marathi, Odia, Punjabi, Tamil and Telugu. Urdu and the others are text only for now, and the page says so.
- **Cost:** Sarvam charged about ₹30 per 10,000 characters for the default voice when this was written, so a short prompt is a fraction of a rupee. Check [Sarvam's pricing](https://www.sarvam.ai/api-pricing) for current rates.

Choosing a voice: the default is `shubh` at a slightly slow pace (0.9), which is easier to follow. Sarvam's own picks for Telugu are `shubh`, `ratan` (male) and `neha`, `priya` (female). Listen to the samples on Sarvam's voices page, then set one in `backend/.env` and restart the backend:

```
SARVAM_TTS_SPEAKER=priya
SARVAM_TTS_PACE=0.85
```

Voice quality varies by language, so have a Telugu speaker listen to the prompts you plan to use. To turn speech off, set `SPEECH_PROVIDER=none`.

The database gains one new table (`prompt_audio`) the first time the backend starts. Nothing else changes and your data stays.

## Tests and checks

One command runs everything (backend tests, then the dashboard build). From the project folder:

```powershell
.\scripts\check.ps1
```

On Linux or macOS use `scripts/check.sh`. The same checks run on GitHub for every push (`.github/workflows/ci.yml`, Python 3.10 and 3.13). To run only the backend tests:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

## Rules the system enforces

- **Wear-aware alerts.** The glasses decide whether they are being worn. They send `fall_confirmed` only when worn and `fall_suppressed` otherwise. The server records the second and never alerts on it.
- **Escalation.** `fall_confirmed` and `sos` start at tier 1 (SMS to the priority 1 contact) and climb one tier every `ESCALATION_SECONDS` (120) until acknowledged, up to tier 3 (SMS and call). A failing SMS provider never blocks an alert.
- **Doses.** Times are in the wearer's time zone. A dose is taken if a `med_taken` arrives from one hour before the time until the window closes, otherwise the server records `med_missed` and warns once. Devices cannot send `med_missed`.
- **Medicine wording is never machine translated.** Prompts about taking medicine must use a reviewed template, and only English is reviewed so far. Other prompts can be machine translated, but only after the caregiver has read the result: `POST /prompts/preview` translates without saving, and `POST /prompts` rejects a translated message that arrives without the reviewed text. With no key configured the preview answers 503 and the dashboard says why.
- **Device keys** are shown once and stored hashed. Caregivers only ever see their own wearers; a stranger's id returns 404.

## Device API (what the firmware will call)

All requests carry the header `X-Device-Key`.

| Call | Purpose |
| --- | --- |
| `POST /api/device/heartbeat` | `{battery_pct, worn}`; marks the device online |
| `POST /api/device/events` | `{type, payload, schedule_id?, occurred_at?}` where type is `fall_confirmed`, `fall_suppressed`, `fall_cancelled`, `sos`, `med_taken`, `med_mismatch`, `obstacle` or `location` |
| `GET /api/device/schedule` | Active medicine schedule |
| `GET /api/device/prompts?since_version=N` | Prompts changed since version N; store the returned `version` |
| `GET /api/device/prompts/{key}/audio` | The prompt as a 16 kHz mono WAV. Send `If-None-Match` with the last `ETag` to get a 304 instead of downloading it again. Each prompt in the list above has `audio_ready` |

Interactive docs for every endpoint are at http://localhost:8000/docs while the backend runs.

## Settings

Environment variables, or lines in `backend/.env`. All are optional for local use: `DATABASE_URL` (a Postgres URL works), `JWT_SECRET` (**set this before deploying**), `ESCALATION_SECONDS`, `MAX_ESCALATION_TIER`, `SWEEP_INTERVAL_SECONDS`, `DEVICE_ONLINE_SECONDS`, `CORS_ORIGINS`, `TRANSLATOR_PROVIDER` (`sarvam`, `azure` or `none`), `SARVAM_API_KEY`, `SARVAM_ENDPOINT`, `SARVAM_MODEL`, `SPEECH_PROVIDER` (`sarvam` or `none`), `SARVAM_TTS_MODEL`, `SARVAM_TTS_SPEAKER`, `SARVAM_TTS_PACE`, `SARVAM_TTS_SAMPLE_RATE`, `AZURE_TRANSLATOR_KEY`, `AZURE_TRANSLATOR_REGION`, `AZURE_TRANSLATOR_ENDPOINT`.

## Not built yet

- A real SMS and voice provider. `LogNotifier` only logs; implement the `Notifier` protocol in `app/escalation.py` and call `set_notifier`.
- Human-reviewed dose templates in Hindi and Telugu. Until a fluent speaker and a pharmacist have checked them, medicine prompts only exist in English. Another translation provider (for example Bhashini) can be added as one more class behind the `Translator` protocol in `app/translation.py`, plus one branch in `build_translator`.
- The Sarvam translation and speech adapters were tested against a simulated Sarvam server, not the real one, and Sarvam does not document its error replies. On first use with a real key, try one good message and one with a wrong key, and check that the messages make sense. If Listen fails with a message about `SARVAM_TTS_MODEL` or `SARVAM_TTS_SPEAKER`, change that voice or model name in `backend/.env`; the backend window shows what Sarvam replied.
- Hosting with HTTPS, and a production database.
- Firmware, the fall model, and medicine-packaging recognition. These are the next phases.
