# services/library_health/findings.py
# -*- coding: utf-8 -*-
"""
Persistentes Findings-Review-System für den Library Health Scanner.

Ein *Finding* ist ein konkreter, wiedererkennbarer Befund eines Scans
(z. B. "ALBUM_TRACK_GAP bei Artist X, Album Y") — nicht zu verwechseln mit
einem Issue-Code allein, der pro Scan beliebig oft mit unterschiedlicher
Identität auftreten kann (sieben "ALBUM_TRACK_GAP"-Issues sind sieben
verschiedene Findings).

Architektur (bewusst getrennt vom Scanner, siehe CLAUDE.md §4 Schichtgrenzen
und Aufgaben-Abschnitt 1/28):

    Scanner (services/library_health/*) → Issues (rein transient, pro Lauf)
        ↓
    generate_finding_id()               → stabile Identität pro Issue
        ↓
    FindingsRegistry                    → persistenter Review-Status
        ↓
    annotate_issues_with_findings()     → reichert Issues additiv an
        ↓
    report.py::render_summary_markdown()/CLI/(künftig) Telegram-Handler

Der Scanner selbst bleibt vollständig read-only gegenüber der Music
Library (unverändert) — dieses Modul liest/schreibt ausschließlich die
Registry-Datei außerhalb der Library. Es gibt hier bewusst KEINE
Reparaturfunktion (kein Rename/Move/Delete/Tag-/Cover-Schreiben/Re-Encode)
— reines Findings-Management (Aufgaben-Abschnitt 12/29).

Zukunftssicherheit (Aufgaben-Abschnitt 28): ein künftiger Telegram-Handler
ruft dieselbe `FindingsRegistry`-API wie `scripts/library_health_review.py`
auf — niemals die JSON-Datei direkt.
"""

from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from logger import get_module_logger

# schema_version aendert sich nur bei einer inkompatiblen Aenderung der
# Registry-Struktur selbst (analog SCHEMA_VERSION in models.py).
SCHEMA_VERSION = 1

DEFAULT_FILENAME = "library_health_findings.json"

# ─────────────────────────────────────────────────────────────────────────
# Lifecycle-Status (Aufgaben-Abschnitt 3)
# ─────────────────────────────────────────────────────────────────────────

STATUS_OPEN = "OPEN"
STATUS_RESOLVED = "RESOLVED"
STATUS_FALSE_POSITIVE = "FALSE_POSITIVE"
# Technischer Zwischenzustand (Aufgaben-Abschnitt 9): der Scanner erkennt
# das Finding nicht mehr, aber kein Mensch hat das je bestaetigt. Bewusst
# von RESOLVED (= Nutzer hat die Behebung bestaetigt) unterschieden, damit
# "nicht mehr erkannt" nie mit "geprueft und behoben" verwechselt wird.
# Zaehlt NICHT als "offen" (Aufgaben-Abschnitt 17) - es gibt aktuell nichts
# zu pruefen, der Scanner sieht es schlicht nicht mehr.
STATUS_RESOLVED_BY_SCAN = "RESOLVED_BY_SCAN"

_ALL_STATUSES = (STATUS_OPEN, STATUS_RESOLVED, STATUS_FALSE_POSITIVE, STATUS_RESOLVED_BY_SCAN)
_REVIEWABLE_STATUSES = (STATUS_RESOLVED, STATUS_FALSE_POSITIVE)


class FindingsRegistryError(Exception):
    """Wird geworfen, wenn die Registry-Datei existiert, aber nicht sicher
    interpretierbar ist (kaputtes JSON / unerwartetes Schema / beschaedigter
    Finding-Eintrag). Bewusst KEIN stiller Reset auf eine leere Registry
    (Aufgaben-Abschnitt 22) - anders als z. B. MaintenanceModeStore/
    DownloadHistoryStore (dort ist ein Reset auf einen sicheren Default
    unkritisch), waere ein stiller Reset hier ein STILLER VERLUST der
    gesamten Review-Historie (wer hat was wann bewertet, mit welcher
    Notiz) - das ist nicht wiederherstellbar und muss daher immer laut
    fehlschlagen, nie still ueberschrieben werden."""


