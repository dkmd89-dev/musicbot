# handlers/menu/actions/library.py
# -*- coding: utf-8 -*-
"""
Admin > Bibliothek & Navidrome-Actions: Reprocessing, MusicBot Doctor,
Library Health Review, Repair MusicBot - entspricht der bestehenden
"admin_group_library"-Gruppierung in initialize_menu_structure()
(Navidrome-Scan selbst liegt in actions/admin_operations.py, da dort
keine eigene Handler-Klasse existiert - reine RichMenuHandler-Logik).

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py verschoben (reine Move-Operation).
Jede Callback-Dispatcher-Funktion behält ihre eigene, historisch
bewusst unterschiedliche Defense-in-Depth-Berechtigungsprüfung
(Reprocessing: reiner Owner-Check gegen config.OWNER_USER_ID; Doctor/
Review/Repair: is_admin_check-Callable, siehe ARCH-023/P-3) -
keine Vereinheitlichung, das war ARCH-023-Scope und ist abgeschlossen.
"""

from telegram import Update
from telegram.ext import ContextTypes

from handlers.menu.actions._common import show_handler_not_available
from services.library_repair.maintenance_service import ACTION_SET_GENRE
from services.library_repair.maintenance_service import ALL_ACTIONS as _ALL_MAINTENANCE_ACTIONS

# Library Genre Management v2 (Chat-Charakterisierung 2026-09-15):
# ACTION_SET_GENRE ist ueber die generische "libmaint:action/confirm/
# execute:<action>:<idx>"-Route bewusst NICHT mehr erreichbar - kein
# Button erzeugt mehr "libmaint:action:set-genre:*" (siehe
# handlers/library_maintenance_handler.py::_preview_fn()/_execute_fn(),
# die diesen Eintrag entfernt haben). Ohne diesen Ausschluss wuerde ein
# von Hand konstruiertes "libmaint:action:set-genre:0"-callback_data
# (SEC-003: callback_data ist frei sendbar) zu einem unbehandelten
# KeyError statt einer sauberen Fehlermeldung fuehren - Genre setzen
# laeuft jetzt ausschliesslich ueber den neuen "🎭 Genre-Verwaltung"-Flow
# (libmaint:genremenu:*/gs:*/gr:*/missing*).
_MAINTENANCE_ACTIONS = tuple(a for a in _ALL_MAINTENANCE_ACTIONS if a != ACTION_SET_GENRE)


# ====== METADATA-REPROCESSING ======


async def handle_reprocessing_show(update: Update, context: ContextTypes.DEFAULT_TYPE, reprocessing_handler):
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu den
    Navidrome-Actions."""
    if reprocessing_handler:
        await reprocessing_handler.show_artist_list(update, context)
    else:
        await show_handler_not_available(update, "Reprocessing-Handler")


async def handle_reprocessing_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    reprocessing_handler,
    config,
    logger,
) -> None:
    """
    Dispatcher für alle reprocess:* Callbacks.

    Routing:
      reprocess:show        → Artist-Liste anzeigen
      reprocess:pick:<idx>  → Dry-Run für Artist <idx> starten
      reprocess:live:<idx>  → LIVE-Lauf für Artist <idx> starten

    Eigener Owner-Check hier (Defense-in-Depth, analog zu maint: -
    bewusst NICHT in _ADMIN_ONLY_PREFIXES aufgenommen, da OWNER
    strenger als ADMIN ist und dieser Dispatcher seinen eigenen,
    passenden Check macht statt sich auf den ADMIN-Check zu verlassen).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if user_id != getattr(config, "OWNER_USER_ID", None):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Owner {user_id} versuchte "
            f"Reprocessing-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not reprocessing_handler:
        await query.answer("⚠️ Reprocessing-Handler nicht verfügbar", show_alert=True)
        return

    if callback_data == "reprocess:show":
        await reprocessing_handler.show_artist_list(update, context)
        return

    if callback_data.startswith("reprocess:pick:"):
        idx_str = callback_data[len("reprocess:pick:") :]
        try:
            idx = int(idx_str)
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await reprocessing_handler.handle_pick(update, context, idx)
        return

    if callback_data.startswith("reprocess:live:"):
        idx_str = callback_data[len("reprocess:live:") :]
        try:
            idx = int(idx_str)
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await reprocessing_handler.handle_live(update, context, idx)
        return

    await query.answer("⚠️ Unbekannter Reprocessing-Callback")


