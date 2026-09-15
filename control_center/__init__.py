# control_center/__init__.py
# -*- coding: utf-8 -*-
"""
MusicBot Control Center — Web-Backend (FastAPI).

Reine Orchestrierungsschicht analog zu handlers/ und klassen/ (siehe
CLAUDE.md Abschnitt 4): ruft ausschliesslich bestehende services/-Funktionen
auf, enthaelt keine eigene Fachlogik. Siehe
docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md fuer den vollstaendigen
Architekturvorschlag und docs/audits/CONTROL_CENTER_ARCHITECTURE_AUDIT_2026-09-15.md
fuer den vorangegangenen Repository-Audit.

Status: Vertical Slice "Health/Dashboard", Schritt 1 (Health API). Noch
ohne Authentifizierung (folgt in Schritt 3) — dieser Server ist bislang
ausschliesslich fuer lokale Entwicklung gedacht (uvicorn bindet laut
Architekturvorschlag nur an 127.0.0.1, kein Reverse-Proxy/keine externe
Erreichbarkeit vorgesehen, bevor Auth steht).
"""
