"""Verhaalgeneratie: tekst, illustraties, stem en opslag op schijf."""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import config, gcp

log = logging.getLogger("voorlees.story")

Voortgang = Callable[[str, int], None]

STIJL = (
    "children's picture book illustration, friendly 3D cartoon style,"
    " soft warm lighting, vibrant but gentle colours, clean rounded shapes,"
    " clear outlines, cosy bedtime atmosphere, no text, no letters,"
    " no speech bubbles"
)

_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


# --- Profiel ----------------------------------------------------------------
def lees_profiel() -> dict:
  profiel = dict(config.DEFAULT_PROFILE)
  if config.PROFILE_PATH.is_file():
    try:
      opgeslagen = json.loads(config.PROFILE_PATH.read_text(encoding="utf-8"))
      if isinstance(opgeslagen, dict):
        profiel.update({k: v for k, v in opgeslagen.items() if v not in (None, "")})
    except (OSError, json.JSONDecodeError) as exc:
      log.warning("Profiel niet leesbaar, ik gebruik de standaard: %s", exc)
  return profiel


def schrijf_profiel(nieuw: dict) -> dict:
  profiel = lees_profiel()
  toegestaan = set(config.DEFAULT_PROFILE)
  profiel.update({k: v for k, v in nieuw.items() if k in toegestaan})
  try:
    profiel["leeftijd"] = max(1, min(12, int(profiel.get("leeftijd", 3))))
  except (TypeError, ValueError):
    profiel["leeftijd"] = 3
  try:
    profiel["tempo"] = max(0.6, min(1.3, round(float(profiel.get("tempo", 0.9)), 2)))
  except (TypeError, ValueError):
    profiel["tempo"] = 0.9
  config.PROFILE_PATH.write_text(
      json.dumps(profiel, ensure_ascii=False, indent=2), encoding="utf-8"
  )
  return profiel


# --- Tekst ------------------------------------------------------------------
def _systeem_prompt(profiel: dict, aantal_scenes: int) -> str:
  naam = profiel.get("naam", "Leo")
  leeftijd = profiel.get("leeftijd", 3)
  plaats = profiel.get("plaats", "Rotterdam")
  uiterlijk = profiel.get("uiterlijk", "")
  favorieten = profiel.get("favorieten", "")

  return f"""
Je bent een warme, fantasierijke kinderboekenschrijver. Je schrijft een
bedtijdverhaal voor {naam}, een kind van {leeftijd} jaar uit {plaats}.
{naam} houdt van: {favorieten}.

REGELS VOOR HET VERHAAL
- Precies {aantal_scenes} scènes, die samen één doorlopend verhaal vormen met
  een begin, een klein spannend moment en een geruststellend, slaperig einde.
- {naam} is altijd de hoofdpersoon en lost het samen met anderen op.
- Eenvoudige, korte zinnen. Woorden die een kind van {leeftijd} begrijpt.
- Maximaal twee zinnen per scène, hardop voorlezen duurt ongeveer 10 seconden.
- Vrolijk en veilig: geen echt gevaar, geen enge figuren, geen verdriet aan het
  eind. Kleine spanning mag, maar die wordt in dezelfde of de volgende scène
  opgelost.
- De laatste scène is rustig: {naam} gaat tevreden slapen of komt veilig thuis.
- Verwerk herkenbare details uit {plaats} als dat past bij het idee.
- Schrijf in het Nederlands, zonder emoji's.

REGELS VOOR DE BEELDPROMPT (beeld_prompt)
- Schrijf die in het Engels, want die gaat naar een tekenmodel.
- Beschrijf in ELKE beeldprompt het hoofdpersoon opnieuw voluit:
  "{uiterlijk}".
- Beschrijf één duidelijk tafereel: wie, waar, welke handeling, welk moment van
  de dag. Noem ook het camerastandpunt (close-up, wide shot, from above).
- Geen tekst, letters of cijfers in het beeld.
- Houd decor, kleding en stijl consistent over alle scènes.

ANTWOORDFORMAAT
Geef UITSLUITEND een geldig JSON-object terug, zonder uitleg eromheen:
{{
  "titel": "Korte, vrolijke titel van maximaal 6 woorden",
  "scenes": [
    {{
      "scene_nr": 1,
      "tekst": "Twee korte zinnen in het Nederlands.",
      "beeld_prompt": "English image description including the full character description."
    }}
  ]
}}
""".strip()


