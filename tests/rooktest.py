"""Rooktest zonder Google-aanroepen: routes, pincode, opslag en bibliotheek.

Draaien vanuit de projectmap:  python tests/rooktest.py
"""
import json, os, shutil, sys, tempfile
from pathlib import Path

tijdelijk = tempfile.mkdtemp(prefix="voorlees-test-")
os.environ["DATA_DIR"] = tijdelijk
os.environ["APP_PIN"] = "4321"
os.environ["SECRET_KEY"] = "test-sleutel-voor-de-rooktest"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.main import app
from app import story, config

c = TestClient(app)

# 1. Startpagina rendert
r = c.get("/")
assert r.status_code == 200 and "Voorlees Ninja" in r.text, r.status_code
print("✓ startpagina")

# 2. Alles achter de pin is dicht
for pad in ("/api/verhalen", "/api/profiel", "/api/suggesties",
            "/media/abc/scene_1.png"):
    assert c.get(pad).status_code == 401, pad
assert c.post("/api/genereer", json={"prompt": "test"}).status_code == 401
print("✓ pincode beschermt api en media")

# 2b. Het vibecode-log moet juist WEL zonder pincode bereikbaar zijn
log = c.get("/vibecode-log.json")
assert log.status_code == 200, log.status_code
assert log.json()["schema"] == "vibecode-log/1"
assert log.headers["content-type"].startswith("application/json")
tekst = log.text.lower()
for verboden in ("claude.ai/code/session", "private_key", "gcp_sa_json", "-----begin"):
    assert verboden not in tekst, f"gevoelige tekst in het logboek: {verboden}"
print("✓ vibecode-log publiek, zonder pincode en zonder geheimen")

# 3. Verkeerde pin faalt, juiste pin geeft cookie
assert c.post("/api/login", data={"pincode": "0000"}).status_code == 401
assert c.post("/api/login", data={"pincode": "4321"}).status_code == 200
assert c.get("/api/status").json()["ingelogd"] is True
print("✓ inloggen")

# 4. Profiel opslaan en teruglezen
p = c.post("/api/profiel", json={"naam": "Leo", "leeftijd": 3, "plaats": "Rotterdam",
                                 "tempo": 5.0, "onzin": "x"}).json()
assert p["naam"] == "Leo" and p["tempo"] == 1.3 and "onzin" not in p, p
assert c.get("/api/profiel").json()["naam"] == "Leo"
print("✓ profiel (met begrenzing)")

# 5. Nepverhaal op schijf -> bibliotheek, media, favoriet, verwijderen
vid = "20260822-abc123"
map_pad = Path(tijdelijk) / "stories" / vid
map_pad.mkdir(parents=True)
(map_pad / "scene_1.png").write_bytes(b"\x89PNG\r\n\x1a\nnep")
(map_pad / "scene_1.mp3").write_bytes(b"nepgeluid")
(map_pad / "verhaal.json").write_text(json.dumps({
    "id": vid, "titel": "Leo en de tram", "gemaakt_op": "2026-08-22T19:00:00+00:00",
    "favoriet": False, "titel_audio": "titel.mp3", "slot_audio": "slot.mp3",
    "scenes": [{"nr": 1, "tekst": "Leo rijdt.", "beeld_prompt": "x",
                "afbeelding": "scene_1.png", "audio": "scene_1.mp3"}],
}), encoding="utf-8")

lijst = c.get("/api/verhalen").json()["verhalen"]
assert len(lijst) == 1 and lijst[0]["omslag"] == "scene_1.png", lijst
assert c.get(f"/media/{vid}/scene_1.png").status_code == 200
assert c.get(f"/api/verhalen/{vid}").json()["titel"] == "Leo en de tram"
assert c.post(f"/api/verhalen/{vid}/favoriet", json={"favoriet": True}).json()["favoriet"] is True
assert c.get("/api/verhalen").json()["verhalen"][0]["favoriet"] is True
print("✓ bibliotheek, media en favorieten")

# 6. Padtrucs worden geweigerd
for slecht in ("/media/..%2F..%2Fetc/passwd", f"/media/{vid}/../verhaal.json",
               "/media/a/b/c", f"/media/{vid}/.verborgen"):
    code = c.get(slecht).status_code
    assert code in (400, 404, 405), (slecht, code)
assert c.get("/api/verhalen/../../etc").status_code in (400, 404)
print("✓ padtrucs geblokkeerd")

# 6b. Suggesties: achter de pincode, en netjes terugvallen als Google faalt
def _stuk(*a, **k):
    raise RuntimeError("geen verbinding met Google")
story.genereer_suggesties = _stuk
antwoord = c.get("/api/suggesties")
assert antwoord.status_code == 200, antwoord.status_code
assert antwoord.json()["suggesties"] == [], antwoord.json()
print("✓ suggesties vallen terug op de vaste lijst als Google faalt")

# 7. Invoercontrole bij genereren
assert c.post("/api/genereer", json={"prompt": "ab"}).status_code == 400
print("✓ lege prompt geweigerd")

# 8. Verwijderen
assert c.delete(f"/api/verhalen/{vid}").status_code == 200
assert c.get("/api/verhalen").json()["verhalen"] == []
print("✓ verwijderen")

# 9. Uitloggen sluit de deur weer
c.post("/api/logout")
assert c.get("/api/verhalen").status_code == 401
print("✓ uitloggen")

# 10. Service worker, manifest, health, iconen
assert c.get("/sw.js").status_code == 200
assert c.get("/manifest.webmanifest").status_code == 200
assert c.get("/healthz").json()["status"] == "ok"
for icoon in ("icoon.svg", "icoon-192.png", "icoon-512.png", "icoon-maskeerbaar.png",
              "app.js", "styles.css"):
    assert c.get(f"/static/{icoon}").status_code == 200, icoon
print("✓ pwa-bestanden")

shutil.rmtree(tijdelijk, ignore_errors=True)
print("\nAlles goed 🎉")