# ─────────────────────────────────────────────────────────────────────────
# Stabile Finding-ID (Aufgaben-Abschnitt 5/6)
# ─────────────────────────────────────────────────────────────────────────


def _normalize_identity_part(value: object) -> str:
    """Normalisiert ein Identitaets-Feld fuer die Finding-ID: Unicode NFC,
    Whitespace getrimmt, klein geschrieben - eine reine Gross-/
    Kleinschreibungs-Korrektur eines Tags soll kein neues Finding erzeugen."""
    if not value:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip().casefold()


def generate_finding_id(issue: dict) -> str:
    """Erzeugt eine deterministische, stabile Finding-ID aus den fachlich
    relevanten Identitaetsdaten eines Issues (Issue.to_dict()-Schema).

    Bewusst NICHT von Report-Reihenfolge, Scan-Zeitpunkt, Health-Score
    oder Python hash() abhaengig (Aufgaben-Abschnitt 5) - reiner SHA-256
    ueber eine normalisierte, scope-abhaengige Feldkombination.

    Scope-abhaengige Zusammensetzung (Aufgaben-Abschnitt 6 - "nicht blind
    den vollstaendigen Pfad als einzige Identitaet verwenden"):
      - file:   (code, scope, artist, title) wenn BEIDE vorhanden - eine
                reine Umbenennung/Verschiebung (z. B. durch eine spaetere
                Reparatur) aendert dann nicht die Identitaet. Fehlt
                artist ODER title (z. B. META_ARTIST_MISSING - dort FEHLT
                der Artist per Definition), bleibt der (bereits relative)
                Pfad die einzig verbleibende verlaessliche Identitaet.
      - album:  (code, scope, artist, album) - ein Albumordner bleibt bei
                Datei-internen Reparaturen stabil.
      - artist: (code, scope, artist).
      - sonst (z. B. library/Duplicate-Analyse): (code, scope, artist, title).
    """
    code = str(issue.get("issue_code") or "")
    scope = str(issue.get("scope") or "")
    artist = _normalize_identity_part(issue.get("artist"))
    album = _normalize_identity_part(issue.get("album"))
    title = _normalize_identity_part(issue.get("title"))
    path = _normalize_identity_part(issue.get("path"))

    if scope == "file":
        parts = (code, scope, artist, title) if (artist and title) else (code, scope, path)
    elif scope == "album":
        parts = (code, scope, artist, album)
    elif scope == "artist":
        parts = (code, scope, artist)
    else:
        parts = (code, scope, artist, title)

    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────
# Domain-Modelle
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class FindingHistoryEntry:
    status: str
    timestamp: str
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {"status": self.status, "timestamp": self.timestamp, "note": self.note}

    @classmethod
    def from_dict(cls, data: dict) -> "FindingHistoryEntry":
        return cls(
            status=data.get("status", STATUS_OPEN),
            timestamp=data.get("timestamp", ""),
            note=data.get("note"),
        )


