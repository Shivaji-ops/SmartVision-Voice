"""Runtime settings, read once from environment variables.

Defaults are for local development only. Set JWT_SECRET and DATABASE_URL
before deploying anywhere reachable from the internet.

Secrets such as the translator key can go in backend/.env (one KEY=value per
line). Real environment variables win over the file.
"""
import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    try:
        raw = path.read_bytes()
    except OSError:
        return
    # Windows PowerShell's `echo X=y > .env` writes UTF-16; Notepad may add a UTF-8 BOM.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", errors="replace")
    else:
        text = raw.decode("utf-8-sig", errors="replace")
    # A name can appear twice, for example an empty `KEY=` left from .env.example and the
    # real one added below it. The last line with a value wins; an empty line never
    # replaces a value.
    found: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if value or name not in found:
            found[name] = value
    for name, value in found.items():
        os.environ.setdefault(name, value)


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./smartvision.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-secret-change-before-deploying-0123456789")
    jwt_minutes: int = int(os.getenv("JWT_MINUTES", "720"))
    # A critical alert that nobody acknowledges moves up one tier this often.
    escalation_seconds: int = int(os.getenv("ESCALATION_SECONDS", "120"))
    max_escalation_tier: int = int(os.getenv("MAX_ESCALATION_TIER", "3"))
    sweep_interval_seconds: int = int(os.getenv("SWEEP_INTERVAL_SECONDS", "30"))
    # A device that has not been heard from for this long shows as offline.
    device_online_seconds: int = int(os.getenv("DEVICE_ONLINE_SECONDS", "180"))
    cors_origins: tuple = tuple(
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    )
    # Machine translation for free-text prompts. TRANSLATOR_PROVIDER is "sarvam", "azure" or
    # "none". Leave it empty to use whichever provider has a key (Sarvam first). With no key
    # at all the dashboard simply says translation is not set up.
    translator_provider: str = os.getenv("TRANSLATOR_PROVIDER", "").strip().lower()
    sarvam_api_key: str = os.getenv("SARVAM_API_KEY", "").strip()
    sarvam_endpoint: str = os.getenv("SARVAM_ENDPOINT", "https://api.sarvam.ai").strip()
    sarvam_model: str = os.getenv("SARVAM_MODEL", "sarvam-translate:v1").strip()
    # Spoken prompts (text to speech). SPEECH_PROVIDER is "sarvam" or "none"; empty means
    # use Sarvam when SARVAM_API_KEY is set. The voice is a Sarvam speaker name; audition
    # them on Sarvam's voices page. A slower pace is easier to follow.
    speech_provider: str = os.getenv("SPEECH_PROVIDER", "").strip().lower()
    sarvam_tts_model: str = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3").strip()
    sarvam_tts_speaker: str = os.getenv("SARVAM_TTS_SPEAKER", "shubh").strip().lower()
    sarvam_tts_pace: float = float(os.getenv("SARVAM_TTS_PACE", "0.9"))
    sarvam_tts_sample_rate: int = int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "16000"))
    azure_translator_key: str = os.getenv("AZURE_TRANSLATOR_KEY", "").strip()
    azure_translator_region: str = os.getenv("AZURE_TRANSLATOR_REGION", "").strip()
    azure_translator_endpoint: str = os.getenv(
        "AZURE_TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com"
    ).strip()


settings = Settings()
