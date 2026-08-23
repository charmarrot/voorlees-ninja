# 🌙 Voorlees Ninja

Een webapp die elke avond een nieuw bedtijdverhaaltje maakt: Gemini schrijft het
verhaal, tekent er een prentenboek bij en Google Cloud Text-to-Speech leest het
voor. De app draait als container op Coolify en is als PWA op de tablet te
installeren.

Alles is bewust donker en warm gehouden — geen fel blauw licht in een donkere
slaapkamer.

## Wat kan het?

- **Verhaal maken** vanuit een eigen idee of een van de suggestietegels.
- **Verse ideeën**: de suggestietegels worden door Gemini verzonnen op basis
  van het profiel (naam, leeftijd, woonplaats, interesses) en een dag lang
  bewaard in `suggesties.json` — dat is één goedkope tekstaanroep per dag. Met
  "Andere ideeën" vraag je meteen een nieuwe set. Lukt dat niet, dan valt de
  app terug op haar eigen ingebouwde lijst, ook offline.
- **Kort / gewoon / lang**: 3, 4 of 6 bladzijden.
- **Prentenboek met vaste hoofdpersoon**: elke illustratie krijgt de vorige mee
  als referentie, zodat het figuurtje en de tekenstijl door het hele boekje
  hetzelfde blijven.
- **Voorlezen per bladzijde** met automatisch omslaan, plus een "welterusten"
  aan het eind. Het scherm blijft aan tijdens het voorlezen. De ↻-knop naast
  de speelknop begint het hele verhaal opnieuw — voor als het "nog een keer!"
  wordt.
- **Slaapliedje bij het verhaal**: onder ⋯ maakt Gemini er een Nederlandse
  songtekst van met `[Vers]`- en `[Refrein]`-blokken, plus een Engelse
  stijlregel. Beide met één tik te kopiëren en zo in Suno of Gemini met
  muziek te plakken. Het liedje wordt bij het verhaal bewaard.
- **Boekenplank** met alle eerdere verhaaltjes, favorieten bovenaan.
- **Vegen, pijltjestoetsen en spatie** om te bladeren en voor te lezen.
- **Schermdimmer** voor als het echt donker moet.
- **PWA**: installeerbaar op de tablet, en bewaarde boekjes werken zonder
  internet.
- **Profiel**: naam, leeftijd, woonplaats, interesses, het uiterlijk van het
  hoofdpersoon, de stem en het voorleestempo.
- **Pincode** ervoor, zodat niet iedereen op internet jouw GCP-tegoed opmaakt.

## Snel lokaal draaien

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export GCP_SA_JSON="$(cat gcp_key.json)"   # of GCP_KEY_PATH=./gcp_key.json
export APP_PIN=1234
export SECRET_KEY=$(openssl rand -hex 32)
export DATA_DIR=./data

