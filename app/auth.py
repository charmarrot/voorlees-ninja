"""Toegang met één gedeelde pincode, bewaard in een ondertekende cookie."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict

from fastapi import HTTPException, Request, Response

from . import config

COOKIE_NAAM = "voorlees_toegang"
_MAX_POGINGEN = 8
_BLOKKADE_SECONDEN = 300
_pogingen: dict[str, list[float]] = defaultdict(list)


def pin_vereist() -> bool:
  return bool(config.APP_PIN)


def _token() -> str:
  handtekening = hmac.new(
      config.SECRET_KEY.encode("utf-8"),
      hashlib.sha256(config.APP_PIN.encode("utf-8")).digest(),
      hashlib.sha256,
  ).hexdigest()
  return handtekening


def is_ingelogd(request: Request) -> bool:
  if not pin_vereist():
    return True
  cookie = request.cookies.get(COOKIE_NAAM, "")
  return bool(cookie) and hmac.compare_digest(cookie, _token())


def vereis_toegang(request: Request) -> None:
  """FastAPI-dependency: blokkeert alles zonder geldige cookie."""
  if not is_ingelogd(request):
    raise HTTPException(status_code=401, detail="Pincode vereist")


def _client(request: Request) -> str:
  stuurlijst = request.headers.get("x-forwarded-for", "")
  if stuurlijst:
    return stuurlijst.split(",")[0].strip()
  return request.client.host if request.client else "onbekend"


def probeer_login(request: Request, response: Response, pincode: str) -> bool:
  """Controleert de pincode en zet bij succes de cookie."""
  sleutel = _client(request)
  nu = time.time()
  _pogingen[sleutel] = [t for t in _pogingen[sleutel] if nu - t < _BLOKKADE_SECONDEN]
  if len(_pogingen[sleutel]) >= _MAX_POGINGEN:
    raise HTTPException(
        status_code=429,
        detail="Te vaak geprobeerd. Wacht vijf minuten en probeer opnieuw.",
    )

  goed = hmac.compare_digest((pincode or "").strip(), config.APP_PIN)
  if not goed:
    _pogingen[sleutel].append(nu)
    time.sleep(0.5 + secrets.randbelow(500) / 1000)
    return False

  _pogingen.pop(sleutel, None)
  response.set_cookie(
      COOKIE_NAAM,
      _token(),
      max_age=config.SESSION_DAYS * 24 * 3600,
      httponly=True,
      samesite="lax",
      secure=request.url.scheme == "https",
      path="/",
  )
  return True


def uitloggen(response: Response) -> None:
  response.delete_cookie(COOKIE_NAAM, path="/")
