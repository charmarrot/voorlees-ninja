"""Centrale configuratie en padbeheer voor Voorlees Ninja."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import secrets
import tempfile
from pathlib import Path

log = logging.getLogger("voorlees.config")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"


def _env(name: str, default: str = "") -> str:
  return (os.getenv(name) or default).strip()


def _pick_data_dir() -> Path:
  """Kiest de eerste schrijfbare datamap.

  In de container mount Coolify een volume op /data. Draai je lokaal, dan
  valt hij terug op ./data naast de projectmap.
  """
  candidates = [_env("DATA_DIR"), "/data", str(BASE_DIR.parent / "data")]
  for candidate in candidates:
    if not candidate:
      continue
    path = Path(candidate)
    try:
      path.mkdir(parents=True, exist_ok=True)
      probe = path / ".schrijftest"
      probe.write_text("ok", encoding="utf-8")
      probe.unlink()
      return path
    except OSError as exc:
      log.warning("Datamap %s niet bruikbaar: %s", path, exc)
  raise RuntimeError("Geen schrijfbare datamap gevonden (zet DATA_DIR).")


DATA_DIR = _pick_data_dir()
STORIES_DIR = DATA_DIR / "stories"
STORIES_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_PATH = DATA_DIR / "profiel.json"

# --- Google Cloud -----------------------------------------------------------
GCP_PROJECT_ID = _env("GCP_PROJECT_ID", "voorlees-ninja-506310")
GCP_LOCATION = _env("GCP_LOCATION", "us-central1")
TEXT_MODEL = _env("TEXT_MODEL", "gemini-2.5-flash")
IMAGE_MODEL = _env("IMAGE_MODEL", "gemini-2.5-flash-image")
# Experimenteel: laat een liedje ook echt zingen via Google's Lyria. Staat
# bij Google zelf nog in preview; werkt dus mogelijk niet op elk project.
MUSIC_MODEL = _env("MUSIC_MODEL", "lyria-3-pro-preview")
# Lyria staat (nog) niet overal waar de tekst- en beeldmodellen wel staan --
# Google's eigen voorbeeldnotebook gebruikt hiervoor "global" in plaats van
# een gewone regio zoals us-central1. Apart instelbaar, zodat een verkeerde
# gok voor Lyria niet de rest van de app kan raken.
MUSIC_LOCATION = _env("MUSIC_LOCATION", "global")

# --- App --------------------------------------------------------------------
APP_PIN = _env("APP_PIN")
SECRET_KEY = _env("SECRET_KEY")
if not SECRET_KEY:
  SECRET_KEY = secrets.token_hex(32)
  if APP_PIN:
    log.warning(
        "SECRET_KEY niet gezet: er is een tijdelijke gegenereerd. Iedereen"
        " moet na een herstart opnieuw de pincode invoeren."
    )

SESSION_DAYS = int(_env("SESSION_DAYS", "60"))
MAX_STORIES_PER_DAY = int(_env("MAX_STORIES_PER_DAY", "25"))
DEFAULT_VOICE = _env("TTS_VOICE", "nl-NL-Wavenet-E")

DEFAULT_PROFILE: dict = {
    "naam": "Leo",
    "leeftijd": 3,
    "plaats": "Rotterdam",
    "uiterlijk": (
        "a cheerful toddler boy with short wavy brown hair, big brown eyes,"
        " rosy cheeks, wearing a blue-and-white striped shirt and a dark blue"
        " cap"
    ),
    "favorieten": "trams, kranen, boten, PAW Patrol",
    "stem": DEFAULT_VOICE,
    "tempo": 0.9,
}


def bootstrap_credentials() -> None:
  """Zet de service-account key klaar voor de Google-clients.

  Voorkeursvolgorde:
    1. GCP_SA_JSON   -- de volledige key-JSON (of base64 daarvan) als secret.
    2. GCP_KEY_PATH  -- pad naar een gemount keybestand.
    3. Application Default Credentials (bv. Workload Identity).
  """
  raw = os.getenv("GCP_SA_JSON", "").strip()
  if raw:
    if not raw.startswith("{"):
      try:
        raw = base64.b64decode(raw, validate=True).decode("utf-8")
      except (binascii.Error, UnicodeDecodeError) as exc:
        raise RuntimeError(
            "GCP_SA_JSON is geen geldige JSON en ook geen geldige base64."
        ) from exc
    try:
      json.loads(raw)
    except json.JSONDecodeError as exc:
      raise RuntimeError("GCP_SA_JSON bevat geen geldige JSON.") from exc

    handle, path = tempfile.mkstemp(prefix="gcp_key_", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
      fh.write(raw)
    os.chmod(path, 0o600)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
    log.info("Service-account key uit GCP_SA_JSON geladen.")
    return

  key_path = _env("GCP_KEY_PATH")
  if key_path and Path(key_path).is_file():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
    log.info("Service-account key gelezen van %s.", key_path)
    return

  log.info(
      "Geen expliciete key gevonden; ik val terug op Application Default"
      " Credentials."
  )
