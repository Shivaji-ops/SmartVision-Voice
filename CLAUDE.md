# Smart Vision (AU Smart Vision)

Caregiver backend and dashboard for AI smart eyewear for elderly people. FastAPI + SQLite backend, React + Vite dashboard. The glasses will talk to the device API; there is no firmware yet, `app.simulate` plays the glasses. See README.md for how everything works.

```
backend/     FastAPI app, tests (pytest)
dashboard/   React + Vite caregiver dashboard
scripts/     check.sh / check.ps1: the one command that runs every check
```

## Definition of done (any change that touches code)

1. Add or update tests together with the change.
2. Run `scripts/check.sh` (Windows: `.\scripts\check.ps1`). It runs the backend tests and the dashboard build. Never report a change as done while it fails.
3. If the change affects what a person sees, also drive the page in a real browser (Playwright is installed in the cloud container), including the error path. A passing build does not prove the page works.
4. Commit in small steps as the repo owner: `git config user.name "Shivaji-ops"` and `git config user.email "dosalashivaji@gmail.com"` (the email on the GitHub account Shivaji-ops). Write a message that says what and why, and push to `main`. Then confirm the GitHub Actions run for the push is green and fix it if not.
5. Send one PushNotification at the end (under 200 characters): what was done today and the check result, for example "Smart Vision: added X. 111 tests and the build pass, pushed." If something failed or needs the user, lead with that.
6. In the final reply say what changed, what was verified, and what was NOT verified.

## Rules that must not break

- Never commit `.env`, `*.db`, API keys or device keys. Keys live only in `backend/.env`.
- Medicine and dose prompts are never machine translated. They use reviewed templates only (only English is reviewed). Free-text translations are saved only after a caregiver has reviewed them; the server enforces this and tests cover it.
- Existing databases must keep working. Add new tables; never change an existing table (`create_all` only adds tables).
- Tests stay offline (`backend/tests/conftest.py`). No real keys, no real network in tests.
- Be honest about reach: the Sarvam translation and speech adapters have only been run against a simulated server unless this file says otherwise.

## Working with the user

- The user is on Windows. Give PowerShell-compatible commands. When code is requested, give complete files, not fragments.
- No emojis in the dashboard.

## Commands

```
cd backend;   python -m venv .venv; pip install -r requirements.txt; python -m pytest -q; uvicorn app.main:app --reload
cd dashboard; npm ci; npm run dev; npm run build
```