# ====== MUSICBOT DOCTOR (Phase 3, P1.3) ======


async def handle_doctor_scan(update: Update, context: ContextTypes.DEFAULT_TYPE, doctor_handler):
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
    handle_reprocessing_show()."""
    if doctor_handler:
        await doctor_handler.handle_scan(update, context)
    else:
        await show_handler_not_available(update, "Doctor-Handler")


async def handle_doctor_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    doctor_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle doctor:* Callbacks.

    Routing:
      doctor:scan                 → Health-Scan starten (auch über
                                     den Menüpunkt direkt erreichbar)
      doctor:apply_safe           → Bestätigung vor SAFE_AUTOMATIC-Apply
      doctor:apply_safe_confirm   → SAFE_AUTOMATIC-Apply tatsächlich starten
      doctor:score_history        → Health-Score-Verlauf anzeigen (read-only)

    Eigener Admin-Check hier (Defense-in-Depth, analog zu maint:/
    reprocess: - callback_data ist frei sendbar, siehe SEC-003).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if not is_admin_check(user_id):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
            f"Doctor-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not doctor_handler:
        await query.answer("⚠️ Doctor-Handler nicht verfügbar", show_alert=True)
        return

    if callback_data == "doctor:scan":
        await doctor_handler.handle_scan(update, context)
        return

    if callback_data == "doctor:apply_safe":
        await doctor_handler.handle_apply_safe_confirm_prompt(update, context)
        return

    if callback_data == "doctor:apply_safe_confirm":
        await doctor_handler.handle_apply_safe_confirmed(update, context)
        return

    if callback_data == "doctor:score_history":
        await doctor_handler.handle_score_history(update, context)
        return

    await query.answer("⚠️ Unbekannter Doctor-Callback")


# ====== LIBRARY HEALTH REVIEW ======


async def handle_review_start(update: Update, context: ContextTypes.DEFAULT_TYPE, review_handler):
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
    handle_doctor_scan()."""
    if review_handler:
        await review_handler.handle_start(update, context)
    else:
        await show_handler_not_available(update, "Review-Handler")


async def handle_review_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    review_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle review:* Callbacks.

    Routing (siehe handlers/library_health_review_handler.py):
      review:start                    → Übersicht (Severity-Verteilung)
      review:severity:<TIER>          → Kategorien dieser Severity-Stufe
      review:category:<CODE>          → Kategorie-Aktionen
      review:edit:<CODE>              → Einzelreview starten
      review:resolve:<finding_id>     → Resolve im Einzelreview
      review:fp:<finding_id>          → False Positive im Einzelreview
      review:skip:<finding_id>        → Skip im Einzelreview
      review:quit:<finding_id>        → Review beenden
      review:batchconfirm:<CODE>      → Bestätigung vor Batch-False-Positive
      review:batchyes:<CODE>          → Batch-False-Positive ausführen
      review:accepted                 → Liste der akzeptierten Findings (nach Code)
      review:acccode:<CODE>           → akzeptierte Findings dieser Kategorie
      review:accshow:<finding_id>     → ein akzeptiertes Finding (Detail)
      review:unaccept:<finding_id>    → Acceptance zurücknehmen (→ OPEN)

    Eigener Admin-Check hier (Defense-in-Depth, analog zu doctor:/
    maint:/reprocess: - callback_data ist frei sendbar, siehe SEC-003).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if not is_admin_check(user_id):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
            f"Review-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not review_handler:
        await query.answer("⚠️ Review-Handler nicht verfügbar", show_alert=True)
        return

    if callback_data == "review:start":
        await review_handler.handle_start(update, context)
        return
    if callback_data == "review:accepted":
        await review_handler.handle_accepted_list(update, context)
        return

    parts = callback_data.split(":", 2)
    if len(parts) < 3:
        await query.answer("⚠️ Unbekannter Review-Callback")
        return
    action, payload = parts[1], parts[2]

    if action == "severity":
        await review_handler.handle_severity(update, context, payload)
    elif action == "category":
        await review_handler.handle_category(update, context, payload)
    elif action == "edit":
        await review_handler.handle_edit_start(update, context, payload)
    elif action == "batchconfirm":
        await review_handler.handle_batch_confirm_prompt(update, context, payload)
    elif action == "batchyes":
        await review_handler.handle_batch_confirmed(update, context, payload)
    elif action in ("resolve", "fp", "skip", "quit"):
        await review_handler.handle_single_action(update, context, action, payload)
    elif action == "acccode":
        await review_handler.handle_accepted_category(update, context, payload)
    elif action == "accshow":
        await review_handler.handle_accepted_show(update, context, payload)
    elif action == "unaccept":
        await review_handler.handle_unaccept(update, context, payload)
    else:
        await query.answer("⚠️ Unbekannter Review-Callback")