@dataclass
class Finding:
    """Ein einzelnes, persistiertes Finding mit vollstaendiger Review-
    Historie (Aufgaben-Abschnitt 4/20)."""

    finding_id: str
    code: str
    scope: str
    status: str = STATUS_OPEN
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    path: Optional[str] = None
    message: str = ""
    first_seen: str = ""
    last_seen: str = ""
    occurrences: int = 1
    present_in_latest_scan: bool = True
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by_scan_at: Optional[str] = None
    reopened_at: Optional[str] = None
    history: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "code": self.code,
            "scope": self.scope,
            "status": self.status,
            "artist": self.artist,
            "album": self.album,
            "title": self.title,
            "path": self.path,
            "message": self.message,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "occurrences": self.occurrences,
            "present_in_latest_scan": self.present_in_latest_scan,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
            "review_note": self.review_note,
            "resolved_at": self.resolved_at,
            "resolved_by_scan_at": self.resolved_by_scan_at,
            "reopened_at": self.reopened_at,
            "history": [h.to_dict() for h in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        return cls(
            finding_id=data["finding_id"],
            code=data.get("code", ""),
            scope=data.get("scope", ""),
            status=data.get("status", STATUS_OPEN),
            artist=data.get("artist"),
            album=data.get("album"),
            title=data.get("title"),
            path=data.get("path"),
            message=data.get("message", ""),
            first_seen=data.get("first_seen", ""),
            last_seen=data.get("last_seen", ""),
            occurrences=int(data.get("occurrences", 1)),
            present_in_latest_scan=bool(data.get("present_in_latest_scan", True)),
            reviewed_at=data.get("reviewed_at"),
            reviewed_by=data.get("reviewed_by"),
            review_note=data.get("review_note"),
            resolved_at=data.get("resolved_at"),
            resolved_by_scan_at=data.get("resolved_by_scan_at"),
            reopened_at=data.get("reopened_at"),
            history=[FindingHistoryEntry.from_dict(h) for h in (data.get("history") or [])],
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────


class FindingsRegistry:
    """Persistenter, atomar geschriebener Speicher fuer Findings (ein
    JSON-Dokument, finding_id -> Finding). Reine Persistenz-/Merge-Logik,
    kein Telegram-/CLI-Bezug (siehe Modul-Docstring)."""

    def __init__(self, path: "str | Path", logger: Optional[object] = None):
        self.path = Path(path)
        self.logger = logger or get_module_logger("LibraryHealthFindings")
        self._findings: dict[str, Finding] = {}
        self._load()

    # ── Persistenz ─────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.path.exists():
            self.logger.info(
                f"📋 Keine bestehende Findings-Registry gefunden, wird neu "
                f"angelegt: {self.path}"
            )
            self._findings = {}
            return

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as e:
            raise FindingsRegistryError(
                f"Library Health Findings Registry ist nicht lesbar: "
                f"{self.path} ({e})"
            ) from e

        if not raw.strip():
            self._findings = {}
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise FindingsRegistryError(
                f"Library Health Findings Registry is invalid (kaputtes "
                f"JSON) in {self.path}: {e}. Datei wurde NICHT ueberschrieben "
                f"- die vorhandene Review-Historie bleibt unangetastet, muss "
                f"aber manuell geprueft/wiederhergestellt werden (z. B. aus "
                f"einem Backup)."
            ) from e

        if (
            not isinstance(data, dict)
            or "findings" not in data
            or not isinstance(data["findings"], dict)
        ):
            raise FindingsRegistryError(
                f"Library Health Findings Registry is invalid (unerwartetes "
                f"Schema) in {self.path}. Datei wurde NICHT ueberschrieben."
            )

        findings: dict[str, Finding] = {}
        for finding_id, finding_data in data["findings"].items():
            try:
                findings[finding_id] = Finding.from_dict(finding_data)
            except Exception as e:  # noqa: BLE001
                raise FindingsRegistryError(
                    f"Library Health Findings Registry is invalid (Finding "
                    f"{finding_id!r} beschaedigt) in {self.path}: {e}. Datei "
                    f"wurde NICHT ueberschrieben."
                ) from e
        self._findings = findings

    def save(self) -> None:
        data = {
            "schema_version": SCHEMA_VERSION,
            "findings": {
                fid: f.to_dict() for fid, f in sorted(self._findings.items())
            },
        }
        self._write_json_atomic(self.path, data)

    @staticmethod
    def _write_json_atomic(path: Path, data: dict) -> None:
        """write-tmp + Path.replace() - dasselbe, im Projekt etablierte
        Muster (INV-02) wie DuplicateCache/DownloadHistoryStore/
        MaintenanceModeStore/AutoLearnManager._write_json_atomic(). Bewusst
        erneut lokal implementiert statt eines gemeinsamen Imports - im
        Projekt existiert kein zentraler geteilter Helfer dafuer, jedes
        Modul haelt seine eigene Kopie desselben Musters (siehe genannte
        Vorbilder)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp_{int(time.time() * 1000)}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_path.replace(path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    # ── Zugriff ────────────────────────────────────────────────────────

    def get(self, finding_id: str) -> Optional[Finding]:
        return self._findings.get(finding_id)

    def all(self) -> list[Finding]:
        return list(self._findings.values())

    def get_open_findings(self) -> list[Finding]:
        return [f for f in self._findings.values() if f.status == STATUS_OPEN]

    def summary(self) -> dict:
        counts = Counter(f.status for f in self._findings.values())
        return {"total": len(self._findings), **{s: counts.get(s, 0) for s in _ALL_STATUSES}}

    # ── Review ─────────────────────────────────────────────────────────

    def review_finding(
        self,
        finding_id: str,
        status: str,
        *,
        note: Optional[str] = None,
        reviewed_by: Optional[str] = None,
        reviewed_at: Optional[str] = None,
    ) -> Finding:
        """Setzt den Review-Status eines Findings (Aufgaben-Abschnitt 3/11).

        Nur RESOLVED/FALSE_POSITIVE sind gueltige Review-Ziele - OPEN ist
        kein Ergebnis einer bewussten Bewertung, sondern der Default-/
        Reopen-Zustand (kein separater REVIEWED-Status, siehe Aufgaben-
        Abschnitt 3: "vermeide unnoetige Komplexitaet").
        """
        finding = self._findings.get(finding_id)
        if finding is None:
            raise KeyError(f"Unbekannte Finding-ID: {finding_id!r}")
        if status not in _REVIEWABLE_STATUSES:
            raise ValueError(
                f"review_finding() akzeptiert nur {_REVIEWABLE_STATUSES!r}, "
                f"nicht {status!r}"
            )
        ts = reviewed_at or _now_iso()
        finding.status = status
        finding.reviewed_at = ts
        finding.reviewed_by = reviewed_by
        finding.review_note = note
        if status == STATUS_RESOLVED:
            finding.resolved_at = ts
        finding.history.append(FindingHistoryEntry(status=status, timestamp=ts, note=note))
        return finding

    # ── Scan-Merge (Aufgaben-Abschnitt 8/9/18/19) ───────────────────────

    def merge_scan_issues(self, issues: list[dict], *, scanned_at: str) -> dict:
        """Gleicht die aktuell erkannten Issues eines Scans mit der
        Registry ab. Mutiert die Registry in-memory - der Aufrufer muss
        anschliessend explizit save() rufen (kein impliziter Autosave, um
        Zwischenzustaende waehrend eines Scans nicht unnoetig oft zu
        schreiben).

        Regeln (siehe Aufgaben-Abschnitt 8/9/18/19):
          - neues Finding                          -> OPEN
          - OPEN, weiterhin erkannt                 -> bleibt OPEN
          - RESOLVED/RESOLVED_BY_SCAN, wieder erkannt -> REOPEN zu OPEN
            (Regression: der Nutzer hielt es fuer behoben/der Scanner
            hatte es nicht mehr gesehen, jetzt ist es wieder da)
          - FALSE_POSITIVE, wieder erkannt          -> bleibt FALSE_POSITIVE
            (bewusst KEIN Reopen - identische Identitaet bedeutet
            identischer, bereits bewusst akzeptierter Sachverhalt)
          - bekanntes Finding, JETZT nicht mehr erkannt, Status war OPEN
            -> RESOLVED_BY_SCAN (technischer Zwischenzustand, siehe
            STATUS_RESOLVED_BY_SCAN)
          - bekanntes Finding, JETZT nicht mehr erkannt, Status war
            RESOLVED/FALSE_POSITIVE/RESOLVED_BY_SCAN -> unveraendert
            (Historie bleibt erhalten, kein Loeschen - Aufgaben-Abschnitt 8)
        """
        seen_ids: set[str] = set()
        created = 0
        reopened = 0
        resolved_by_scan = 0

        for issue in issues:
            finding_id = generate_finding_id(issue)
            seen_ids.add(finding_id)
            existing = self._findings.get(finding_id)

            if existing is None:
                self._findings[finding_id] = Finding(
                    finding_id=finding_id,
                    code=issue.get("issue_code", ""),
                    scope=issue.get("scope", ""),
                    status=STATUS_OPEN,
                    artist=issue.get("artist"),
                    album=issue.get("album"),
                    title=issue.get("title"),
                    path=issue.get("path"),
                    message=issue.get("message", ""),
                    first_seen=scanned_at,
                    last_seen=scanned_at,
                    occurrences=1,
                    present_in_latest_scan=True,
                    history=[FindingHistoryEntry(status=STATUS_OPEN, timestamp=scanned_at)],
                )
                created += 1
                continue

            existing.last_seen = scanned_at
            existing.occurrences += 1
            existing.present_in_latest_scan = True
            # Reine Anzeige-Daten auffrischen (keine Identitaet - die
            # steckt ausschliesslich in der Finding-ID selbst).
            existing.message = issue.get("message", existing.message)
            existing.path = issue.get("path", existing.path)

            if existing.status in (STATUS_RESOLVED, STATUS_RESOLVED_BY_SCAN):
                existing.status = STATUS_OPEN
                existing.reopened_at = scanned_at
                existing.history.append(
                    FindingHistoryEntry(
                        status=STATUS_OPEN, timestamp=scanned_at,
                        note="Reopened - erneut erkannt",
                    )
                )
                reopened += 1
            # FALSE_POSITIVE bleibt bewusst unveraendert (kein Reopen).
            # OPEN bleibt OPEN (keine History-Eintragung fuer "weiterhin
            # unveraendert offen" - das wuerde die Historie pro Scan
            # unnoetig aufblaehen).

        for finding_id, finding in self._findings.items():
            if finding_id in seen_ids:
                continue
            finding.present_in_latest_scan = False
            # Nur OPEN -> RESOLVED_BY_SCAN transitionieren. Ein Finding,
            # das bereits in einem frueheren Merge auf RESOLVED_BY_SCAN
            # gesetzt wurde, ist zu diesem Zeitpunkt nicht mehr OPEN -
            # dieser Zweig greift also nur genau beim UEBERGANG von
            # "erkannt" zu "nicht mehr erkannt", nicht bei jedem
            # weiteren Scan, in dem es weiterhin fehlt.
            if finding.status == STATUS_OPEN:
                finding.status = STATUS_RESOLVED_BY_SCAN
                finding.resolved_by_scan_at = scanned_at
                finding.history.append(
                    FindingHistoryEntry(
                        status=STATUS_RESOLVED_BY_SCAN, timestamp=scanned_at,
                        note="Vom Scanner nicht mehr erkannt (nicht vom Nutzer bestätigt)",
                    )
                )
                resolved_by_scan += 1

        return {
            "created": created,
            "reopened": reopened,
            "resolved_by_scan": resolved_by_scan,
            "total_in_registry": len(self._findings),
        }


# ─────────────────────────────────────────────────────────────────────────
# Report-Integration (additiv, siehe report.py::render_summary_markdown())
# ─────────────────────────────────────────────────────────────────────────


def annotate_issues_with_findings(issues: list[dict], registry: FindingsRegistry) -> list[dict]:
    """Reichert eine Liste von Issue-Dicts additiv um `finding_id`/
    `finding_status`/`finding_reviewed_at`/`finding_review_note` an.

    Rein additiv (Aufgaben-Abschnitt 14: "Nicht einfach bereits bestätigte
    Issues aus dem historischen Report entfernen") - keine vorhandenen
    Felder werden veraendert oder entfernt, es werden neue Kopien der
    Dicts zurueckgegeben (kein In-place-Mutieren der Eingabe)."""
    annotated: list[dict] = []
    for issue in issues:
        finding_id = generate_finding_id(issue)
        finding = registry.get(finding_id)
        new_issue = dict(issue)
        new_issue["finding_id"] = finding_id
        if finding is not None:
            new_issue["finding_status"] = finding.status
            new_issue["finding_reviewed_at"] = finding.reviewed_at
            new_issue["finding_review_note"] = finding.review_note
        else:
            new_issue["finding_status"] = STATUS_OPEN
            new_issue["finding_reviewed_at"] = None
            new_issue["finding_review_note"] = None
        annotated.append(new_issue)
    return annotated


def build_findings_summary(annotated_issues: list[dict]) -> dict:
    """Aggregiert die Findings-Statusverteilung der AKTUELL erkannten
    Issues eines Scans (Aufgaben-Abschnitt 14) - bewusst nicht die
    gesamte, historische Registry (die kann auch laengst nicht mehr
    erkannte RESOLVED_BY_SCAN-Findings enthalten)."""
    counts = Counter(i.get("finding_status", STATUS_OPEN) for i in annotated_issues)
    return {
        "total_detected": len(annotated_issues),
        "open": counts.get(STATUS_OPEN, 0),
        "resolved": counts.get(STATUS_RESOLVED, 0),
        "false_positive": counts.get(STATUS_FALSE_POSITIVE, 0),
    }
