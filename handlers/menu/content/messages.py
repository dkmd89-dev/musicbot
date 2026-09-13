# handlers/menu/content/messages.py
# -*- coding: utf-8 -*-
"""
Statischer User-Facing UI-Content für die Onboarding-Oberfläche
(/start, /help, Help-Callback): Begrüßungs-/Hilfetexte und
Button-Labels.

ARCH-025 (Content Separation Closure): 1:1 aus
handlers/menu/content/greeting.py und handlers/menu/content/help.py
verschoben (reine Move-Operation, keine Textänderung - gleiche
Formulierungen/Emojis/Markdown/Reihenfolge). Zentralisiert nach dem
Prinzip "Centralized Static Content in einem Python-Modul" - bewusst
KEIN JSON/YAML/i18n/CMS, siehe
docs/MusicBot_ARCH-025_Menu_Command_Help_Content_Closure.md.

Dieses Modul hat bewusst KEINE Abhängigkeit auf RichMenuHandler,
RichMenuSystem, actions/ oder sonstige Projektlogik - nur reine
String-Konstanten. Dynamische Werte (Feature-Listen, User-Rollen,
Timestamps) werden weiterhin in greeting.py/help.py zur Aufrufzeit via
.format()/f-string in die hier definierten Templates eingesetzt.

Zentralisiert wurden Button-Labels, die mehrfach verwendet werden
(🏠 Hauptmenü ×4, ❌ Schließen ×3, 📥/📊/🎵/⚙️ ×2) - einmalig verwendete
Labels (z. B. "⬅️ Zurück zur Hilfe", "❓ Hilfe") bleiben bewusst lokal
in greeting.py/help.py (keine erzwungene Zentralisierung ohne
Duplizierung, siehe Master-Prompt Abschnitt 10).
"""

# ====== GREETING (/start) ======

GREETING_WELCOME_NEW = "👋 **Willkommen, {username}!**\n"
GREETING_WELCOME_NEW_LINE_2 = "🎉 Schön, dass du hier bist!"
GREETING_WELCOME_NEW_LINE_3 = "Lass mich dir zeigen, was ich kann...\n"

GREETING_WELCOME_BACK = "👋 **Hallo zurück, {username}!**\n"
GREETING_WELCOME_BACK_LINE_2 = "Schön, dich wiederzusehen!\n"

GREETING_ROLE_LINE = "\n{role_emoji} Deine Rolle: **{role_title}**\n"

GREETING_FEATURES_HEADER = "\n📚 **Verfügbare Funktionen:**\n"

GREETING_QUICKSTART_HEADER = "\n💡 **Schnellstart:**"
GREETING_QUICKSTART_MENU = "• Nutze /menu für das Hauptmenü"
GREETING_QUICKSTART_HELP = "• Nutze /help für detaillierte Hilfe"
GREETING_HINT_DOWNLOAD = "• Sende mir einen YouTube-Link zum Download"
GREETING_HINT_SEARCH = "• Nutze /search um Musik zu suchen"

# ====== HELP (/help + Help-Callback) ======

HELP_INTRO_TITLE = "📚 **Hilfe & Dokumentation**\n"
HELP_INTRO_SUBTITLE = "Übersicht aller Funktionen:\n"

HELP_GENERAL_COMMANDS_HEADER = "\n⚡ **Allgemeine Befehle:**"
HELP_CMD_START = "• /start - Bot neu starten"
HELP_CMD_MENU = "• /menu - Hauptmenü öffnen"
HELP_CMD_HELP = "• /help - Diese Hilfe anzeigen"
HELP_CMD_CANCEL = "• /cancel - Aktion abbrechen\n"
HELP_SUPPORT_HEADER = "💬 **Benötigst du Unterstützung?**"
HELP_SUPPORT_TEXT = "Nutze /menu und navigiere zu den jeweiligen Funktionen."

HELP_MAIN_MENU_TEXT = "📚 **Hilfe & Dokumentation**\n\nWähle ein Thema:"

HELP_DOWNLOAD = (
    "📥 **Download-Hilfe**\n\n"
    "**YouTube-Downloads:**\n"
    "1. Kopiere einen YouTube-Link\n"
    "2. Sende ihn an den Bot\n"
    "3. Der Bot lädt die Musik herunter\n\n"
    "Beispiel: `https://youtube.com/watch?v=...`\n\n"
    "**Unterstützte Formate:**\n"
    "• Einzelne Videos, Playlists, Mix-Playlists"
)

HELP_STATS = (
    "📊 **Statistik-Hilfe**\n\n"
    "• 📅 Monatsrückblick\n"
    "• 🎆 Jahresrückblick\n"
    "• 🎵 Top Songs\n"
    "• 🎤 Top Künstler\n\n"
    "Alle Statistiken basieren auf deinem Navidrome-Account."
)

HELP_NAVIDROME = (
    "🎵 **Navidrome-Hilfe**\n\n"
    "• 🔍 Suche nach Songs, Alben, Künstlern\n"
    "• 📂 Durchsuche nach Kategorien\n"
    "• ⭐ Favoriten verwalten\n"
    "• 📋 Playlists verwalten\n\n"
    "Befehle: /search, /menu → Navidrome"
)

HELP_ADMIN = (
    "⚙️ **Admin-Hilfe**\n\n"
    "• 👥 Benutzerverwaltung\n"
    "• 📊 Logger-Verwaltung\n"
    "• 🔄 Bot neu starten\n"
    "• 💾 Backup-Verwaltung\n"
    "• 🧪 Test-System\n"
    "• 🚨 Error-Verwaltung\n\n"
    "Alle Admin-Aktionen werden geloggt."
)

# ====== BUTTON-LABELS (mehrfach verwendet) ======

BTN_MAIN_MENU = "🏠 Hauptmenü"
BTN_CLOSE = "❌ Schließen"
BTN_HELP_DOWNLOAD = "📥 Downloads"
BTN_HELP_STATS = "📊 Statistiken"
BTN_HELP_NAVIDROME = "🎵 Navidrome"
BTN_HELP_ADMIN = "⚙️ Admin-Hilfe"

# ====== FEHLERTEXTE ======

ERROR_GENERIC = "❌ Ein Fehler ist aufgetreten."