# ====== REPAIR MUSICBOT ======


async def handle_repair_start(update: Update, context: ContextTypes.DEFAULT_TYPE, repair_handler):
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
    handle_doctor_scan()/handle_review_start()."""
    if repair_handler:
        await repair_handler.handle_start(update, context)
    else:
        await show_handler_not_available(update, "Repair-Handler")


async def handle_repair_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    repair_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle repair:* Callbacks.

    Routing (siehe handlers/repair_musicbot_handler.py):
      repair:start      → Startseite
      repair:analyze    → Reparaturen analysieren / Offene Reparaturen
      repair:proposals  → Reparaturvorschläge (SAFE_AUTOMATIC)
      repair:preview    → Read-only Vorschau
      repair:confirm    → explizite Bestätigung vor Ausführung
      repair:execute    → tatsächliche Ausführung (Berechtigung erneut geprüft)
      repair:history    → Reparaturhistorie
      repair:stats      → Repair-Statistik

    Eigener Admin-Check hier (Defense-in-Depth, analog zu doctor:/
    review:/maint:/reprocess: - callback_data ist frei sendbar, siehe
    SEC-003).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if not is_admin_check(user_id):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
            f"Repair-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not repair_handler:
        await query.answer("⚠️ Repair-Handler nicht verfügbar", show_alert=True)
        return

    routing = {
        "repair:start": repair_handler.handle_start,
        "repair:analyze": repair_handler.handle_analyze,
        "repair:proposals": repair_handler.handle_proposals,
        "repair:preview": repair_handler.handle_preview,
        "repair:confirm": repair_handler.handle_confirm_prompt,
        "repair:execute": repair_handler.handle_execute,
        "repair:history": repair_handler.handle_history,
        "repair:stats": repair_handler.handle_statistics,
    }
    handler_fn = routing.get(callback_data)
    if handler_fn is None:
        await query.answer("⚠️ Unbekannter Repair-Callback")
        return
    await handler_fn(update, context)


# ====== LIBRARY-WARTUNG (ARCH-032 Phase 4) ======


async def handle_library_maintenance_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, maintenance_handler
) -> None:
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
    handle_repair_start()."""
    if maintenance_handler:
        await maintenance_handler.handle_start(update, context)
    else:
        await show_handler_not_available(update, "Library-Wartung-Handler")


