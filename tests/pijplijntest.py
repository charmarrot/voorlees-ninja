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

AANROEPEN = {"tekst": 0, "beeld": 0, "beeld_met_referentie": 0, "audio": 0}
PNG = b"\x89PNG\r\n\x1a\nnepplaatje"


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
