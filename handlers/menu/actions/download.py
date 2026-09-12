# handlers/menu/actions/download.py
# -*- coding: utf-8 -*-
"""
Download-Actions: Download-Control-Center (RichMenuSystem) + die
Download-Pipeline-Einstiegspunkte (RichMenuHandler).

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py und handlers/menu/rich_menu_handler.py
verschoben (reine Move-Operation). Einzige Domäne, die beide Dateien
gleichzeitig betrifft (siehe
docs/MusicBot_ARCH-024_Menu_File_Decomposition.md Abschnitt 1.8,
"RISKY"). `user_states` (RichMenuHandler) bleibt bewusst ein von
RichMenuHandler gehaltenes, mutable Dict - wird als Referenz
durchgereicht statt kopiert, damit handle_url_message() (liest) und die
beiden Download-Wrapper (schreiben) weiterhin denselben, geteilten
Zustand sehen wie vorher.
"""

import asyncio
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from klassen.download_handler import DownloadHandler


def _dl_progress_bar(current: int, total: int, width: int = 10) -> str:
    """Track-Fortschrittsbalken für "🔄 Aktive Downloads" (Download-
    Control-Center 2026-09-02) - eigener, kleiner Helfer für die
    Track-Anzahl innerhalb EINES Downloads, nicht zu verwechseln mit dem
    6-Schritte-Pipelinebalken in klassen/download_handler.py."""
    filled = round(width * current / max(total, 1))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {current}/{total}"


class _RetryMessageAdapter:
    """Duck-Typing-Stellvertreter für update.message, beschränkt auf genau
    die zwei Attribute, die klassen/download_handler.py entlang des
    handle_url()/handle_youtube_links()-Pfads tatsächlich liest (verifiziert
    per grep: nur .text und .reply_text(...))."""

    def __init__(self, text: str, reply_text):
        self.text = text
        self.reply_text = reply_text


class _RetryUpdateAdapter:
    """Duck-Typing-Stellvertreter für ein Update-Objekt, siehe
    handle_download_retry()-Docstring für die Begründung (PTB-Update-/
    Message-Objekte sind eingefroren, dürfen nicht mutiert werden).
    effective_user/effective_chat/update_id werden 1:1 vom echten,
    auslösenden Callback-Query-Update übernommen (die sind bereits real und
    gültig) - nur .message wird durch einen Stellvertreter mit der
    gespeicherten Verlaufs-URL ersetzt, .reply_text sendet über die echte
    Bot-Message des Callback-Queries (callback_query.message.reply_text)."""

    def __init__(self, source_update: Update, url: str):
        self.effective_user = source_update.effective_user
        self.effective_chat = source_update.effective_chat
        self.update_id = source_update.update_id
        self.message = _RetryMessageAdapter(
            text=url,
            reply_text=source_update.callback_query.message.reply_text,
        )


# ====== DOWNLOAD-CONTROL-CENTER (RichMenuSystem, 2026-09-02) ======
#
# "📥 Downloads" wird zu einem echten Steuerzentrum statt der
# bisherigen statischen 2-Optionen-Liste (Einzelner Track/Playlist -
# ohnehin redundant, da download_utils.py Single/Playlist automatisch
# anhand der URL erkennt, siehe handle_download_new()). "❌
# Abbrechen" erscheint NUR, wenn tatsächlich ein Download für diesen
# Chat aktiv ist (active_downloads, siehe
# services/downloader/active_downloads.py) - "keine toten Buttons".


