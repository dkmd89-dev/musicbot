# MusicBot — Post-Baseline-v4 Health & Risk Audit

> Strikt read-only Audit nach `docs/archive/MusicBot_ENGINEERING_BASELINE_v4.md`
> (Freeze 2026-08-26, 1107 passed/0 failed). Ziel: unabhängig verifizieren,
> ob seit dem Freeze neue P0/P1-Risiken bestehen, und eine Entscheidungsvorlage
> für die nächste Phase (Engineering-Fix vs. Produktphase) erzeugen. Die
> anschließend freigegebenen Fixes sind in
> `docs/archive/MusicBot_ENGINEERING_BASELINE_v5.md` dokumentiert.

---

## 1. Repository- und Baseline-Verifikation

```
Branch: main
HEAD:   4591bef (docs: CLAUDE.md auf Baseline v4 verweisen + Freeze-Abschluss-Automatik)
Status: clean
```

BASELINE CONSISTENT — CLAUDE.md/README.md/docs/INDEX.md verweisen konsistent auf v4.

## 2. Testverifikation

```
python3 -m pytest tests/ -q
1107 passed, 1 warning, 19 subtests passed in 86.22s
```

Exakt identisch zu Baseline v4. Keine Regression.

## 3. AE-10/AE-11/AE-12 Re-Verifikation

Direkt im aktuellen Code gelesen (nicht nur Dokumentation): `chart_renderer.py`
(Agg-Backend, `_render_lock`, alle 6 Call-Sites über `asyncio.to_thread()`),
`tag_writer.py` (Copy→Tag→Replace, Exception-Propagation), `enhanced_metadata_processor.py`
(`write_tags()` weiterhin über `asyncio.to_thread()`) — **alle drei vollständig
intakt, kein Rückfall.**

## 4. Download-Pipeline (eigener Plan aus Sessionbeginn)

Ein zu Sessionbeginn erstellter Plan (Event-Loop-Blocking bei `extract_info`,
fehlende URL-Allowlist, tote Resource-Limits in der Download-Pipeline) erwies
sich als bereits vollständig implementiert — Commit `4715394`, praktisch am
Projektanfang. Plan gegenstandslos, nichts zu tun.

## 5. Neue Findings

| # | Finding | Bereich | Prio | Evidenz |
|---|---|---|---|---|
| 1 | `check_for_duplicates()` wurde produktiv nur mit `url=` aufgerufen (`klassen/download_handler.py`) — Artist+Titel/Parser/Library-Fallback-Ebenen (`services/duplicate/detector.py`) waren im echten Pre-Download-Pfad toter Code | Duplicate Detection | **P1** | grep-verifiziert: einziger Produktiv-Call-Site im gesamten Repo |
| 2 | `renamed_due_to_conflict` wurde nirgends gesetzt (`move_to_library()` gab nur `Path` zurück) — Dateinamens-Kollisionen wurden nie erkannt/aufgeräumt/gemeldet | Duplicate Detection / Library | **P1** | grep-verifiziert: einzige Fundstelle war der Read selbst; `move_to_library()`-Signatur direkt gelesen |
| 3 | Fanart-API-Key konnte bei `LOG_LEVEL=DEBUG` über `str(RequestException)` im Klartext geloggt werden (`services/metadata/cover_processor.py::_get()`), analog zu einem bereits in `navidrome_api.py` behobenen Bug | Security | **P1** | Code direkt gelesen, Default-Log-Level `INFO` bestätigt |
| 4 | Verwaiste Teildatei bei Task-Cancellation in `download_executor.py::download_single_track()` | Concurrency | P2 | Subagent-Sweep, chiefly Shutdown-Szenario |
| 5 | `services/statistik/statistics_calculator.py::export_stats_to_json()` — nicht-atomarer Write | INV-02 | P3 | One-Shot-Exportartefakt, kein App-State |
| 6 | `handlers/enhanced_error_handler.py` ist seit Initial-Commit voll integriert (`bot.py` registriert ihn als globalen Telegram-Error-Handler) — Baseline-Doku (v3→v4 geerbt) sagt fälschlich „PLANNED / NOT INTEGRATED" | Dokumentation | P3 | selbst verifiziert: `bot.py` `add_error_handler`, `git log` zeigt Ursprung im Initial-Commit |
| 7 | Undokumentierter Loudness-Normalisierungs-Schritt in der Metadata-Pipeline + Debug-Log-Rauschen auf INFO-Level | Dokumentation | P3 | — |
| 8 | `pylast.LastFMNetwork.__repr__()` würde Secrets einbetten, aktuell nirgends geloggt (latent) | Security (latent) | P3 | — |

Bestätigt, keine neue Evidenz: `duplicate/cache.py` INV-01 (bewusst deferred),
URL-Normalisierung in `cache.py` (solide: youtu.be, Tracking-Parameter,
Playlist-ID-Extraktion), Metadata-Pipeline-Fallback-Kette (kein Service-Ausfall
killt einen Track), Cache-Hit-Logik (Video-ID-verankert, kein False-Positive-Pfad),
`navidrome_api.py`/`genius_client.py` (bereits sauber), `config.py`-Maskierung,
`test_menu_handler.py` Admin-Gating (`AccessLevel.ADMIN` an allen 3 Menüpunkten,
selbst verifiziert).

## 6. Entscheidung

**OPTION A (eng begrenzt)** — drei kleine, unabhängige Engineering-Fixes
(Finding 1–3), kein neuer Architektur-Freeze-Bruch, keine große Phase. Details,
Umsetzung und Regressionstests: `docs/archive/MusicBot_ENGINEERING_BASELINE_v5.md`.

## 7. Explicit Non-Actions (während des Audits selbst)

```
[x] Kein Produktionscode geändert (im Audit-Schritt selbst)
[x] Keine Tests geändert (im Audit-Schritt selbst)
[x] Keine Mapping-Dateien geändert
[x] Keine Architekturänderung
[x] Keine P2/P3-Probleme vorsorglich behoben
[x] Kein Commit/Push/PR während des Audits selbst
```

Die anschließend vom Nutzer freigegebenen Fixes (Finding 1–3) sind ein
separater, nachgelagerter Schritt — siehe Baseline v5.