async def handle_library_maintenance_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    maintenance_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle libmaint:* Callbacks.

    Routing (siehe handlers/library_maintenance_handler.py):
      libmaint:start                    → Startseite
      libmaint:artists                  → Artist-Liste (Index-Picker)
      libmaint:pick:<idx>                → Aktions-Auswahl für diesen Artist
      libmaint:action:<action>:<idx>     → Preview (read-only, NUR artist-casing/
                                          legacy-genre-cleanup - set-genre laeuft
                                          seit Library Genre Management v2 ueber
                                          die genremenu:/gs:-Routen unten)
      libmaint:confirm:<action>:<idx>    → explizite Bestätigung
      libmaint:execute:<action>:<idx>    → tatsächliche Ausführung
      libmaint:genremenu:<idx>           → 🎭 Genre-Verwaltung für diesen Artist
      libmaint:missing                   → 🧹 Fehlende Genres (Finding-Artist-Liste)
      libmaint:missingpick:<idx>         → Artist aus dieser Liste wählen
      libmaint:gs:src/mapping/manual/mode:<m>/save:<s>/confirm/execute
                                          → ✏️ Genre setzen (Quelle→Modus→
                                          Mapping speichern?→Preview→Execute)
      libmaint:gr:preview/confirm/execute → 🔄 Genre revalidieren (Subprozess,
                                          siehe genre_revalidation_runner.py)
      libmaint:meta:<idx>/artist:*/title:*
                                          → 📝 Metadaten bearbeiten (Manual
                                          Metadata Editing v1) - Artist
                                          bearbeiten / Titel bearbeiten
                                          (eigener Track-Picker) /
                                          Genre-Verwaltung (Verweis auf
                                          genremenu:* oben, keine
                                          Duplizierung)

    Eigener Admin-Check hier (Defense-in-Depth, analog zu doctor:/review:/
    repair:/reprocess: - callback_data ist frei sendbar, siehe SEC-003).
    Bewusst NICHT "maint:" (bereits durch den Bot-Wartungsmodus belegt,
    siehe rich_menu_system.py::_handle_maintenance_callback()).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if not is_admin_check(user_id):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
            f"Library-Wartung-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not maintenance_handler:
        await query.answer("⚠️ Library-Wartung-Handler nicht verfügbar", show_alert=True)
        return

    if callback_data == "libmaint:start":
        await maintenance_handler.handle_start(update, context)
        return
    if callback_data == "libmaint:artists":
        await maintenance_handler.handle_artist_list(update, context)
        return

    parts = callback_data.split(":")

    if len(parts) == 3 and parts[1] == "pick":
        try:
            idx = int(parts[2])
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await maintenance_handler.handle_pick_artist(update, context, idx)
        return

    if len(parts) == 4 and parts[1] in ("action", "confirm", "execute"):
        action, idx_str = parts[2], parts[3]
        try:
            idx = int(idx_str)
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        if action not in _MAINTENANCE_ACTIONS:
            await query.answer("⚠️ Unbekannte Aktion", show_alert=True)
            return
        if parts[1] == "action":
            await maintenance_handler.handle_preview(update, context, action, idx)
        elif parts[1] == "confirm":
            await maintenance_handler.handle_confirm_prompt(update, context, action, idx)
        else:
            await maintenance_handler.handle_execute(update, context, action, idx)
        return

    # ── 🎭 Genre-Verwaltung (Library Genre Management v2,
    # Chat-Charakterisierung 2026-09-15) ────────────────────────────────

    if len(parts) == 3 and parts[1] == "genremenu":
        try:
            idx = int(parts[2])
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await maintenance_handler.handle_genre_menu(update, context, idx)
        return

    if callback_data == "libmaint:missing":
        await maintenance_handler.handle_missing_genre_start(update, context)
        return
    if len(parts) == 3 and parts[1] == "missingpick":
        try:
            idx = int(parts[2])
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await maintenance_handler.handle_missing_genre_pick(update, context, idx)
        return

    if len(parts) >= 3 and parts[1] == "gs":
        sub = parts[2]
        if sub == "src":
            await maintenance_handler.handle_gs_src(update, context)
            return
        if sub == "mapping":
            await maintenance_handler.handle_gs_mapping(update, context)
            return
        if sub == "manual":
            await maintenance_handler.handle_gs_manual(update, context)
            return
        if sub == "mode" and len(parts) == 4 and parts[3] in ("overwrite", "onlymissing"):
            await maintenance_handler.handle_gs_mode(update, context, parts[3])
            return
        if sub == "save" and len(parts) == 4 and parts[3] in ("yes", "no"):
            await maintenance_handler.handle_gs_save(update, context, parts[3] == "yes")
            return
        if sub == "confirm":
            await maintenance_handler.handle_gs_confirm(update, context)
            return
        if sub == "execute":
            await maintenance_handler.handle_gs_execute(update, context)
            return
        await query.answer("⚠️ Unbekannter Genre-Setzen-Callback")
        return

    if len(parts) == 3 and parts[1] == "gr":
        sub = parts[2]
        if sub == "preview":
            await maintenance_handler.handle_gr_preview(update, context)
            return
        if sub == "confirm":
            await maintenance_handler.handle_gr_confirm(update, context)
            return
        if sub == "execute":
            await maintenance_handler.handle_gr_execute(update, context)
            return
        await query.answer("⚠️ Unbekannter Genre-Revalidierung-Callback")
        return

    # ── 📝 Metadaten bearbeiten (Manual Metadata Editing v1) ─────────────
    # libmaint:meta:<idx>                        -> Aktions-Auswahl (Artist/
    #                                               Titel/Genre-Verwaltung)
    # libmaint:meta:artist:<idx>                 -> Freitext-Eingabe starten
    # libmaint:meta:artist:confirm/execute       -> Bestätigung/Ausführung
    # libmaint:meta:title:<idx>                  -> Track-Picker
    # libmaint:meta:title:pick:<idx>:<track_idx> -> Track wählen, Freitext
    #                                               starten
    # libmaint:meta:title:confirm/execute        -> Bestätigung/Ausführung

    if len(parts) >= 3 and parts[1] == "meta":
        if len(parts) == 3:
            try:
                idx = int(parts[2])
            except ValueError:
                await query.answer("⚠️ Ungültiger Callback", show_alert=True)
                return
            await maintenance_handler.handle_meta_menu(update, context, idx)
            return

        if len(parts) == 4 and parts[2] == "artist":
            sub = parts[3]
            if sub == "confirm":
                await maintenance_handler.handle_meta_artist_confirm(update, context)
                return
            if sub == "execute":
                await maintenance_handler.handle_meta_artist_execute(update, context)
                return
            try:
                idx = int(sub)
            except ValueError:
                await query.answer("⚠️ Ungültiger Callback", show_alert=True)
                return
            await maintenance_handler.handle_meta_artist_start(update, context, idx)
            return

        if len(parts) == 4 and parts[2] == "title":
            sub = parts[3]
            if sub == "confirm":
                await maintenance_handler.handle_meta_title_confirm(update, context)
                return
            if sub == "execute":
                await maintenance_handler.handle_meta_title_execute(update, context)
                return
            try:
                idx = int(sub)
            except ValueError:
                await query.answer("⚠️ Ungültiger Callback", show_alert=True)
                return
            await maintenance_handler.handle_meta_title_start(update, context, idx)
            return

        if len(parts) == 6 and parts[2] == "title" and parts[3] == "pick":
            try:
                idx, track_idx = int(parts[4]), int(parts[5])
            except ValueError:
                await query.answer("⚠️ Ungültiger Callback", show_alert=True)
                return
            await maintenance_handler.handle_meta_title_pick(update, context, idx, track_idx)
            return

        await query.answer("⚠️ Unbekannter Metadaten-Callback")
        return

    await query.answer("⚠️ Unbekannter Library-Wartung-Callback")