async def handle_download_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, active_downloads
) -> None:
    """Wird über den regulären menu:download-Callback aufgerufen
    (query.answer() bereits vom generischen Dispatcher erledigt, siehe
    RichMenuSystem.handle_callback())."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    active = active_downloads.get(chat_id) if active_downloads else None
    await render_download_menu(query, active)


async def render_download_menu(query, active) -> None:
    # Live-Fund 2026-09-02: active.title/tracker-Inhalte stammen aus
    # echten YouTube-Titeln/Artist-/Albumnamen - koennen "_"/"*"
    # enthalten, die Telegrams (Legacy-)Markdown-Parser als
    # unvollstaendige Formatierung interpretiert
    # ("Can't parse entities: can't find end of the entity", live
    # reproduziert für eine URL mit "_"). Bewusst KEIN parse_mode in
    # dieser gesamten dl:-Sektion, sobald dynamische/externe Inhalte
    # vorkommen koennen - robuster als selektives Escapen einzelner
    # Felder (das genau diesen Fund erst verursacht hat).
    lines = ["📥 Downloads", ""]
    if active is not None:
        lines.append(f"🔄 Läuft gerade: {active.title or 'wird vorbereitet …'}")
    else:
        lines.append("Lade Musik von YouTube herunter oder verwalte Downloads.")

    keyboard = [
        [InlineKeyboardButton("➕ Neuer Download", callback_data="dl:new")],
        [InlineKeyboardButton("🔄 Aktive Downloads", callback_data="dl:active")],
        [InlineKeyboardButton("📋 Download-Verlauf", callback_data="dl:history")],
    ]
    if active is not None:
        keyboard.append(
            [InlineKeyboardButton("❌ Abbrechen", callback_data="dl:cancel")]
        )
    keyboard.append(
        [InlineKeyboardButton("◀️ Hauptmenü", callback_data="menu:main")]
    )

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_download_control_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str,
    active_downloads,
    download_history,
    retry_url_callback,
    logger,
) -> None:
    """Spezial-Handler für alle dl:*-Callbacks (Download-Control-Center),
    analog zu handle_backup_callback() etc."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    if callback_data == "dl:new":
        await handle_download_new(query)
        return
    if callback_data == "dl:active":
        await handle_download_active(query, chat_id, active_downloads)
        return
    if callback_data == "dl:cancel":
        await handle_download_cancel_request(query, chat_id, active_downloads, logger)
        return
    if callback_data == "dl:details":
        await handle_download_details(query, chat_id, active_downloads)
        return
    if callback_data == "dl:history":
        await handle_download_history(query, chat_id, download_history)
        return
    if callback_data.startswith("dl:retry:"):
        await handle_download_retry(
            update, context, query, chat_id, callback_data, download_history, retry_url_callback
        )
        return
    if callback_data == "dl:menu":
        active = active_downloads.get(chat_id) if active_downloads else None
        await render_download_menu(query, active)
        return

    logger.warning(f"⚠️ Unbekannter dl:-Callback: {callback_data}")
    await query.edit_message_text("⚠️ Unbekannte Aktion.")


async def handle_download_new(query) -> None:
    await query.edit_message_text(
        "🎵 Neuer Download\n\n"
        "Sende mir einfach einen YouTube-Link (Song oder Playlist) - "
        "ich erkenne automatisch, um welchen Typ es sich handelt."
    )


async def handle_download_active(query, chat_id: int, active_downloads) -> None:
    """
    "📥 Download läuft" (Nutzer-Vorgabe, P1): zeigt aktuellen Track,
    bereits abgeschlossene Tracks und die verbleibende Anzahl anhand
    des GETEILTEN ProgressTrackers (ActiveDownload.tracker) - derselbe
    Zustand, den auch die automatischen Zwischen-Updates während des
    Downloads nutzen (klassen/download_handler.py::
    _on_playlist_progress()) - hier nur zusätzlich manuell abrufbar,
    statt nur passiv gepusht.
    """
    active = active_downloads.get(chat_id) if active_downloads else None
    if active is None:
        await query.edit_message_text(
            "🔄 Aktive Downloads\n\nAktuell läuft kein Download.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")]]
            ),
        )
        return

    tracker = active.tracker
    bar = _dl_progress_bar(tracker.processed_items, tracker.total_items)
    remaining = max(tracker.total_items - tracker.processed_items, 0)

    # Live-Fund 2026-09-02: siehe render_download_menu() - kein
    # parse_mode, tracker.current_item/completed_items sind echte
    # YouTube-Tracktitel (koennen "_"/"*" enthalten).
    lines = [
        "📥 Download läuft",
        "",
        f"🎵 {active.title or 'wird vorbereitet …'}",
        "",
        bar,
    ]
    if tracker.current_item:
        lines += ["", "⬇️ Aktuell", tracker.current_item]
    if tracker.completed_items:
        lines += ["", "✅ Abgeschlossen"] + tracker.completed_items[-5:]
    if remaining > 0:
        lines += ["", f"⏳ Noch {remaining} Tracks"]

    keyboard = [
        [InlineKeyboardButton("❌ Download abbrechen", callback_data="dl:cancel")],
        [InlineKeyboardButton("ℹ️ Details", callback_data="dl:details")],
        [InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_download_cancel_request(query, chat_id: int, active_downloads, logger) -> None:
    active = active_downloads.get(chat_id) if active_downloads else None
    if active is None:
        await query.edit_message_text(
            "ℹ️ Kein aktiver Download zum Abbrechen.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")]]
            ),
        )
        return

    active.request_cancel()
    logger.info(f"🛑 [DL-CONTROL] Abbruch angefordert für Chat {chat_id}")
    await query.edit_message_text(
        "🛑 Abbruch angefordert - der Download wird in Kürze gestoppt.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")]]
        ),
    )


