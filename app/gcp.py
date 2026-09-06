"""Dunne laag rond de Google-clients: lui geladen, met retries."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, TypeVar

from . import config

log = logging.getLogger("voorlees.gcp")

T = TypeVar("T")

_lock = threading.Lock()
_genai_client: Any = None
_muziek_client: Any = None
_tts_client: Any = None


def genai_client():
  """Vertex AI-client voor tekst- en beeldgeneratie."""
  global _genai_client
  if _genai_client is None:
    with _lock:
      if _genai_client is None:
        from google import genai

        config.bootstrap_credentials()
        _genai_client = genai.Client(
            vertexai=True,
            project=config.GCP_PROJECT_ID,
            location=config.GCP_LOCATION,
        )
        log.info(
            "Vertex AI-client gestart (project=%s, locatie=%s).",
            config.GCP_PROJECT_ID,
            config.GCP_LOCATION,
        )
  return _genai_client


def muziek_client():
  """Aparte client voor Lyria (experimenteel), met zijn eigen locatie.

  Lyria staat niet per se op dezelfde regio als de tekst- en
  beeldmodellen -- vandaar een eigen client in plaats van hergebruik van
  genai_client(), zodat een verkeerde locatie-gok hier niet de rest van de
  app kan raken.
  """
  global _muziek_client
  if _muziek_client is None:
    with _lock:
      if _muziek_client is None:
        from google import genai

        config.bootstrap_credentials()
        _muziek_client = genai.Client(
            vertexai=True,
            project=config.GCP_PROJECT_ID,
            location=config.MUSIC_LOCATION,
        )
        log.info(
            "Muziekclient (Lyria, experimenteel) gestart (project=%s,"
            " locatie=%s).",
            config.GCP_PROJECT_ID,
            config.MUSIC_LOCATION,
        )
  return _muziek_client


def tts_client():
  """Client voor Cloud Text-to-Speech."""
  global _tts_client
  if _tts_client is None:
    with _lock:
      if _tts_client is None:
        from google.cloud import texttospeech

        config.bootstrap_credentials()
        _tts_client = texttospeech.TextToSpeechClient()
        log.info("Text-to-Speech-client gestart.")
  return _tts_client


def with_retries(
    fn: Callable[[], T],
    *,
    pogingen: int = 3,
    wacht: float = 2.0,
    omschrijving: str = "Google API-aanroep",
) -> T:
  """Voert `fn` uit en probeert het opnieuw bij tijdelijke fouten."""
  laatste: Exception | None = None
  for poging in range(1, pogingen + 1):
    try:
      return fn()
    except Exception as exc:  # noqa: BLE001 - alle SDK-fouten zijn interessant
      laatste = exc
      if poging == pogingen:
        break
      pauze = wacht * (2 ** (poging - 1))
      log.warning(
          "%s mislukt (poging %d/%d): %s -- opnieuw over %.0fs",
          omschrijving,
          poging,
          pogingen,
          exc,
          pauze,
      )
      time.sleep(pauze)
  assert laatste is not None
  raise laatste


_voices_cache: list[dict] | None = None


def nederlandse_stemmen() -> list[dict]:
  """Haalt de beschikbare Nederlandse stemmen op (gecached)."""
  global _voices_cache
  if _voices_cache is not None:
    return _voices_cache

  from google.cloud import texttospeech

  request = texttospeech.ListVoicesRequest(language_code="nl-NL")
  antwoord = with_retries(
      lambda: tts_client().list_voices(request=request),
      pogingen=2,
      omschrijving="Stemmenlijst ophalen",
  )
  geslacht = {1: "man", 2: "vrouw", 3: "neutraal"}
  stemmen = [
      {
          "naam": stem.name,
          "geslacht": geslacht.get(int(stem.ssml_gender), "onbekend"),
          "soort": _stemsoort(stem.name),
      }
      for stem in antwoord.voices
  ]
  volgorde = {"Chirp3-HD": 0, "Neural2": 1, "Wavenet": 2, "Standard": 3}
  stemmen.sort(key=lambda s: (volgorde.get(s["soort"], 9), s["naam"]))
  _voices_cache = stemmen
  return stemmen


def _stemsoort(naam: str) -> str:
  for soort in ("Chirp3-HD", "Chirp-HD", "Neural2", "Wavenet", "Studio",
                "Standard", "Polyglot"):
    if soort.lower() in naam.lower():
      return soort
  return "overig"