def _parse_json(tekst: str) -> dict:
  tekst = (tekst or "").strip()
  if tekst.startswith("```"):
    tekst = re.sub(r"^```[a-zA-Z]*\s*", "", tekst)
    tekst = re.sub(r"\s*```$", "", tekst)
  try:
    return json.loads(tekst)
  except json.JSONDecodeError:
    start, eind = tekst.find("{"), tekst.rfind("}")
    if start != -1 and eind > start:
      return json.loads(tekst[start : eind + 1])
    raise


def genereer_tekst(idee: str, profiel: dict, aantal_scenes: int) -> dict:
  """Laat Gemini het verhaal en de beeldconcepten schrijven."""
  from google.genai import types

  def _aanroep():
    return gcp.genai_client().models.generate_content(
        model=config.TEXT_MODEL,
        contents=[f"Verhaalidee: {idee}"],
        config=types.GenerateContentConfig(
            system_instruction=_systeem_prompt(profiel, aantal_scenes),
            response_mime_type="application/json",
            temperature=0.9,
            top_p=0.95,
            max_output_tokens=4096,
        ),
    )

  antwoord = gcp.with_retries(_aanroep, omschrijving="Verhaal schrijven")
  data = _parse_json(antwoord.text)

  scenes = data.get("scenes") or []
  if not isinstance(scenes, list) or not scenes:
    raise RuntimeError("Het model gaf geen scènes terug.")

  opgeschoond = []
  for index, scene in enumerate(scenes[:aantal_scenes], start=1):
    tekst = str(scene.get("tekst", "")).strip()
    beeld = str(scene.get("beeld_prompt", "")).strip()
    if not tekst:
      continue
    opgeschoond.append({"nr": index, "tekst": tekst, "beeld_prompt": beeld})
  if not opgeschoond:
    raise RuntimeError("Het model gaf lege scènes terug.")

  return {
      "titel": str(data.get("titel") or "Een nieuw avontuur").strip(),
      "scenes": opgeschoond,
  }


# --- Slaapliedje ------------------------------------------------------------
def genereer_liedje(verhaal: dict, profiel: dict) -> dict:
  """Schrijft een slaapliedje bij een bestaand verhaal.

  De uitvoer is bedoeld om rechtstreeks in Suno (of Gemini met muziek) te
  plakken: Nederlandse songtekst met blokhaken, en een losse stijlregel in
  het Engels, want daar reageren die modellen beter op.
  """
  from google.genai import types

  naam = profiel.get("naam", "Leo")
  leeftijd = profiel.get("leeftijd", 3)
  verhaaltje = " ".join(scene["tekst"] for scene in verhaal.get("scenes", []))

  systeem = f"""
Je schrijft slaapliedjes voor {naam}, een kind van {leeftijd} jaar. Je krijgt
een bedtijdverhaal en maakt daar een liedje van dat je vlak voor het slapen
zingt.

REGELS VOOR DE SONGTEKST
- Nederlands, eenvoudige woorden die een kind van {leeftijd} begrijpt.
- Korte regels van hooguit acht woorden, met een duidelijk rijm.
- Deze opbouw, met de blokhaken er letterlijk bij:
  [Intro], [Vers 1], [Refrein], [Vers 2], [Refrein], [Brug], [Refrein], [Outro]
- Het refrein is elke keer hetzelfde, komt de naam {naam} in voor, en is kort
  genoeg om mee te zingen.
- Vers 1 en 2 vertellen het avontuur uit het verhaal na; de brug en de outro
  worden rustig en slaperig en brengen {naam} naar bed.
- Geen emoji's, geen aanwijzingen tussen haakjes behalve de blokhaken.

REGELS VOOR DE STIJLREGEL
- In het Engels, want die gaat naar het muziekmodel.
- Eén regel, hooguit 20 woorden: genre, instrumenten, stem, tempo en sfeer.
- Altijd rustig en zacht -- dit is een slaapliedje, geen kinderdisco.

ANTWOORDFORMAAT
Geef UITSLUITEND geldig JSON terug:
{{
  "titel": "Titel van het liedje, maximaal 5 woorden",
  "stijl": "soft Dutch lullaby, gentle fingerpicked guitar, warm female voice, slow 6/8, music box",
  "tekst": "[Intro]\\nregel\\n\\n[Vers 1]\\nregel\\nregel"
}}
""".strip()

  def _aanroep():
    return gcp.genai_client().models.generate_content(
        model=config.TEXT_MODEL,
        contents=[
            f"Titel van het verhaal: {verhaal.get('titel', '')}\n"
            f"Het verhaal: {verhaaltje}"
        ],
        config=types.GenerateContentConfig(
            system_instruction=systeem,
            response_mime_type="application/json",
            temperature=1.0,
            max_output_tokens=2000,
        ),
    )

  antwoord = gcp.with_retries(_aanroep, omschrijving="Liedje schrijven")
  data = _parse_json(antwoord.text)

  tekst = str(data.get("tekst", "")).strip()
  if len(tekst) < 40:
    raise RuntimeError("Het model gaf geen bruikbare songtekst terug.")

  return {
      "titel": str(data.get("titel") or verhaal.get("titel", "Slaapliedje")).strip(),
      "stijl": str(
          data.get("stijl")
          or "soft Dutch lullaby, gentle acoustic guitar, warm voice, slow tempo"
      ).strip(),
      "tekst": tekst,
      "gemaakt_op": datetime.now(timezone.utc).isoformat(timespec="seconds"),
  }