async def handle_download_details(query, chat_id: int, active_downloads) -> None:
    active = active_downloads.get(chat_id) if active_downloads else None
    if active is None:
        await query.edit_message_text(
            "ℹ️ Kein aktiver Download.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:active")]]
            ),
        )
        return

    tracker = active.tracker
    elapsed = int(active.elapsed_seconds())
    minutes, seconds = divmod(elapsed, 60)

    # Live-Fund 2026-09-02: siehe render_download_menu() - kein
    # parse_mode. Genau active.url hat den urspruenglichen Fehler
    # ausgeloest ("Can't parse entities", "_" in der YouTube-URL von
    # Telegrams Legacy-Markdown-Parser als unvollstaendige Kursiv-
    # Formatierung interpretiert).
    lines = [
        "ℹ️ Download-Details",
        "",
        f"🎵 Titel      : {active.title or '?'}",
        f"🔗 URL        : {active.url}",
        f"📦 Typ        : {active.download_type}",
        f"⏱️ Laufzeit   : {minutes}:{seconds:02d} min",
        f"📊 Fortschritt: {tracker.processed_items}/{tracker.total_items}",
    ]
    if tracker.current_item:
        lines.append(f"⬇️ Aktuell    : {tracker.current_item}")

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:active")]]
        ),
    )


_HISTORY_STATUS_ICONS = {"success": "✅", "failed": "❌", "cancelled": "🛑"}


