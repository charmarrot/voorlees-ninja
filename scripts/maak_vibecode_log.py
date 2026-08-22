#!/usr/bin/env python3
"""Genereert app/static/vibecode-log.json uit de git-historie.

Draaien aan het eind van een sessie, vóór de laatste commit:

    python scripts/maak_vibecode_log.py

Het bestand wordt meegecommit en is na de deploy publiek te lezen op
https://voorlees.ninjageit.nl/vibecode-log.json — zonder pincode, zodat
Cowork het voor de wekelijkse vibecode-review kan ophalen.

Bewust alleen de ONDERWERPREGEL van elke commit: de bodies bevatten
Claude-Session-URL's en die horen niet in een publiek bestand.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORTEL = Path(__file__).resolve().parent.parent
DOEL = WORTEL / "app" / "static" / "vibecode-log.json"
SCHEIDING = "\x1f"

# Commits die niets over het bouwen zeggen.
OVERSLAAN = ("merge ", "lege startcommit", "vibecode-log bijgewerkt")


def git(*argumenten: str) -> str:
  return subprocess.run(
      ["git", "-C", str(WORTEL), *argumenten],
      check=True, capture_output=True, text=True,
  ).stdout.strip()


def omvang(commit: str) -> dict:
  """Aantal gewijzigde bestanden en regels van één commit."""
  regels = git("show", "--numstat", "--format=", commit).splitlines()
  bestanden = gewijzigd = 0
  for regel in regels:
    delen = regel.split("\t")
    if len(delen) != 3:
      continue
    bestanden += 1
    for getal in delen[:2]:
      if getal.isdigit():
        gewijzigd += int(getal)
  return {"bestanden": bestanden, "regels": gewijzigd}


def bouw_entries() -> list[dict]:
  ruw = git(
      "log", "--no-merges", "--date=short",
      f"--format=%H{SCHEIDING}%ad{SCHEIDING}%s",
  )
  entries = []
  for regel in ruw.splitlines():
    commit, datum, titel = regel.split(SCHEIDING, 2)
    if titel.lower().startswith(OVERSLAAN):
      continue
    cijfers = omvang(commit)
    if not cijfers["bestanden"]:
      continue
    entries.append({
        "datum": datum,
        "titel": titel,
        "commit": commit[:7],
        **cijfers,
    })
  return entries


def main() -> int:
  entries = bouw_entries()
  log = {
      "schema": "vibecode-log/1",
      "project": "Voorlees Ninja",
      "domein": "voorlees.ninjageit.nl",
      "omschrijving": (
          "Webapp die met Gemini en Cloud Text-to-Speech elke avond een nieuw"
          " bedtijdverhaaltje schrijft, tekent en voorleest."
      ),
      "bijgewerkt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
      "aantal": len(entries),
      "entries": entries,
  }
  DOEL.parent.mkdir(parents=True, exist_ok=True)
  DOEL.write_text(
      json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
  )
  print(f"{DOEL.relative_to(WORTEL)}: {len(entries)} entries geschreven.")
  return 0


if __name__ == "__main__":
  sys.exit(main())