def liedje_voor(verhaal_id: str, vernieuw: bool = False) -> dict | None:
  """Haalt het bewaarde liedje op, of schrijft er een nieuw."""
  verhaal = lees_verhaal(verhaal_id)
  if not verhaal:
    return None
  if verhaal.get("liedje") and not vernieuw:
    return verhaal["liedje"]

  liedje = genereer_liedje(verhaal, lees_profiel())
  verhaal["liedje"] = liedje
  _bewaar(verhaal)
  return liedje


# --- Suggesties -------------------------------------------------------------
SUGGESTIES_PATH_NAAM = "suggesties.json"
SUGGESTIES_GELDIG_UREN = 20
_laatste_suggestie_ronde = 0.0


def _suggesties_pad() -> Path:
  return config.DATA_DIR / SUGGESTIES_PATH_NAAM


def _profiel_sleutel(profiel: dict) -> str:
  """Verandert zodra iets meespeelt in de ideeën, zodat de cache vervalt."""
  return "|".join(
      str(profiel.get(veld, ""))
      for veld in ("naam", "leeftijd", "plaats", "favorieten")
  )


def genereer_suggesties(profiel: dict, vermijd: list[str], aantal: int = 8) -> list[dict]:
  """Laat Gemini een handvol frisse verhaalideeën verzinnen."""
  from google.genai import types

  naam = profiel.get("naam", "Leo")
  leeftijd = profiel.get("leeftijd", 3)
  plaats = profiel.get("plaats", "Rotterdam")
  favorieten = profiel.get("favorieten", "")
  eerder = ", ".join(vermijd[:24]) or "nog niets"

  systeem = f"""
Je verzint korte ideeën voor bedtijdverhalen voor {naam}, een kind van
{leeftijd} jaar uit {plaats}. {naam} houdt van: {favorieten}.

Geef precies {aantal} ideeën, allemaal verschillend van elkaar. Zorg voor
variatie: iets uit {plaats}, iets met dieren, iets met voertuigen, iets uit
het dagelijks leven (bad, tandenpoetsen, boodschappen), iets met het weer of
een seizoen, en iets fantasievols. Alles vrolijk en veilig — niets engs.

Vermijd ideeën die lijken op: {eerder}.

Elk idee bestaat uit:
- "emoji": één passende emoji.
- "label": maximaal 4 woorden, zoals het op een knopje staat.
- "idee": één zin van 8 tot 16 woorden die begint met "{naam} " en vertelt
  wat er gebeurt.

Antwoord UITSLUITEND met geldige JSON:
{{"suggesties": [{{"emoji": "🚋", "label": "Tram over de brug",
  "idee": "{naam} rijdt met tram 3 over de brug en zwaait naar alle boten"}}]}}
""".strip()

  def _aanroep():
    return gcp.genai_client().models.generate_content(
        model=config.TEXT_MODEL,
        contents=["Verzin nieuwe ideeën."],
        config=types.GenerateContentConfig(
            system_instruction=systeem,
            response_mime_type="application/json",
            temperature=1.2,
            top_p=0.97,
            max_output_tokens=1500,
        ),
    )

  antwoord = gcp.with_retries(
      _aanroep, pogingen=2, omschrijving="Suggesties verzinnen"
  )
  data = _parse_json(antwoord.text)

  schoon = []
  for item in (data.get("suggesties") or [])[:aantal]:
    label = str(item.get("label", "")).strip()
    idee = str(item.get("idee", "")).strip()
    emoji = str(item.get("emoji", "")).strip()[:4] or "✨"
    if not label or len(idee) < 12:
      continue
    schoon.append({"emoji": emoji, "label": label[:40], "idee": idee[:200]})
  if len(schoon) < 3:
    raise RuntimeError("Te weinig bruikbare suggesties terug.")
  return schoon