async def handle_download_history(query, chat_id: int, download_history) -> None:
    """
    Download-Verlauf (Nutzer-Priorität 3) + "🔁 Erneut versuchen"
    (Priorität 4) - Folgeschritt des Download-Control-Centers, siehe
    docs/FINDINGS_INDEX.md ("Download-Verlauf/Erneut-versuchen").
    Zeigt die letzten Einträge des Chats aus dem geteilten
    DownloadHistoryStore (services/downloader/download_history.py),
    neueste zuerst - jeweils mit einem eigenen "🔁"-Button
    (callback_data=f"dl:retry:{position}", position bezieht sich auf
    DownloadHistoryStore.get_recent()/get_entry_by_position(), damit
    Index und Anzeige immer übereinstimmen).
    """
    entries = download_history.get_recent(chat_id) if download_history else []
    if not entries:
        await query.edit_message_text(
            "📋 Download-Verlauf\n\nNoch keine Downloads in dieser Chat-Historie.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")]]
            ),
        )
        return

    lines = ["📋 Download-Verlauf", ""]
    keyboard = []
    for position, entry in enumerate(entries):
        icon = _HISTORY_STATUS_ICONS.get(entry.status, "•")
        # Nur Datum/Uhrzeit, kein Sekunden-Praezisions-Rauschen - die
        # Reihenfolge (neueste zuerst) macht die genaue Sekunde ohnehin
        # nicht aussagekraeftig.
        try:
            when = datetime.fromisoformat(entry.timestamp).strftime("%d.%m. %H:%M")
        except ValueError:
            when = "?"
        lines.append(f"{icon} {entry.artist} - {entry.title}  ({when})")
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔁 {entry.title[:40]}",
                    callback_data=f"dl:retry:{position}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("◀️ Zurück", callback_data="dl:menu")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_download_retry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query,
    chat_id: int,
    callback_data: str,
    download_history,
    retry_url_callback,
) -> None:
    """Handler für "🔁 Erneut versuchen" (callback_data=f"dl:retry:{position}").

    RichMenuSystem kann selbst keinen DownloadHandler bauen (siehe
    __init__-Kommentar zu _retry_url_callback in rich_menu_system.py) -
    baut stattdessen ein minimales, schreibgeschütztes Duck-Typing-Objekt
    anstelle von update.message (PTB-Update-/Message-Objekte sind nach
    Auslieferung eingefroren, ein echtes Update darf nicht nachtraeglich
    mutiert werden) und reicht es an genau denselben, bereits produktiv
    genutzten Pfad weiter (process_url() -> handler.handle_url() ->
    handle_youtube_links()) wie ein normaler Text-Download - keine
    Parallel-Implementierung der Download-Pipeline."""
    try:
        position = int(callback_data.split(":", 2)[2])
    except (IndexError, ValueError):
        await query.edit_message_text("⚠️ Ungültiger Verlaufseintrag.")
        return

    if not download_history:
        await query.edit_message_text("⚠️ Download-Verlauf nicht verfügbar.")
        return
    entry = download_history.get_entry_by_position(chat_id, position)
    if entry is None or not entry.url:
        await query.edit_message_text("⚠️ Dieser Eintrag ist nicht mehr verfügbar.")
        return
    if not retry_url_callback:
        await query.edit_message_text("⚠️ Erneuter Download aktuell nicht möglich.")
        return

    await query.edit_message_text(f"🔁 Starte erneuten Download:\n{entry.title}")
    retry_update = _RetryUpdateAdapter(update, entry.url)
    await retry_url_callback(retry_update, context, entry.url)


# ====== PLATZHALTER-HANDLER (RichMenuSystem) ======


async def handle_download_single_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎵 Einzelner Track - Sende mir einen YouTube-Link!")


async def handle_download_playlist_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📋 Playlist - Sende mir einen Playlist-Link!")


# ====== DOWNLOAD-WRAPPER + PIPELINE (RichMenuHandler) ======


async def handle_download_single_wrapper(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_states: dict, logger
) -> None:
    """Wrapper für Single-Download (YouTube)."""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    await query.edit_message_text(
        "🎵 **Einzelner Track Download**\n\n"
        "Sende mir einen YouTube-Link.\n\n"
        "YouTube-Beispiel:\n"
        "`https://youtube.com/watch?v=...`"
    )
    user_states[user_id] = "awaiting_single_url"
    logger.info(f"📝 User {user_id} wartet auf Single-URL")


async def handle_download_playlist_wrapper(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_states: dict, logger
) -> None:
    """Wrapper für Playlist-Download (YouTube)."""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    await query.edit_message_text(
        "📋 **Playlist Download**\n\n"
        "Sende mir einen YouTube-Playlist-Link."
    )
    user_states[user_id] = "awaiting_playlist_url"
    logger.info(f"📝 User {user_id} wartet auf Playlist-URL")


def create_download_handler(update: Update, config, duplicate_detector, metadata_processor, logger_factory, active_downloads, download_history, logger):
    """
    Erstellt eine neue DownloadHandler-Instanz mit allen injizierten
    Abhängigkeiten.

    Der MetadataProcessor und DuplicateHandler werden geteilt.

    Args:
        update: Telegram-Update-Objekt

    Returns:
        Fertig konfigurierter DownloadHandler oder None bei fehlenden
        Abhängigkeiten.
    """
    if not duplicate_detector:
        logger.error("❌ DuplicateDetector nicht initialisiert – Download nicht möglich.")
        return None
    if not metadata_processor:
        logger.error("❌ MetadataProcessor nicht initialisiert – Download nicht möglich.")
        return None

    return DownloadHandler(
        update=update,
        config=config,
        duplicate_detector=duplicate_detector,
        metadata_processor=metadata_processor,
        logger_factory=logger_factory,
        active_downloads=active_downloads,
        download_history=download_history,
    )


