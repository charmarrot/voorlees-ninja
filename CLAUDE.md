# Voorlees Ninja — aandachtspunten voor Claude

Webapp die met Gemini en Cloud Text-to-Speech bedtijdverhaaltjes maakt voor
Leo. Draait als container op Coolify, publiek op `voorlees.ninjageit.nl`
achter een Cloudflare-tunnel.

Zie `README.md` voor de opzet, de environment variables en het uitrollen.

## Draaien en testen

```bash
uvicorn app.main:app --reload --port 8000     # lokaal
python tests/rooktest.py                      # routes, pincode, opslag, PWA
python tests/pijplijntest.py                  # generatiepijplijn, zonder GCP-kosten
```

Beide tests draaien zonder Google-aanroepen. Draai ze allebei voordat je pusht:
een kapotte deploy betekent hier een kind zonder verhaaltje.

## Vaste afspraken

- **Nederlands** in de code: functienamen, variabelen, commentaar en alle
  tekst in de interface. Engels alleen waar het framework dat afdwingt en in
  de beeldprompts (die gaan naar het tekenmodel).
- **Geen fel blauw licht** in de interface. Het donkere thema met warme
  accenten is een bewuste keuze voor gebruik in een donkere slaapkamer.
- **Alles achter de pincode**, inclusief de plaatjes en geluidsbestanden. De
  enige uitzonderingen zijn `/healthz`, `/manifest.webmanifest`, `/sw.js`,
  `/static/*` en `/vibecode-log.json`.
- **Nooit een sleutel in de repo.** De service-account key komt uit
  `GCP_SA_JSON`; `gcp_key.json` staat in `.gitignore`.
- **Verhalen leven op het volume** (`/data`), niet in de image. Bestanden
  daar zijn van Leo — nooit weggooien zonder dat Marc erom vraagt.

## Vibecode-log

`app/static/vibecode-log.json` wordt publiek geserveerd op
<https://voorlees.ninjageit.nl/vibecode-log.json> (zonder auth) en door Cowork
opgehaald voor Marc's wekelijkse vibecode-review.

Regenereren aan het eind van een sessie, vóór de laatste commit:

```bash
python scripts/maak_vibecode_log.py
```

Het bestand wordt uit `git log` opgebouwd en meegecommit, want `.git` zit in
`.dockerignore` en is tijdens de Docker-build dus niet beschikbaar.

Formaat (`schema: "vibecode-log/1"`):

```json
{
  "schema": "vibecode-log/1",
  "project": "Voorlees Ninja",
  "domein": "voorlees.ninjageit.nl",
  "omschrijving": "…",
  "bijgewerkt": "2026-08-22T19:04:51+00:00",
  "aantal": 1,
  "entries": [
    {
      "datum": "2026-08-22",
      "titel": "Onderwerpregel van de commit",
      "commit": "6a65239",
      "bestanden": 22,
      "regels": 3124
    }
  ]
}
```

**Let op bij het schrijven van commit-onderwerpen:** die regel komt
ongefilterd in een publiek bestand terecht. Dus geen tokens, sleutels,
project-id's, interne hostnames of iets uit de verhalen van Leo zelf. Het
script neemt bewust alleen de onderwerpregel mee en nooit de body — daar staan
Claude-Session-URL's in.