uvicorn app.main:app --reload --port 8000
```

Daarna open je <http://localhost:8000>.

De rooktest draait zonder Google-aanroepen en controleert routes, pincode,
opslag en de PWA-bestanden:

```bash
pip install httpx        # eenmalig, voor de testclient
python tests/rooktest.py
```

## Instellingen (environment variables)

| Variabele | Standaard | Waarvoor |
| --- | --- | --- |
| `GCP_SA_JSON` | — | **Aanbevolen.** De volledige service-account key als JSON (of base64). De app schrijft die bij het starten naar een tijdelijk bestand. |
| `GCP_KEY_PATH` | — | Alternatief: pad naar een gemount keybestand. |
| `GCP_PROJECT_ID` | `voorlees-ninja-506310` | Je Google Cloud-project. |
| `GCP_LOCATION` | `us-central1` | Vertex AI-regio. |
| `TEXT_MODEL` | `gemini-2.5-flash` | Model dat het verhaal schrijft. |
| `IMAGE_MODEL` | `gemini-2.5-flash-image` | Model dat de plaatjes tekent. |
| `APP_PIN` | leeg | Gedeelde pincode. Leeg = iedereen mag erbij. |
| `SECRET_KEY` | willekeurig | Ondertekent de inlogcookie. Zonder vaste waarde moet je na elke herstart opnieuw inloggen. |
| `SESSION_DAYS` | `60` | Hoe lang een tablet ingelogd blijft. |
| `MAX_STORIES_PER_DAY` | `25` | Rem op de kosten. |
| `TTS_VOICE` | `nl-NL-Wavenet-E` | Standaardstem (in de app zelf ook te kiezen). |
| `DATA_DIR` | `/data` | Waar de verhalen worden bewaard. |

Zie ook `.env.example`.

## Google Cloud klaarzetten

1. Zet in je project deze API's aan:
   - **Vertex AI API** (`aiplatform.googleapis.com`)
   - **Cloud Text-to-Speech API** (`texttospeech.googleapis.com`)
2. Maak een service account en geef die de rol **Vertex AI User**
   (`roles/aiplatform.user`).
3. Maak er een JSON-key voor en bewaar die **buiten** de repo — `gcp_key.json`
   staat in `.gitignore`.

## Uitrollen op Coolify

1. **New Resource → Private Repository** en kies deze repo met de `Dockerfile`
   build pack. Poort **8000** wordt automatisch opgepikt (`EXPOSE 8000`).
2. **Domain**: `https://voorlees.ninjageit.nl`. Traefik regelt het certificaat.
3. **Environment Variables** — als *secret* markeren waar dat kan:
   - `GCP_SA_JSON` → plak de volledige inhoud van je keybestand. Staan de
     newlines in de private key in de weg, plak dan de base64-versie:
     `base64 -w0 gcp_key.json`.
   - `APP_PIN` → de pincode die je thuis gebruikt.
   - `SECRET_KEY` → `openssl rand -hex 32`.
   - Eventueel `GCP_PROJECT_ID`, `GCP_LOCATION`, `MAX_STORIES_PER_DAY`.
4. **Persistent Storage** → volume mount op `/data`. Zonder dit volume ben je
   alle verhaaltjes kwijt bij een nieuwe deploy.
5. **Health check** staat al in de `Dockerfile` (`/healthz`).
6. **Deploy**, en zet daarna op de tablet in Safari/Chrome
   "Zet op beginscherm" — dan opent hij als losse app zonder adresbalk.

## Hoe het werkt

```
Browser  ──POST /api/genereer──►  FastAPI  ──►  wachtrij (1 verhaal tegelijk)
   │                                              │
   │  ◄──GET /api/taken/{id}── voortgang ─────────┤ 1. Gemini schrijft JSON
   │                                              │ 2. Gemini tekent scène 1..n
   │  ◄──/media/{verhaal}/…── plaatjes + mp3 ─────┤ 3. TTS spreekt elke scène in
                                                  └─► /data/stories/<id>/
```

Elk verhaal komt in een eigen map te staan:

```
data/stories/20260822-a1b2c3/
├── verhaal.json     # titel, teksten, beeldprompts, bestandsnamen
├── scene_1.png …    # de illustraties
├── scene_1.mp3 …    # per bladzijde ingesproken
├── titel.mp3
└── slot.mp3         # "Welterusten, Leo."
```

Mislukt er iets halverwege, dan wordt de halve map opgeruimd — je krijgt nooit
een kapot boekje op de plank.

## Kosten in toom houden

Eén verhaaltje van 4 bladzijden = 1 tekstaanroep, 4 beeldaanroepen en 6 korte
TTS-aanroepen. `MAX_STORIES_PER_DAY` zet daar een dagelijkse rem op, de pincode
houdt vreemden buiten, en er wordt maar één verhaal tegelijk gemaakt.

## Beveiliging

- Alles achter de pincode: de API én de plaatjes en geluidsbestanden.
- De cookie is HMAC-ondertekend, `httponly` en `secure` achter https.
- Na 8 mislukte pogingen is dat ip-adres vijf minuten geblokkeerd.
- Bestandsnamen en verhaal-id's worden gecontroleerd, dus `../`-trucs werken
  niet.
- De service-account key staat nooit in de repo of in de image, alleen in een
  environment variable.
