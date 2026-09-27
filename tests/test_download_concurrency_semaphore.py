# tests/test_download_concurrency_semaphore.py
# -*- coding: utf-8 -*-
"""
RETIRED (Client Consolidation Phase D/E, 2026-09-28): charakterisierte
bisher klassen/download_handler.py::_get_download_semaphore()/
_download_semaphore, ein modulglobales asyncio.Semaphore.

Dieser Mechanismus wurde ersetzt durch
services/downloader/download_concurrency.py::download_slot() (Cross-
Process-N-Slot-Mutex, siehe dortiger Modul-Docstring und
docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md Abschnitt 11)
- notwendig, weil ein modulglobales, prozesslokales Semaphore keine
Grenze mehr über Bot- UND Control-Center-Prozess hinweg durchsetzen
kann. `_get_download_semaphore`/`_download_semaphore` existieren in
klassen/download_handler.py nicht mehr; die hier ehemals enthaltenen
Charakterisierungstests (Modul-Singleton, Shared-Instance über mehrere
DownloadHandler-Konstruktionen, tatsächliche Nebenläufigkeitsbegrenzung,
Default-Fallback auf 3) sind funktional äquivalent in
tests/test_download_concurrency.py fortgeführt, dort für den neuen
Cross-Process-Mechanismus (inkl. der bewusst beibehaltenen Warte- statt
Fail-Fast-Semantik).

Datei bleibt als Platzhalter erhalten statt gelöscht (Löschung wurde in
dieser Session vom Auto-Mode-Classifier als irreversible Aktion
blockiert) - keine aktiven Tests mehr, absichtlich.
"""
