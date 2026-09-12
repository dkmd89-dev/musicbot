# handlers/menu/actions/family.py
# -*- coding: utf-8 -*-
"""
Family-Hub-Actions (Familien-Statistik/-Chat/-Challenge, Phasen F2-F4).

ARCH-024/P-2 (Actions Extraction): 1:1 aus handlers/menu/rich_menu_system.py
verschoben (reine Move-Operation, keine Verhaltensänderung). Die
Zugriffsprüfung (Family-Membership) erfolgt weiterhin in den jeweiligen
Handlern selbst (FamilyStatsHandler/FamilyChatHandler/
FamilyChallengeHandler), nicht hier - dieselbe Aufgabenteilung wie vorher.

Abhängigkeiten werden bei jedem Aufruf explizit übergeben (kein
Konstruktor-State) - die Handler-Referenzen in RichMenuSystem sind erst
nach initialize_menu_structure() gesetzt (Lazy-Binding, siehe
docs/MusicBot_ARCH-024_Menu_File_Decomposition.md Abschnitt 1.6/1.7) und
können sich zur Laufzeit ändern (Tests weisen sie teils direkt zu).
"""

from telegram import Update
from telegram.ext import ContextTypes


async def handle_family_stats_top_songs(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_stats_handler
):
    query = update.callback_query
    await query.answer()
    if family_stats_handler:
        await family_stats_handler.handle_family_top_songs(update, context)
    else:
        await query.edit_message_text("🎵 Lade Top Songs Familie...")


async def handle_family_stats_top_artists(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_stats_handler
):
    query = update.callback_query
    await query.answer()
    if family_stats_handler:
        await family_stats_handler.handle_family_top_artists(update, context)
    else:
        await query.edit_message_text("🎤 Lade Top Künstler Familie...")


async def handle_family_stats_member(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_stats_handler
):
    query = update.callback_query
    await query.answer()
    if family_stats_handler:
        await family_stats_handler.handle_family_member_stats(update, context)
    else:
        await query.edit_message_text("👥 Lade Statistik pro Person...")


async def handle_family_stats_champion(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_stats_handler
):
    query = update.callback_query
    await query.answer()
    if family_stats_handler:
        await family_stats_handler.handle_family_champion(update, context)
    else:
        await query.edit_message_text("🏆 Ermittle Musik-Champion...")


async def handle_family_stats_listening_times(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_stats_handler
):
    query = update.callback_query
    await query.answer()
    if family_stats_handler:
        await family_stats_handler.handle_family_listening_times(update, context)
    else:
        await query.edit_message_text("⏰ Lade Hörzeiten...")


async def handle_family_stats_monthly_trend(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_stats_handler
):
    query = update.callback_query
    await query.answer()
    if family_stats_handler:
        await family_stats_handler.handle_family_monthly_trend(update, context)
    else:
        await query.edit_message_text("📈 Lade Monatsentwicklung...")


async def handle_family_chat_send(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_chat_handler
):
    query = update.callback_query
    await query.answer()
    if family_chat_handler:
        await family_chat_handler.handle_send_message_prompt(update, context)
    else:
        await query.edit_message_text("📝 Familien-Chat nicht verfügbar...")


async def handle_family_chat_recent(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_chat_handler
):
    query = update.callback_query
    await query.answer()
    if family_chat_handler:
        await family_chat_handler.handle_recent_messages(update, context)
    else:
        await query.edit_message_text("📋 Familien-Chat nicht verfügbar...")


async def handle_family_chat_notifications(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_chat_handler
):
    query = update.callback_query
    await query.answer()
    if family_chat_handler:
        await family_chat_handler.handle_toggle_notifications(update, context)
    else:
        await query.edit_message_text("🔔 Familien-Chat nicht verfügbar...")


async def handle_family_challenge_today(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_challenge_handler
):
    query = update.callback_query
    await query.answer()
    if family_challenge_handler:
        await family_challenge_handler.handle_todays_challenge(update, context)
    else:
        await query.edit_message_text("❓ Familien-Challenge nicht verfügbar...")


async def handle_family_challenge_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_challenge_handler
):
    query = update.callback_query
    await query.answer()
    if family_challenge_handler:
        await family_challenge_handler.handle_answer_prompt(update, context)
    else:
        await query.edit_message_text("✅ Familien-Challenge nicht verfügbar...")


async def handle_family_challenge_leaderboard(
    update: Update, context: ContextTypes.DEFAULT_TYPE, family_challenge_handler
):
    query = update.callback_query
    await query.answer()
    if family_challenge_handler:
        await family_challenge_handler.handle_leaderboard(update, context)
    else:
        await query.edit_message_text("🏆 Familien-Challenge nicht verfügbar...")
