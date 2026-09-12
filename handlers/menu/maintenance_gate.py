# handlers/menu/maintenance_gate.py
# -*- coding: utf-8 -*-
"""
Gemeinsamer Wartungsmodus-Gate-Check für alle Telegram-Einstiegspunkte
(RichMenuHandler UND RichMenuSystem, siehe deren jeweilige Docstrings zur
Wartungsmodus-Verdrahtung sowie services/bot_maintenance.py für die
Architekturbegründung).

Freie Funktion statt Methode auf einer der beiden Klassen, da beide
(RichMenuHandler UND RichMenuSystem) sie unabhängig voneinander an ihren
eigenen Einstiegspunkten aufrufen müssen - vermeidet eine künstliche
Abhängigkeit der einen Klasse von der anderen nur für diesen einen Check.
"""

from telegram import Update
from telegram.ext import ContextTypes

from handlers.menu.permissions import is_admin_or_owner

_MAINTENANCE_MESSAGE = (
    "🛠️ Der Bot befindet sich aktuell im Wartungsmodus.\n\n"
    "Bitte versuche es später erneut."
)


async def is_blocked_by_maintenance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    maintenance_store,
    config,
    logger,
) -> bool:
    """
    Liefert True (und sendet bereits die Wartungsmeldung), wenn der
    Wartungsmodus aktiv ist UND der aufrufende User kein Admin/Owner ist -
    in diesem Fall MUSS der Aufrufer sofort zurückkehren, ohne die
    eigentliche Handler-Logik auszuführen.

    Admin/Owner werden NIE blockiert - andernfalls gäbe es keinen Weg
    zurück zum Ausschalten des Wartungsmodus, da der blockierende Check
    selbst vor jedem Einstiegspunkt steht (siehe
    services/bot_maintenance.py-Docstring für die vollständige
    Begründung).

    maintenance_store darf None sein (z. B. in Tests, die die Handler-
    Konstruktion per object.__new__() umgehen, siehe etabliertes Muster
    dieser Session für active_downloads/download_history) - liefert dann
    unauffällig False (kein Wartungsmodus aktiv), kein AttributeError.
    """
    if maintenance_store is None or not maintenance_store.is_active():
        return False

    user_id = update.effective_user.id if update.effective_user else None
    # ARCH-023/P-4 Phase 3: vormals inline duplizierte Pruefung durch die
    # gemeinsame, bereits getestete permissions.is_admin_or_owner()
    # ersetzt - funktional aequivalent (inkl. user_id=None-Randfall),
    # keine Verhaltensaenderung.
    if is_admin_or_owner(user_id, config):
        return False

    if update.callback_query:
        await update.callback_query.answer(_MAINTENANCE_MESSAGE, show_alert=True)
    elif update.message:
        await update.message.reply_text(_MAINTENANCE_MESSAGE)

    logger.info(f"🛠️ [MAINTENANCE] User {user_id} während Wartungsmodus blockiert")
    return True
