# control_center/root_path.py
# -*- coding: utf-8 -*-
"""
Reverse-Proxy-Subpath-Unterstuetzung (Spike, Phase 1).

Betrieb hinter nginx unter einem Subpath (z. B. https://host/controlcenter/):
nginx entfernt den Prefix (`proxy_pass http://127.0.0.1:8420/;`) und meldet
ihn per `X-Forwarded-Prefix`. Diese Middleware uebernimmt ihn nach
`scope["root_path"]` — der ASGI-Standardweg, den Starlette fuer
`request.url`, `url_for()` und Slash-Redirects auswertet. Das Routing
selbst matcht weiterhin auf `scope["path"]` (ohne Prefix), Routen bleiben
also unveraendert Root-basiert.

Ohne Header (Direktbetrieb auf 127.0.0.1:8420) bleibt `root_path`
unveraendert — kein Verhaltensunterschied.

Sicherheit: Der Header kommt ausschliesslich von nginx (uvicorn bindet nur
an 127.0.0.1), wird aber trotzdem streng validiert — ein ungueltiger Wert
wird ignoriert statt uebernommen, damit ein manipulierter Header keine
Redirects auf fremde Hosts (`//evil.example`) erzeugen kann.
"""

from __future__ import annotations

import re
from typing import Optional

# Ein oder mehrere Segmente aus URL-sicheren Zeichen, fuehrender Slash,
# kein "//" am Anfang, kein "." / ".." als Segment.
_PREFIX_RE = re.compile(r"^(?:/[A-Za-z0-9._~-]+)+$")


def normalize_prefix(raw: Optional[str]) -> str:
    """Liefert einen sicheren root_path ("" wenn leer/ungueltig)."""
    if not raw:
        return ""
    value = raw.strip().rstrip("/")
    if not value or not _PREFIX_RE.match(value):
        return ""
    if any(seg in (".", "..") for seg in value.split("/")):
        return ""
    return value


class ForwardedPrefixMiddleware:
    """Reine ASGI-Middleware: X-Forwarded-Prefix -> scope["root_path"]."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            for name, value in scope.get("headers", []):
                if name == b"x-forwarded-prefix":
                    prefix = normalize_prefix(value.decode("latin-1"))
                    if prefix:
                        scope = dict(scope)
                        scope["root_path"] = prefix
                    break
        await self.app(scope, receive, send)
