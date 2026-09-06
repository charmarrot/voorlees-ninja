"""Test de verhaalpijplijn met nagebootste Google-clients (geen echte kosten).

Draaien vanuit de projectmap:  python tests/pijplijntest.py
"""
import json, os, shutil, sys, tempfile, types
from pathlib import Path

tijdelijk = tempfile.mkdtemp(prefix="voorlees-pijplijn-")
os.environ["DATA_DIR"] = tijdelijk
os.environ["APP_PIN"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import gcp, story  # noqa: E402

AANROEPEN = {"tekst": 0, "beeld": 0, "beeld_met_referentie": 0, "audio": 0,
             "suggesties": 0, "liedje": 0, "gezongen": 0}
PNG = b"\x89PNG\r\n\x1a\nnepplaatje"
GEZONGEN_INSTELLING = {"mislukken": False}


class NepDeel:
  def __init__(self, data): self.inline_data = types.SimpleNamespace(data=data, mime_type="image/png")


class NepAntwoord:
  def __init__(self, tekst=None, beeld=False):
    self.text = tekst
    deel = NepDeel(PNG) if beeld else types.SimpleNamespace(inline_data=None)
    inhoud = types.SimpleNamespace(parts=[deel])
    self.candidates = [types.SimpleNamespace(content=inhoud)]


class NepModellen:
  def generate_content(self, model, contents, config=None):
    if "image" in model:
      AANROEPEN["beeld"] += 1
      if any(not isinstance(deel, str) for deel in contents):
        AANROEPEN["beeld_met_referentie"] += 1
      return NepAntwoord(beeld=True)
    if "lyria" in model:
      AANROEPEN["gezongen"] += 1
      if GEZONGEN_INSTELLING["mislukken"]:
        deel = types.SimpleNamespace(inline_data=None)
      else:
        # Ruwe PCM, zoals Lyria (en Gemini's andere audio-antwoorden) vaak
        # teruggeven -- precies het geval dat de WAV-header zelf moet
        # worden opgebouwd.
        ruwe_pcm = b"\x11\x22" * 4000
        deel = types.SimpleNamespace(inline_data=types.SimpleNamespace(
            data=ruwe_pcm, mime_type="audio/L16;rate=24000"))
      inhoud = types.SimpleNamespace(parts=[deel])
      return types.SimpleNamespace(candidates=[types.SimpleNamespace(content=inhoud)])
    if contents and str(contents[0]).startswith("Titel van het verhaal:"):
      AANROEPEN["liedje"] += 1
      # Gemini geeft voor meerregelige tekst vaak LETTERLIJKE regeleinden
      # terug in plaats van het escape-teken \n -- ongeldig voor
      # json.loads(strict=True), en precies wat _parse_json moet verdragen.
      return NepAntwoord(tekst=(
          '{"titel": "Slaap zacht, Leo",'
          ' "stijl": "soft Dutch lullaby, gentle guitar, warm voice, slow 6/8",'
          ' "tekst": "[Intro]\nSssst\n\n[Vers 1]\nLeo rijdt door de nacht\n'
          '\n[Refrein]\nSlaap zacht, Leo, slaap zacht\n"}'
      ))
    if contents and contents[0] == "Verzin nieuwe ideeën.":
      AANROEPEN["suggesties"] += 1
      return NepAntwoord(tekst=json.dumps({"suggesties": [
          {"emoji": "🚋", "label": f"Idee {n}",
           "idee": f"Leo beleeft avontuur nummer {n} in de stad"}
          for n in range(1, 9)
      ]}))
    AANROEPEN["tekst"] += 1
    # Het model levert JSON in een codeblok: de parser moet daar tegen kunnen.
    return NepAntwoord(tekst="```json\n" + json.dumps({
        "titel": "Leo en de dansende tram",
        "scenes": [
            {"scene_nr": n, "tekst": f"Zin {n} van het verhaal.",
             "beeld_prompt": f"scene {n} with the toddler boy"}
            for n in range(1, 5)
        ],
    }) + "\n```")


class NepGenai:
  models = NepModellen()


class NepTts:
  def synthesize_speech(self, input, voice, audio_config):
    AANROEPEN["audio"] += 1
    assert voice.language_code == "nl-NL"
    return types.SimpleNamespace(audio_content=b"ID3nepgeluid")


gcp.genai_client = lambda: NepGenai()
gcp.muziek_client = lambda: NepGenai()
gcp.tts_client = lambda: NepTts()

stappen = []
verhaal = story.maak_verhaal(
    "Leo rijdt met tram 3 over de Erasmusbrug", 4,
    lambda stap, pct: stappen.append((stap, pct)),
)

vid = verhaal["id"]
map_pad = Path(tijdelijk) / "stories" / vid
assert verhaal["titel"] == "Leo en de dansende tram"
assert len(verhaal["scenes"]) == 4
print("✓ verhaal geschreven en JSON uit codeblok geparsed")

for n in range(1, 5):
  assert (map_pad / f"scene_{n}.png").read_bytes() == PNG, n
  assert (map_pad / f"scene_{n}.mp3").is_file(), n
assert (map_pad / "titel.mp3").is_file() and (map_pad / "slot.mp3").is_file()
assert json.loads((map_pad / "verhaal.json").read_text(encoding="utf-8"))["id"] == vid
print("✓ vier plaatjes, vier bladzijden geluid, titel en slot op schijf")

assert AANROEPEN["beeld"] == 4, AANROEPEN
assert AANROEPEN["beeld_met_referentie"] == 3, AANROEPEN  # scène 2..4 krijgen de vorige mee
assert AANROEPEN["audio"] == 6, AANROEPEN                 # titel + 4 scènes + slot
print("✓ scène 2 t/m 4 gebruiken de vorige tekening als referentie")

assert stappen[-1][1] == 100 and [p for _, p in stappen] == sorted(p for _, p in stappen)
print("✓ voortgang loopt netjes op naar 100%")

lijst = story.bibliotheek()
assert len(lijst) == 1 and lijst[0]["omslag"] == "scene_1.png"
print("✓ verhaal staat op de boekenplank")

# Slaapliedje: één keer schrijven, daarna bij het verhaal bewaard.
lied = story.liedje_voor(vid)
assert lied["titel"] == "Slaap zacht, Leo" and "[Refrein]" in lied["tekst"], lied
assert lied["stijl"].startswith("soft Dutch lullaby")
assert AANROEPEN["liedje"] == 1
assert story.lees_verhaal(vid)["liedje"]["tekst"] == lied["tekst"]
nogmaals = story.liedje_voor(vid)
assert AANROEPEN["liedje"] == 1, "liedje werd onnodig opnieuw geschreven"
opnieuw = story.liedje_voor(vid, vernieuw=True)
assert AANROEPEN["liedje"] == 2 and opnieuw["tekst"] == lied["tekst"]
assert story.liedje_voor("bestaat-niet-hier") is None
print("✓ slaapliedje geschreven, bewaard en op verzoek herschreven")

# Experimenteel: het liedje laten zingen via Lyria. Kan pas als er al een
# songtekst is; wat Lyria teruggeeft (ruwe PCM) moet altijd een echt,
# afspeelbaar mp3-bestand worden -- niet soms wav, soms iets anders.
def _is_geldige_mp3(data: bytes) -> bool:
  return len(data) > 100 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0

geen_tekst_nog = story.gezongen_liedje_voor("een-verhaal-zonder-liedje")
assert geen_tekst_nog is None

gezongen = story.gezongen_liedje_voor(vid)
assert gezongen["bestand"] == "liedje_gezongen.mp3" and gezongen["mime"] == "audio/mpeg"
assert AANROEPEN["gezongen"] == 1
mp3_pad = map_pad / gezongen["bestand"]
assert mp3_pad.is_file()
assert _is_geldige_mp3(mp3_pad.read_bytes()), "geen geldige mp3-syncheader"
assert story.lees_verhaal(vid)["liedje"]["gezongen"]["bestand"] == gezongen["bestand"]

nogmaals_gezongen = story.gezongen_liedje_voor(vid)
assert AANROEPEN["gezongen"] == 1, "gezongen versie werd onnodig opnieuw gemaakt"
opnieuw_gezongen = story.gezongen_liedje_voor(vid, vernieuw=True)
assert AANROEPEN["gezongen"] == 2
print("✓ experimenteel: ruwe PCM van Lyria wordt een geldig, afspeelbaar mp3-bestand")

# Aangepaste stijl/tekst meesturen wordt bewaard en dwingt een nieuwe poging
# af, ook zonder vernieuw=True -- een edit negeren zou verwarrend zijn.
aangepast = story.gezongen_liedje_voor(
    vid, stijl="andere stijl", tekst="[Intro]\nhelemaal nieuwe tekst hier\n\n[Refrein]\nx"
)
assert AANROEPEN["gezongen"] == 3, "een aanpassing had een nieuwe poging moeten forceren"
bewaard = story.lees_verhaal(vid)["liedje"]
assert bewaard["stijl"] == "andere stijl", bewaard["stijl"]
assert "helemaal nieuwe tekst" in bewaard["tekst"], bewaard["tekst"]
# Dezelfde tekst nogmaals meesturen (geen echte wijziging) forceert niets.
story.gezongen_liedje_voor(vid, stijl="andere stijl", tekst=bewaard["tekst"])
assert AANROEPEN["gezongen"] == 3, "ongewijzigde stijl/tekst had niets moeten forceren"
print("✓ experimenteel: aangepaste stijl/tekst wordt bewaard en opnieuw gezongen")

GEZONGEN_INSTELLING["mislukken"] = True
try:
  story.gezongen_liedje_voor(vid, vernieuw=True)
  raise AssertionError("had moeten mislukken: Lyria gaf geen audio terug")
except RuntimeError as fout:
  assert "geen audio" in str(fout).lower(), fout
GEZONGEN_INSTELLING["mislukken"] = False
print("✓ experimenteel: nette fout als Lyria geen audio teruggeeft")

# Suggesties: één keer verzinnen, daarna uit de cache.
eerste = story.lees_suggesties()
assert eerste["bron"] == "gemini" and len(eerste["suggesties"]) == 8, eerste
assert AANROEPEN["suggesties"] == 1
tweede = story.lees_suggesties()
assert tweede["bron"] == "cache" and AANROEPEN["suggesties"] == 1, tweede
print("✓ suggesties worden één keer verzonnen en daarna bewaard")

# Kort na elkaar vernieuwen wordt afgeremd.
geremd = story.lees_suggesties(vernieuw=True)
assert geremd.get("wacht") is True and AANROEPEN["suggesties"] == 1, geremd
print("✓ driftig vernieuwen wordt afgeremd")

# Verandert het profiel, dan vervalt de cache.
story.schrijf_profiel({"naam": "Mila", "plaats": "Utrecht"})
na_wijziging = story.lees_suggesties()
assert na_wijziging["bron"] == "gemini" and AANROEPEN["suggesties"] == 2, na_wijziging
print("✓ nieuw profiel geeft nieuwe ideeën")

# Mislukt de beeldgeneratie, dan blijft er geen half boekje achter.
gcp.genai_client = lambda: types.SimpleNamespace(
    models=types.SimpleNamespace(generate_content=NepModellen().generate_content))
def stuk(*a, **k): raise RuntimeError("beeldmodel doet het even niet")
story.genereer_afbeelding = stuk
try:
  story.maak_verhaal("Test die stukloopt", 4, lambda s, p: None)
  raise AssertionError("had moeten mislukken")
except RuntimeError as fout:
  assert "even niet" in str(fout)
assert len(story.bibliotheek()) == 1, "half verhaal is blijven staan"
print("✓ mislukt verhaal wordt opgeruimd")

shutil.rmtree(tijdelijk, ignore_errors=True)
print("\nPijplijn in orde 🎉")
