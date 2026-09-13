# handlers/statistik_format_helpers.py
# -*- coding: utf-8 -*-
"""
Geteilte Telegram-Presentation-Helfer für Personal- und Family-Statistics
(MASTER PHASE B, Family Statistics Attribution/Identity/UX Optimization,
Abschnitt 26.1).

Extrahiert 1:1 aus handlers/mugge_statistik_handler.py::StatistikHandler
(vorher private Instanzmethoden `_format_plays()`/`_format_rank()`/
`_format_date_range()` + Modulkonstante `_RANK_MEDALS`) - reine Move-
Operation, kein Verhaltensunterschied. `StatistikHandler` behält seine
gleichnamigen Instanzmethoden als dünne Delegatoren auf dieses Modul
(bestehende Call-Sites/Tests bleiben unverändert lauffähig).
`handlers/family_stats_handler.py` importiert direkt von hier - EINE
Formatierungsquelle statt einer zweiten, potenziell abweichenden Kopie
(Abschnitt 26.1: "Eine zweite Formatierungs-Quelle führt zwangsläufig zu
Drift bei der nächsten Änderung").

Absichtlich HIER, nicht in helfer/markdown_helfer.py: diese Funktionen
sind reine Statistics-Presentation (Play-Pluralisierung, Rang-Symbole,
Datumsbereiche), keine allgemeinen MarkdownV2-Escaping-Helfer.
"""

from datetime import datetime, timedelta

# Rang-Symbole für Top-N-Listen: 1.-3. Platz mit Medaille, ab 4. Platz
# reine Zahl mit Punkt.
RANK_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# 20 Zeichen, identisch zur bisherigen
# mugge_statistik_handler.py::StatistikHandler._TIMELINE_SEPARATOR -
# EINE Trennlinien-Konstante statt einer zweiten, optisch abweichenden
# Kopie (Abschnitt 15/26.1).
SEPARATOR = "────────────────────"


def format_plays(count: int) -> str:
    """Zentrale Play-Pluralisierung ("1 Play" / "2 Plays")."""
    return f"{count} {'Play' if count == 1 else 'Plays'}"


def format_rank(position: int) -> str:
    """1-basierter Rang -> Medaille (1.-3. Platz) oder reine Zahl mit
    Punkt (ab 4. Platz)."""
    return RANK_MEDALS.get(position, f"{position}.")


def format_date_range(period_start: datetime, period_end: datetime) -> str:
    """
    Der Calculator liefert ausschließlich `period_start`/`period_end`
    (exklusiv) - reine Rohdaten, keine UI-Datumsstrings. Diese
    Presentation-Funktion berechnet daraus den inklusiven Endpunkt
    (`period_end - 1 Tag`) und formatiert den sichtbaren Bereich:

      - "07.–13.09.2026"   (Woche/Monat innerhalb desselben Monats/Jahres)
      - "28.09.–04.10.2026" (Woche über einen Monatswechsel hinweg)
      - "28.12.2026–03.01.2027" (Woche über einen Jahreswechsel hinweg)

    Ein Kalendermonat selbst liegt immer vollständig in einem Monat/Jahr
    (period_end - 1 Tag landet für "month" immer im selben Monat wie
    period_start), nur eine Kalenderwoche kann einen Monats-/
    Jahreswechsel überspannen - daher die zusätzlichen Zweige.
    """
    end_inclusive = period_end - timedelta(days=1)

    if period_start.year != end_inclusive.year:
        return (
            f"{period_start.strftime('%d.%m.%Y')}"
            f"–{end_inclusive.strftime('%d.%m.%Y')}"
        )
    if period_start.month != end_inclusive.month:
        return (
            f"{period_start.strftime('%d.%m')}."
            f"–{end_inclusive.strftime('%d.%m.%Y')}"
        )
    return f"{period_start.strftime('%d')}.–{end_inclusive.strftime('%d.%m.%Y')}"