def _log_background_download_task_exception(task: "asyncio.Task", logger) -> None:
    """add_done_callback()-Sicherheitsnetz für process_url()'s
    Hintergrund-Download-Task - siehe dortigen Docstring."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(
            f"💥 Unerwarteter Fehler im Hintergrund-Download-Task: {exc}",
            exc_info=exc,
        )


async def process_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    create_handler_callback,
    logger,
) -> None:
    """
    Erstellt einen DownloadHandler und startet den Download-Prozess.

    create_handler_callback wird als Callable (nicht als Rohabhängigkeiten)
    entgegengenommen, damit RichMenuHandler._process_url() weiterhin
    self._create_download_handler(update) aufruft - genau die
    Aufrufsignatur, die bestehende Tests per
    patch.object(handler, "_create_download_handler", ...) ersetzen
    (siehe tests/test_rich_menu_handler.py). Eine hier fest verdrahtete
    Konstruktion hätte diese Testbarkeit gebrochen.

    Live-Fund 2026-09-02 (Nutzer-Report: "sobald Download läuft öffnet
    sich das Menü nicht"): die Telegram-`Application` läuft ohne
    `concurrent_updates=True` (siehe bot.py) - PTB holt das NÄCHSTE
    Update aus der Warteschlange erst, NACHDEM der Handler für das
    aktuelle Update komplett zurückgekehrt ist. Ein direktes
    `await handler.handle_url(...)` hier blockierte dadurch die
    Verarbeitung JEDES weiteren Updates (inkl. Menü-Klicks wie "🔄
    Aktive Downloads"/"❌ Abbrechen") für die GESAMTE Downloaddauer -
    bestätigt über einen live beobachteten "Query is too old"-
    BadRequest für einen während eines laufenden Downloads geklickten
    Button, der erst NACH Downloadende (und damit zu spät für
    Telegrams Callback-Query-Gültigkeitsfenster) verarbeitet wurde.

    Fix: der eigentliche Download läuft als eigenständiger
    Hintergrund-Task (asyncio.create_task) - process_url() selbst
    kehrt sofort zurück, PTB kann direkt das nächste Update
    verarbeiten. Bewusst NICHT die globale `concurrent_updates`-
    Einstellung geändert (deutlich größerer Blast-Radius: beträfe
    ALLE Handler, nicht nur Downloads) - dieser gezielte Task deckt
    genau den gemeldeten Fall ab.

    handle_youtube_links() (aufgerufen über handler.handle_url())
    fängt eigene Fehler bereits breit ab und meldet sie dem Nutzer
    per Telegram - der add_done_callback()-Handler unten ist nur ein
    Sicherheitsnetz für wirklich unerwartete, durchrutschende
    Ausnahmen (verhindert eine stumme "Task exception was never
    retrieved"-Warnung ohne jedes Logging).
    """
    logger.info(
        f"🔗 Verarbeite 📺 YouTube-URL von User {update.effective_user.id}: {url}"
    )

    handler = create_handler_callback(update)
    if not handler:
        await update.message.reply_text(
            "❌ Download-Dienst nicht verfügbar. Bitte versuche es später erneut."
        )
        return

    task = asyncio.create_task(handler.handle_url(update, context))
    task.add_done_callback(lambda t: _log_background_download_task_exception(t, logger))


async def handle_url_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_states: dict,
    process_url_callback,
) -> None:
    """
    Verarbeitet URL-Nachrichten basierend auf dem User-State.

    Die URL-Validierung erfolgt in DownloadHandler.handle_url().
    process_url_callback kapselt die konkrete process_url()-Aufrufsignatur
    (config/duplicate_detector/... sind zum Zeitpunkt der Telegram-
    Handler-Registrierung bereits fest über RichMenuHandler._process_url
    gebunden, siehe dortigen Delegator).
    """
    user_id = update.effective_user.id
    text = update.message.text
    state = user_states.get(user_id)

    if not state:
        # Keine aktive Menü-Auswahl – URL direkt verarbeiten
        await process_url_callback(update, context, text)
        return

    if state in ["awaiting_single_url", "awaiting_playlist_url"]:
        await process_url_callback(update, context, text)
        # State nach Verarbeitung aufräumen
        if user_id in user_states:
            del user_states[user_id]
