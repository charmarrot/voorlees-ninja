"""Voorlees Ninja -- een webapp die bedtijdverhaaltjes maakt."""

from __future__ import annotations

import logging
import mimetypes
import re
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, config, gcp, story

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("voorlees")

@asynccontextmanager
async def levensloop(_: FastAPI):
  log.info("Voorlees Ninja start op. Datamap: %s", config.DATA_DIR)
  log.info(
      "Pincode %s ingesteld. Vertex-project: %s (%s).",
      "is" if auth.pin_vereist() else "is NIET",
      config.GCP_PROJECT_ID,
      config.GCP_LOCATION,
  )
  yield
  _werker.shutdown(wait=False)


app = FastAPI(
    title="Voorlees Ninja", docs_url=None, redoc_url=None, lifespan=levensloop
)
app.mount(
    "/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static"
)
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

# Eén verhaal tegelijk: dat houdt het geheugen laag en voorkomt
# quotameldingen bij de beeldgeneratie.
_werker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verhaal")
_taken: dict[str, dict] = {}
_taken_lock = threading.Lock()


def _zet_taak(taak_id: str, **velden) -> None:
  with _taken_lock:
    taak = _taken.setdefault(taak_id, {"id": taak_id})
    taak.update(velden)


def _lees_taak(taak_id: str) -> dict | None:
  with _taken_lock:
    taak = _taken.get(taak_id)
    return dict(taak) if taak else None


def _ruim_taken_op() -> None:
  with _taken_lock:
    if len(_taken) <= 40:
      return
    op_volgorde = sorted(_taken.values(), key=lambda t: t.get("gestart", ""))
    for taak in op_volgorde[:-20]:
      _taken.pop(taak["id"], None)


def _draai_taak(taak_id: str, idee: str, aantal_scenes: int) -> None:
  def meld(stap: str, pct: int) -> None:
    _zet_taak(taak_id, stap=stap, voortgang=pct)

  _zet_taak(taak_id, status="bezig", stap="Aan de beurt…", voortgang=2)
  try:
    verhaal = story.maak_verhaal(idee, aantal_scenes, meld)
    _zet_taak(
        taak_id, status="klaar", voortgang=100, verhaal=verhaal,
        stap="Klaar om voor te lezen!",
    )
  except Exception as exc:  # noqa: BLE001
    log.exception("Verhaal maken mislukt")
    _zet_taak(
        taak_id,
        status="mislukt",
        fout=_leesbare_fout(exc),
        stap="Er ging iets mis",
    )
  finally:
    _ruim_taken_op()


def _leesbare_fout(exc: Exception) -> str:
  tekst = str(exc) or exc.__class__.__name__
  laag = tekst.lower()
  if "quota" in laag or "429" in laag or "resource_exhausted" in laag:
    return (
        "Google zegt even nee (quotum bereikt). Probeer het over een paar"
        " minuten opnieuw."
    )
  if "permission" in laag or "403" in laag:
    return (
        "Geen toegang tot de Google-modellen. Controleer de service-account"
        " en of Vertex AI aanstaat."
    )
  if "credential" in laag or "default credentials" in laag:
    return "De Google-sleutel ontbreekt of klopt niet (GCP_SA_JSON)."
  if "not found" in laag and "model" in laag:
    return "Het gevraagde model bestaat niet in deze regio."
  return tekst[:300]


# --- Pagina's ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
  return templates.TemplateResponse(
      request,
      "index.html",
      {
          "pin_vereist": auth.pin_vereist(),
          "ingelogd": auth.is_ingelogd(request),
          "versie": _statische_versie(),
      },
  )


def _statische_versie() -> str:
  """Simpele cache-buster op basis van de laatste wijziging in /static."""
  try:
    nieuwste = max(
        p.stat().st_mtime for p in config.STATIC_DIR.rglob("*") if p.is_file()
    )
    return str(int(nieuwste))
  except ValueError:
    return "1"


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
  # De service worker moet vanaf de root geserveerd worden voor scope "/".
  return FileResponse(
      config.STATIC_DIR / "sw.js",
      media_type="application/javascript",
      headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
  )


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
  return FileResponse(
      config.STATIC_DIR / "manifest.webmanifest",
      media_type="application/manifest+json",
  )


@app.get("/vibecode-log.json", include_in_schema=False)
async def vibecode_log():
  """Publiek bouwlogboek voor de wekelijkse vibecode-review.

  Bewust buiten de pincode om: Cowork haalt dit bestand zonder inloggen op.
  Het bevat alleen commit-onderwerpregels -- nooit verhaalinhoud of iets uit
  de datamap.
  """
  pad = config.STATIC_DIR / "vibecode-log.json"
  if not pad.is_file():
    raise HTTPException(status_code=404, detail="Nog geen logboek gegenereerd")
  return FileResponse(
      pad,
      media_type="application/json",
      headers={"Cache-Control": "public, max-age=300"},
  )


@app.get("/healthz", include_in_schema=False)
async def healthz():
  return {"status": "ok", "verhalen": len(story.bibliotheek())}


# --- Toegang ----------------------------------------------------------------
@app.get("/api/status")
async def status(request: Request):
  ingelogd = auth.is_ingelogd(request)
  antwoord = {
      "pin_vereist": auth.pin_vereist(),
      "ingelogd": ingelogd,
  }
  if ingelogd:
    antwoord["profiel"] = story.lees_profiel()
    antwoord["vandaag"] = story.verhalen_vandaag()
    antwoord["dagmaximum"] = config.MAX_STORIES_PER_DAY
  return antwoord


