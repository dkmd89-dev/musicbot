# handlers/menu/actions/stats.py
# -*- coding: utf-8 -*-
"""
Statistik-Actions (persönliche Statistiken).

ARCH-024/P-2 (Actions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py und handlers/menu/rich_menu_handler.py
verschoben (reine Move-Operation).

Wichtiger Bestandsbefund (siehe
docs/MusicBot_ARCH-024_Menu_File_Decomposition.md Abschnitt 1.6): die
"_system_*"-Funktionen unten (aus RichMenuSystem) sind im
Produktivbetrieb NICHT erreichbar, da
RichMenuHandler._register_stats_handlers() ihre MenuItem-Bindung nach
initialize_menu_structure() per register_handler() überschreibt -
außer stats_library_overview, das nicht überschrieben wird. Diese
"toten" Funktionen werden trotzdem 1:1 mitverschoben (Verhaltensparität,
kein ARCH-024-Scope, sie zu entfernen).
"""

from telegram import Update
from telegram.ext import ContextTypes


# ====== aus RichMenuSystem (Menu-Definition, teils tot - s. Docstring) ======


async def handle_stats_monthly_system(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler):
    query = update.callback_query
    await query.answer()
    if stats_handler:
        await stats_handler.handle_month_review(update, context)
    else:
        await query.edit_message_text("📅 Lade Monatsstatistiken...")


async def handle_stats_yearly_system(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler):
    query = update.callback_query
    await query.answer()
    if stats_handler:
        await stats_handler.handle_year_review(update, context)
    else:
        await query.edit_message_text("🎆 Lade Jahresstatistiken...")


async def handle_stats_top_songs_system(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler):
    query = update.callback_query
    await query.answer()
    if stats_handler:
        await stats_handler.handle_top_songs(update, context, period="month")
    else:
        await query.edit_message_text("🎵 Lade Top Songs...")


async def handle_stats_library_overview(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler):
    """Phase 3, P1.1 — Library-Zusammensetzung aus dem Health-Report,
    anders als die übrigen stats_*-Handler keine Play-History. Einzige
    Stats-Menu-Definition, die NICHT von RichMenuHandler überschrieben
    wird - im Produktivbetrieb live."""
    query = update.callback_query
    await query.answer()
    if stats_handler:
        await stats_handler.handle_library_overview(update, context)
    else:
        await query.edit_message_text("📚 Lade Library-Übersicht...")


async def handle_stats_top_artists_system(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler):
    query = update.callback_query
    await query.answer()
    if stats_handler:
        await stats_handler.handle_top_artists(update, context, period="month")
    else:
        await query.edit_message_text("🎤 Lade Top Künstler...")


async def handle_stats_timeline_system(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler):
    query = update.callback_query
    await query.answer()
    if stats_handler and hasattr(stats_handler, "handle_music_timeline"):
        await stats_handler.handle_music_timeline(update, context)
    else:
        await query.edit_message_text("📅 Lade Music Timeline...")


# ====== aus RichMenuHandler (per register_handler live gebunden) ======


async def handle_monthly_stats_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler, logger):
    query = update.callback_query
    await query.answer()
    try:
        if stats_handler and hasattr(stats_handler, "handle_month_review"):
            await stats_handler.handle_month_review(update, context)
        else:
            await query.edit_message_text(
                "📅 **Monatsrückblick**\n\nDiese Funktion wird gerade entwickelt... 🚀"
            )
    except Exception as e:
        logger.error(f"❌ Fehler bei Monatsstatistik: {e}")
        await query.edit_message_text("❌ Fehler beim Laden der Statistiken")


async def handle_yearly_stats_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler, logger):
    query = update.callback_query
    await query.answer()
    try:
        if stats_handler and hasattr(stats_handler, "handle_year_review"):
            await stats_handler.handle_year_review(update, context)
        else:
            await query.edit_message_text(
                "🎆 **Jahresrückblick**\n\nDiese Funktion wird gerade entwickelt... 🚀"
            )
    except Exception as e:
        logger.error(f"❌ Fehler bei Jahresstatistik: {e}")
        await query.edit_message_text("❌ Fehler beim Laden der Statistiken")


async def handle_top_songs_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler, logger):
    query = update.callback_query
    await query.answer(f"Lade Top Songs ...")
    try:
        if stats_handler and hasattr(stats_handler, "handle_top_songs"):
            await stats_handler.handle_top_songs(update, context, period="month")
        else:
            await query.edit_message_text(
                "🎵 **Top Songs**\n\nStatistik-Handler nicht gefunden."
            )
    except Exception as e:
        logger.error(f"❌ Fehler bei Top Songs Statistik: {e}")
        await query.edit_message_text("❌ Fehler beim Laden der Statistiken")


async def handle_top_artists_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler, logger):
    query = update.callback_query
    await query.answer("Lade Top Künstler ...")
    try:
        if stats_handler and hasattr(stats_handler, "handle_top_artists"):
            await stats_handler.handle_top_artists(update, context, period="month")
        else:
            await query.edit_message_text(
                "🎤 **Top Künstler**\n\nStatistik-Handler nicht gefunden."
            )
    except Exception as e:
        logger.error(f"❌ Fehler bei Top Künstler Statistik: {e}")
        await query.edit_message_text("❌ Fehler beim Laden der Statistiken")


async def handle_timeline_stats_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, stats_handler, logger):
    query = update.callback_query
    await query.answer("Lade Music Timeline ...")
    try:
        if stats_handler and hasattr(stats_handler, "handle_music_timeline"):
            await stats_handler.handle_music_timeline(update, context)
        else:
            await query.edit_message_text(
                "📅 **Music Timeline**\n\nStatistik-Handler nicht gefunden."
            )
    except Exception as e:
        logger.error(f"❌ Fehler bei Music Timeline: {e}")
        await query.edit_message_text("❌ Fehler beim Laden der Statistiken")