# ====== L2/L3 PRO-ARTIST-REPARATUR (ARCH-033) ======


async def handle_l23rep_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    repair_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle l23rep:* Callbacks.

    Routing (siehe handlers/repair_musicbot_handler.py, ARCH-033):
      l23rep:start                → Einstieg (aus "Reparaturvorschläge")
      l23rep:artists               → Artist-Liste, Seite 0, frischer Scan
      l23rep:artists:<page>        → Artist-Liste, Seite <page> (gecacht)
      l23rep:pick:<idx>            → Aktions-Auswahl (L2/L3) für Artist
      l23rep:preview:<l2|l3>:<idx> → Preview (read-only)
      l23rep:confirm:<l2|l3>:<idx> → explizite Bestätigung
      l23rep:execute:<l2|l3>:<idx> → tatsächliche Ausführung

    Lebt bewusst auf demselben RepairMusicBotHandler wie repair:* (kein
    neuer Handler) - L2/L3 sind Findings-getrieben wie SAFE_AUTOMATIC
    (ADR-0001), nur mit Pro-Artist-Bestätigung (ADR-0003). Eigener
    Admin-Check hier (Defense-in-Depth, analog zu repair:/libmaint:/
    doctor:/review: - callback_data ist frei sendbar, siehe SEC-003).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if not is_admin_check(user_id):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
            f"L2/L3-Repair-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not repair_handler:
        await query.answer("⚠️ Repair-Handler nicht verfügbar", show_alert=True)
        return

    if callback_data == "l23rep:start":
        await repair_handler.handle_l23_start(update, context)
        return
    if callback_data == "l23rep:artists":
        await repair_handler.handle_l23_artist_list(update, context, 0, force_refresh=True)
        return

    parts = callback_data.split(":")

    if len(parts) == 3 and parts[1] == "artists":
        try:
            page = int(parts[2])
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await repair_handler.handle_l23_artist_list(update, context, page)
        return

    if len(parts) == 3 and parts[1] == "pick":
        try:
            idx = int(parts[2])
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await repair_handler.handle_l23_pick_artist(update, context, idx)
        return

    if len(parts) == 4 and parts[1] in ("preview", "confirm", "execute"):
        level, idx_str = parts[2], parts[3]
        if level not in ("l2", "l3"):
            await query.answer("⚠️ Ungültiges Level", show_alert=True)
            return
        try:
            idx = int(idx_str)
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        if parts[1] == "preview":
            await repair_handler.handle_l23_preview(update, context, level, idx)
        elif parts[1] == "confirm":
            await repair_handler.handle_l23_confirm_prompt(update, context, level, idx)
        else:
            await repair_handler.handle_l23_execute(update, context, level, idx)
        return

    await query.answer("⚠️ Unbekannter L2/L3-Repair-Callback")