def lees_suggesties(vernieuw: bool = False) -> dict:
  """Ideeën uit de cache, of vers verzonnen als die verlopen is.

  Geeft een lege lijst terug als Google niet meewerkt; de app valt dan terug
  op haar eigen ingebouwde lijst.
  """
  global _laatste_suggestie_ronde

  profiel = lees_profiel()
  sleutel = _profiel_sleutel(profiel)
  pad = _suggesties_pad()
  bewaard: dict = {}
  if pad.is_file():
    try:
      bewaard = json.loads(pad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
      bewaard = {}

  vers_genoeg = False
  if bewaard.get("sleutel") == sleutel and bewaard.get("suggesties"):
    try:
      gemaakt = datetime.fromisoformat(bewaard["gemaakt_op"])
      ouderdom = (datetime.now(timezone.utc) - gemaakt).total_seconds() / 3600
      vers_genoeg = ouderdom < SUGGESTIES_GELDIG_UREN
    except (KeyError, ValueError):
      vers_genoeg = False

  if vers_genoeg and not vernieuw:
    return {"suggesties": bewaard["suggesties"], "bron": "cache"}

  # Rem tegen driftig tikken op "andere ideeën".
  nu = time.monotonic()
  if vernieuw and nu - _laatste_suggestie_ronde < 20:
    return {
        "suggesties": bewaard.get("suggesties", []),
        "bron": "cache",
        "wacht": True,
    }

  try:
    vermijd = [s.get("label", "") for s in bewaard.get("suggesties", [])]
    nieuw = genereer_suggesties(profiel, vermijd)
    _laatste_suggestie_ronde = nu
  except Exception as exc:  # noqa: BLE001
    log.warning("Suggesties verzinnen mislukt: %s", exc)
    return {"suggesties": bewaard.get("suggesties", []), "bron": "cache"}

  pad.write_text(
      json.dumps(
          {
              "sleutel": sleutel,
              "gemaakt_op": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "suggesties": nieuw,
          },
          ensure_ascii=False,
          indent=2,
      ),
      encoding="utf-8",
  )
  return {"suggesties": nieuw, "bron": "gemini"}


# --- Beeld ------------------------------------------------------------------
def genereer_afbeelding(
    prompt: str, doel_zonder_ext: Path, referentie: Path | None = None
) -> str:
  """Tekent één scène. Geeft de bestandsnaam terug.

  De vorige illustratie gaat als referentie mee, zodat het hoofdpersoon en de
  stijl door het hele boekje hetzelfde blijven.
  """
  from google.genai import types

  volledige_prompt = f"{prompt}. Style: {STIJL}."

  def _bouw_contents(met_referentie: bool):
    if met_referentie and referentie and referentie.is_file():
      mime = "image/png" if referentie.suffix == ".png" else "image/jpeg"
      return [
          types.Part.from_bytes(data=referentie.read_bytes(), mime_type=mime),
          (
              "Draw the next page of the same picture book. Keep exactly the"
              " same main character (same face, hair, clothing) and the same"
              " art style, colours and lighting as the reference image."
              f" New scene: {volledige_prompt}"
          ),
      ]
    return [volledige_prompt]

  def _teken(met_referentie: bool):
    return gcp.genai_client().models.generate_content(
        model=config.IMAGE_MODEL,
        contents=_bouw_contents(met_referentie),
    )

  antwoord = None
  if referentie and referentie.is_file():
    try:
      antwoord = gcp.with_retries(
          lambda: _teken(True), pogingen=2, omschrijving="Illustratie (vervolg)"
      )
    except Exception as exc:  # noqa: BLE001
      log.warning("Referentiebeeld werkte niet, ik teken zonder: %s", exc)
  if antwoord is None:
    antwoord = gcp.with_retries(
        lambda: _teken(False), omschrijving="Illustratie tekenen"
    )

  for kandidaat in antwoord.candidates or []:
    for deel in (kandidaat.content.parts if kandidaat.content else []) or []:
      data = getattr(deel, "inline_data", None)
      if data and data.data:
        ext = _MIME_EXT.get((data.mime_type or "").lower(), "png")
        doel = doel_zonder_ext.with_suffix(f".{ext}")
        doel.write_bytes(data.data)
        return doel.name

  raise RuntimeError("Het tekenmodel gaf geen afbeelding terug.")


# --- Stem -------------------------------------------------------------------
def genereer_audio(tekst: str, doel: Path, profiel: dict) -> None:
  """Spreekt een stukje tekst in met Cloud Text-to-Speech."""
  from google.cloud import texttospeech

  stem_naam = str(profiel.get("stem") or config.DEFAULT_VOICE)
  tempo = float(profiel.get("tempo") or 0.9)
  # Chirp-stemmen ondersteunen geen SSML en geen toonhoogte.
  eenvoudig = "chirp" in stem_naam.lower()

  if eenvoudig:
    invoer = texttospeech.SynthesisInput(text=tekst)
  else:
    veilig = (
        tekst.replace("&", "en")
        .replace("<", "")
        .replace(">", "")
    )
    veilig = re.sub(r"(?<=[.!?])\s+", '<break time="450ms"/> ', veilig)
    invoer = texttospeech.SynthesisInput(ssml=f"<speak>{veilig}</speak>")

  stem = texttospeech.VoiceSelectionParams(
      language_code="nl-NL", name=stem_naam
  )
  audio_config = texttospeech.AudioConfig(
      audio_encoding=texttospeech.AudioEncoding.MP3,
      speaking_rate=tempo,
      **({} if eenvoudig else {"pitch": -0.5}),
  )

  def _spreek(gekozen_stem, gekozen_invoer):
    return gcp.tts_client().synthesize_speech(
        input=gekozen_invoer, voice=gekozen_stem, audio_config=audio_config
    )

  try:
    antwoord = gcp.with_retries(
        lambda: _spreek(stem, invoer), pogingen=2, omschrijving="Inspreken"
    )
  except Exception as exc:  # noqa: BLE001
    log.warning(
        "Stem %s werkte niet (%s); ik val terug op %s.",
        stem_naam,
        exc,
        config.DEFAULT_VOICE,
    )
    terugval = texttospeech.VoiceSelectionParams(
        language_code="nl-NL", name=config.DEFAULT_VOICE
    )
    antwoord = gcp.with_retries(
        lambda: _spreek(terugval, texttospeech.SynthesisInput(text=tekst)),
        omschrijving="Inspreken (terugval)",
    )

  doel.write_bytes(antwoord.audio_content)


# --- Opslag -----------------------------------------------------------------
def _nieuw_id() -> str:
  return f"{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3)}"


def verhaal_map(verhaal_id: str) -> Path:
  if not re.fullmatch(r"[0-9a-zA-Z._-]{3,64}", verhaal_id or ""):
    raise ValueError("Ongeldig verhaal-id")
  map_pad = (config.STORIES_DIR / verhaal_id).resolve()
  if config.STORIES_DIR.resolve() not in map_pad.parents:
    raise ValueError("Ongeldig verhaal-id")
  return map_pad


def lees_verhaal(verhaal_id: str) -> dict | None:
  pad = verhaal_map(verhaal_id) / "verhaal.json"
  if not pad.is_file():
    return None
  try:
    return json.loads(pad.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError):
    return None


def _bewaar(verhaal: dict) -> None:
  pad = verhaal_map(verhaal["id"]) / "verhaal.json"
  pad.write_text(
      json.dumps(verhaal, ensure_ascii=False, indent=2), encoding="utf-8"
  )


def bibliotheek() -> list[dict]:
  """Alle bewaarde verhalen, nieuwste eerst, favorieten bovenaan."""
  items = []
  for map_pad in config.STORIES_DIR.iterdir() if config.STORIES_DIR.is_dir() else []:
    if not map_pad.is_dir():
      continue
    verhaal = lees_verhaal(map_pad.name)
    if not verhaal or not verhaal.get("scenes"):
      continue
    items.append({
        "id": verhaal["id"],
        "titel": verhaal.get("titel", "Verhaaltje"),
        "gemaakt_op": verhaal.get("gemaakt_op", ""),
        "favoriet": bool(verhaal.get("favoriet")),
        "prompt": verhaal.get("prompt", ""),
        "aantal_scenes": len(verhaal["scenes"]),
        "omslag": verhaal["scenes"][0].get("afbeelding"),
    })
  # Nieuwste eerst, met de favorieten bovenaan.
  items.sort(key=lambda i: i["gemaakt_op"], reverse=True)
  items.sort(key=lambda i: not i["favoriet"])
  return items


def markeer_favoriet(verhaal_id: str, favoriet: bool) -> dict | None:
  verhaal = lees_verhaal(verhaal_id)
  if not verhaal:
    return None
  verhaal["favoriet"] = bool(favoriet)
  _bewaar(verhaal)
  return verhaal


def verwijder_verhaal(verhaal_id: str) -> bool:
  pad = verhaal_map(verhaal_id)
  if not pad.is_dir():
    return False
  shutil.rmtree(pad)
  return True


def verhalen_vandaag() -> int:
  vandaag = f"{datetime.now(timezone.utc):%Y-%m-%d}"
  return sum(
      1 for item in bibliotheek() if item["gemaakt_op"].startswith(vandaag)
  )


# --- De hele pijplijn -------------------------------------------------------
def maak_verhaal(
    idee: str, aantal_scenes: int, meld: Voortgang
) -> dict:
  """Schrijft, tekent en spreekt een compleet verhaaltje in."""
  begonnen = time.monotonic()
  profiel = lees_profiel()
  verhaal_id = _nieuw_id()
  map_pad = verhaal_map(verhaal_id)
  map_pad.mkdir(parents=True, exist_ok=True)

  try:
    meld("Het verhaaltje wordt bedacht…", 5)
    geschreven = genereer_tekst(idee, profiel, aantal_scenes)
    scenes = geschreven["scenes"]
    totaal = len(scenes)
    meld(f"“{geschreven['titel']}” — nu de plaatjes…", 15)

    vorige: Path | None = None
    for scene in scenes:
      nr = scene["nr"]
      bestand = genereer_afbeelding(
          scene["beeld_prompt"], map_pad / f"scene_{nr}", referentie=vorige
      )
      scene["afbeelding"] = bestand
      vorige = map_pad / bestand
      meld(
          f"Plaatje {nr} van {totaal} is getekend…",
          15 + int(55 * nr / totaal),
      )

    meld("De verteller leest het verhaal in…", 74)
    genereer_audio(geschreven["titel"], map_pad / "titel.mp3", profiel)
    for scene in scenes:
      nr = scene["nr"]
      genereer_audio(scene["tekst"], map_pad / f"scene_{nr}.mp3", profiel)
      scene["audio"] = f"scene_{nr}.mp3"
      meld(
          f"Bladzijde {nr} van {totaal} is ingesproken…",
          74 + int(20 * nr / totaal),
      )

    naam = profiel.get("naam", "Leo")
    genereer_audio(
        f"Welterusten, {naam}. Slaap lekker.", map_pad / "slot.mp3", profiel
    )

    verhaal = {
        "id": verhaal_id,
        "titel": geschreven["titel"],
        "prompt": idee,
        "gemaakt_op": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "favoriet": False,
        "profiel": {
            "naam": profiel.get("naam"),
            "leeftijd": profiel.get("leeftijd"),
            "plaats": profiel.get("plaats"),
            "stem": profiel.get("stem"),
        },
        "titel_audio": "titel.mp3",
        "slot_audio": "slot.mp3",
        "scenes": scenes,
    }
    _bewaar(verhaal)
    meld("Klaar om voor te lezen!", 100)
    log.info(
        "Verhaal %s gemaakt in %.0f seconden (%d scènes).",
        verhaal_id,
        time.monotonic() - begonnen,
        len(scenes),
    )
    return verhaal
  except Exception:
    shutil.rmtree(map_pad, ignore_errors=True)
    raise