@app.post("/api/login")
async def login(request: Request, pincode: str = Form(...)):
  antwoord = JSONResponse({"ok": True})
  if not auth.pin_vereist():
    return antwoord
  if not auth.probeer_login(request, antwoord, pincode):
    raise HTTPException(status_code=401, detail="Die pincode klopt niet.")
  return antwoord


@app.post("/api/logout")
async def logout():
  antwoord = JSONResponse({"ok": True})
  auth.uitloggen(antwoord)
  return antwoord


# --- Profiel en stemmen -----------------------------------------------------
@app.get("/api/profiel", dependencies=[Depends(auth.vereis_toegang)])
async def profiel_lezen():
  return story.lees_profiel()


@app.post("/api/profiel", dependencies=[Depends(auth.vereis_toegang)])
async def profiel_opslaan(nieuw: dict = Body(...)):
  if not isinstance(nieuw, dict):
    raise HTTPException(status_code=400, detail="Ongeldig profiel")
  return story.schrijf_profiel(nieuw)


@app.get("/api/stemmen", dependencies=[Depends(auth.vereis_toegang)])
async def stemmen():
  try:
    return {"stemmen": gcp.nederlandse_stemmen()}
  except Exception as exc:  # noqa: BLE001
    log.warning("Stemmen ophalen mislukt: %s", exc)
    return {"stemmen": [], "fout": _leesbare_fout(exc)}


# --- Bibliotheek ------------------------------------------------------------
@app.get("/api/verhalen", dependencies=[Depends(auth.vereis_toegang)])
async def verhalen():
  return {"verhalen": story.bibliotheek()}


@app.get("/api/verhalen/{verhaal_id}", dependencies=[Depends(auth.vereis_toegang)])
async def verhaal(verhaal_id: str):
  try:
    gevonden = story.lees_verhaal(verhaal_id)
  except ValueError:
    raise HTTPException(status_code=400, detail="Ongeldig verhaal-id")
  if not gevonden:
    raise HTTPException(status_code=404, detail="Verhaaltje niet gevonden")
  return gevonden


@app.post(
    "/api/verhalen/{verhaal_id}/favoriet",
    dependencies=[Depends(auth.vereis_toegang)],
)
async def favoriet(verhaal_id: str, gegevens: dict = Body(default={})):
  try:
    bijgewerkt = story.markeer_favoriet(
        verhaal_id, bool(gegevens.get("favoriet", True))
    )
  except ValueError:
    raise HTTPException(status_code=400, detail="Ongeldig verhaal-id")
  if not bijgewerkt:
    raise HTTPException(status_code=404, detail="Verhaaltje niet gevonden")
  return {"ok": True, "favoriet": bijgewerkt["favoriet"]}


@app.delete(
    "/api/verhalen/{verhaal_id}", dependencies=[Depends(auth.vereis_toegang)]
)
async def verwijder(verhaal_id: str):
  try:
    weg = story.verwijder_verhaal(verhaal_id)
  except ValueError:
    raise HTTPException(status_code=400, detail="Ongeldig verhaal-id")
  if not weg:
    raise HTTPException(status_code=404, detail="Verhaaltje niet gevonden")
  return {"ok": True}


# --- Genereren --------------------------------------------------------------
@app.post("/api/genereer", dependencies=[Depends(auth.vereis_toegang)])
async def genereer(gegevens: dict = Body(...)):
  idee = str(gegevens.get("prompt") or "").strip()
  if len(idee) < 3:
    raise HTTPException(
        status_code=400, detail="Vertel eerst waar het verhaaltje over gaat."
    )
  if len(idee) > 500:
    idee = idee[:500]

  try:
    aantal_scenes = int(gegevens.get("scenes", 4))
  except (TypeError, ValueError):
    aantal_scenes = 4
  aantal_scenes = max(3, min(8, aantal_scenes))

  if story.verhalen_vandaag() >= config.MAX_STORIES_PER_DAY:
    raise HTTPException(
        status_code=429,
        detail=(
            f"Er zijn vandaag al {config.MAX_STORIES_PER_DAY} verhaaltjes"
            " gemaakt. Morgen mag het weer!"
        ),
    )

  taak_id = secrets.token_hex(8)
  _zet_taak(
      taak_id,
      status="wachtrij",
      stap="In de wachtrij…",
      voortgang=0,
      prompt=idee,
      gestart=datetime.now(timezone.utc).isoformat(timespec="seconds"),
  )
  _werker.submit(_draai_taak, taak_id, idee, aantal_scenes)
  return {"taak_id": taak_id}


@app.get("/api/taken/{taak_id}", dependencies=[Depends(auth.vereis_toegang)])
async def taak(taak_id: str):
  gevonden = _lees_taak(taak_id)
  if not gevonden:
    raise HTTPException(status_code=404, detail="Taak niet gevonden")
  return gevonden


# --- Mediabestanden ---------------------------------------------------------
_BESTAND = re.compile(r"[0-9a-zA-Z._-]{1,64}")


@app.get("/media/{verhaal_id}/{bestand}", dependencies=[Depends(auth.vereis_toegang)])
async def media(verhaal_id: str, bestand: str):
  if not _BESTAND.fullmatch(bestand) or bestand.startswith("."):
    raise HTTPException(status_code=400, detail="Ongeldige bestandsnaam")
  try:
    pad: Path = story.verhaal_map(verhaal_id) / bestand
  except ValueError:
    raise HTTPException(status_code=400, detail="Ongeldig verhaal-id")
  if not pad.is_file():
    raise HTTPException(status_code=404, detail="Bestand niet gevonden")
  soort = mimetypes.guess_type(pad.name)[0] or "application/octet-stream"
  return FileResponse(
      pad,
      media_type=soort,
      headers={"Cache-Control": "public, max-age=31536000, immutable"},
  )