# ====== DUPLIKAT-CHECK (Chat-Charakterisierung 2026-09-15) ======


async def handle_duplicate_check_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, duplicate_check_handler
) -> None:
    """Einstiegspunkt aus dem Menü-System - Wrapper analog zu
    handle_repair_start()."""
    if duplicate_check_handler:
        await duplicate_check_handler.handle_start(update, context)
    else:
        await show_handler_not_available(update, "Duplikat-Check-Handler")


async def handle_duplicate_check_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    duplicate_check_handler,
    is_admin_check,
    logger,
) -> None:
    """
    Dispatcher für alle dupcheck:* Callbacks.

    Routing (siehe handlers/duplicate_check_handler.py):
      dupcheck:start        → Startseite
      dupcheck:artists       → Artist-Liste (Index-Picker)
      dupcheck:pick:<idx>    → Scan für diesen Artist starten (read-only)

    Eigener Admin-Check hier (Defense-in-Depth, analog zu repair:/
    libmaint:/doctor:/review: - callback_data ist frei sendbar, siehe
    SEC-003).
    """
    query = update.callback_query
    user_id = update.effective_user.id

    if not is_admin_check(user_id):
        logger.warning(
            f"🚨 [SECURITY] Nicht-Admin {user_id} versuchte "
            f"Duplikat-Check-Callback: {callback_data}"
        )
        await query.answer("⛔ Keine Berechtigung", show_alert=True)
        return

    if not duplicate_check_handler:
        await query.answer("⚠️ Duplikat-Check-Handler nicht verfügbar", show_alert=True)
        return

    if callback_data == "dupcheck:start":
        await duplicate_check_handler.handle_start(update, context)
        return
    if callback_data == "dupcheck:artists":
        await duplicate_check_handler.handle_artist_list(update, context)
        return

    parts = callback_data.split(":")
    if len(parts) == 3 and parts[1] == "pick":
        try:
            idx = int(parts[2])
        except ValueError:
            await query.answer("⚠️ Ungültiger Callback", show_alert=True)
            return
        await duplicate_check_handler.handle_pick_artist(update, context, idx)
        return

    await query.answer("⚠️ Unbekannter Duplikat-Check-Callback")
