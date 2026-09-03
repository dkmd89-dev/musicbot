# handlers/menu/activity_tracking.py
# -*- coding: utf-8 -*-
"""
Gemeinsamer User-Aktivitäts-Aufzeichnungs-Helfer für alle Telegram-
Einstiegspunkte (RichMenuHandler UND RichMenuSystem, analog zu
handlers/menu/maintenance_gate.py::is_blocked_by_maintenance()).

Funktions-Fund (docs/audits/HANDLER_METHOD_LEVEL_SWEEP_2026-09-03.md,
2026-09-03): der "🤖 Bot-Status"-Screen (handlers/enhanced_status_handler.py
::show_bot_status()) zeigt "Aktive Users"/"Letzte Aktivitäten" aus
BotStatusTracker.get_user_activity() an - aber BotStatusTracker.
record_user_activity() wurde nirgends aufgerufen, die Anzeige war dadurch
dauerhaft leer/0. Fix: dieselben 7 Einstiegspunkte, die bereits für den
Wartungsmodus-Gate-Check instrumentiert sind, rufen jetzt zusätzlich
diesen Helfer auf - direkt nach dem Gate-Check (nur tatsächlich
durchgelassene Interaktionen zählen als "Aktivität", ein waehrend des
Wartungsmodus abgewiesener Versuch nicht).

Freie Funktion statt Methode auf einer der beiden Klassen, aus demselben
Grund wie bei maintenance_gate.py - beide Klassen rufen sie unabhängig
voneinander an ihren eigenen Einstiegspunkten auf.
"""

from telegram import Update


def record_activity(update: Update, status_handler, activity_type: str) -> None:
    """
    Zeichnet eine User-Interaktion im geteilten BotStatusTracker auf
    (status_handler.bot_tracker.record_user_activity()).

    status_handler darf None sein (eigene Initialisierung fehlgeschlagen,
    oder Tests, die die Handler-Konstruktion per object.__new__()
    umgehen, siehe etabliertes Muster dieser Session) - No-op statt
    AttributeError. Fehler beim Aufzeichnen werden bewusst verschluckt
    (reine Diagnose-/Anzeige-Funktion, darf niemals eine sonst
    erfolgreiche Nutzer-Interaktion zum Absturz bringen).
    """
    if status_handler is None:
        return
    bot_tracker = getattr(status_handler, "bot_tracker", None)
    if bot_tracker is None:
        return
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return
    try:
        bot_tracker.record_user_activity(user_id, activity_type)
    except Exception:
        pass
