# -*- coding: utf-8 -*-

"""
Definiert Befehls-Kategorien und Beschreibungen für den Telegram-Bot.

Wird von command_handler.py, button_handler.py etc. importiert.
"""

from emoji import EMOJI

COMMAND_CATEGORIES = {
    "📚 Navidrome": {
        "📂 Medien": ["artists", "indexes", "albumlist", "genres", "search"],
        "📂 Bibliothek": [
            "navidrome",
            "scan",
            "test_api",
            "rescan_library",
            "duplicate_check",
            "last_scan",
            "library_stats",
        ],
        "📊 Playstatistiken": [
            "topsongs",
            "topsongs7",
            "topartists",
            "monthreview",
            "yearreview",
        ],
        "🎧 Aktivität": ["playing", "lastplayed", "activity_feed"],
    },
    "▶️ YouTube Befehle": ["download", "youtube_status", "last_download"],
    "⚙️ System & Hilfe": {
        "🔧 System": [
            "status",
            "quickstatus",
            "detailedstatus",
            "backup",
            "view_scripts",
            "tests",
            "self_update",
            "module_restart",
        ],
        "📋 Logging": [
            "loglevels",
            "viewlogs",
            "clearlogs",
            "live_log",
            "config_profile",
        ],
        "🖥️ Bot-Steuerung": ["stop", "config_state", "version_info"],
        "❓ Hilfe": ["help", "context_help"],
        "🛠️ Wartung": ["rescan_metadata", "rescan_interactive", "rescan_m4a"],
    },
    "🎵 chiLL": {
        "🎧 Musik durchsuchen": ["library_browse", "library_play"],
        "🎲 Zufallswiedergabe": ["random_song", "random_album"],
        "⭐ Favoriten": ["favorites_add", "favorites_list", "favorites_play"],
        "📅 Playlists": ["playlists", "playlist_add", "playlist_play"],
    },
    "🧩 Personalisierung & Mapper": {
        "🎨 Mappings": ["genre_mapper_edit", "artist_normalizer_edit"],
        "⚙️ Module": ["module_settings", "update_mappings", "test_parser"],
        "⚙️ Unity-Test": ["download_handler", "apis", "markdown"],
    },
}

# --- Befehlsbeschreibungen mit Emojis für Telegram ---

# Diese Beschreibungen werden direkt im Bot verwendet, daher enthalten sie Emojis und sind für den Benutzer optimiert.

COMMAND_DESCRIPTIONS = {
    # BESCHREIBUNGEN FÜR UNTERKATEGORIEN (bestehende)
    f"{EMOJI.get('folder', '📁')} Medien": "Medien: Künstler, Alben, Genres, Suche",
    f"{EMOJI.get('folder', '📁')} Bibliothek": "Bibliothek: Navidrome URL, Scans, Rescans",
    f"{EMOJI.get('chart', '📊')} Playstatistiken": "Statistiken: Top Songs, Künstler, Rückblicke",
    f"{EMOJI.get('headphones', '🎧')} Aktivität": "Aktivität: Aktuelle & letzte Titel",
    f"{EMOJI.get('wrench', '🛠️')} System": "System: Status, Backup, Tests",
    f"{EMOJI.get('clipboard', '📋')} Logging": "Logging: Logs verwalten",
    f"{EMOJI.get('computer', '🖥️')} Bot-Steuerung": "Bot: Stoppen, Neu starten, Infos",
    f"{EMOJI.get('help_symbol', '❓')} Hilfe": "Hilfe & Infos",
    # NEUE BESCHREIBUNGEN FÜR UNTERKATEGORIEN (chiLL)
    f"{EMOJI.get('headphones', '🎧')} Musik durchsuchen": "In deiner lokalen Musikbibliothek stöbern.",
    f"{EMOJI.get('game_die', '🎲')} Zufallswiedergabe": "Zufällige Titel oder Alben abspielen.",
    # Navidrome Befehle (bestehende)
    f"{EMOJI.get('artist', '🎤')} artists": "Alle Künstler anzeigen",
    f"{EMOJI.get('folder', '📁')} indexes": "Alle Indexe anzeigen",
    f"{EMOJI.get('album', '📀')} albumlist": "Alle Alben anzeigen",
    f"{EMOJI.get('genres', '🎶')} genres": "Verfügbare Genres anzeigen",
    f"{EMOJI.get('navidrome', '🎵')} navidrome": "Navidrome Webinterface öffnen",
    f"{EMOJI.get('scan', '📡')} scan": "Vollständigen Navidrome Scan starten",
    f"{EMOJI.get('scan', '📡')} rescan_library": "Bibliothek neu scannen & Metadaten aktualisieren",
    f"{EMOJI.get('black_circle', '⚫')} test_api": "Navidrome API-Verbindung testen",
    f"{EMOJI.get('search', '🔍')} search": "Songs nach Titel/Künstler suchen",
    # NEUE BESCHREIBUNGEN FÜR BEFEHLE
    f"{EMOJI.get('music_note', '🎵')} rescan_metadata": "Metadaten aller .m4a-Dateien neu einlesen",
    f"{EMOJI.get('folder_search', '🔍')} rescan_interactive": "Interaktiven Rescan für bestimmte Ordner starten",
    f"{EMOJI.get('music_note', '🎵')} rescan_m4a": "M4A-Metadaten neu einlesen (nur .m4a-Dateien)",
    # Playstatistiken (bestehende)
    f"{EMOJI.get('topsongs', '🏆')} topsongs": "Top 10 Songs (30 Tage)",
    f"{EMOJI.get('topsongs', '🏆')} topsongs7": "Top 10 Songs (7 Tage)",
    f"{EMOJI.get('topartists', '🧑🎤')} topartists": "Top 10 Künstler (30 Tage)",
    f"{EMOJI.get('calendar', '📅')} monthreview": "Monatsrückblick der Hörgewohnheiten",
    f"{EMOJI.get('trophy', '🏅')} yearreview": "Jahresstatistik & Highlights",
    f"{EMOJI.get('now_playing', '▶️')} playing": "Aktuellen Titel anzeigen",
    f"{EMOJI.get('lastplayed', '↩️')} lastplayed": "Zuletzt gehörten Song anzeigen",
    # YouTube Befehle (bestehende)
    f"{EMOJI.get('download', '📥')} download": "YouTube-Audio herunterladen (URL nötig)",
    # System Befehle (bestehend)
    f"{EMOJI.get('status', '📊')} status": "Systemstatus & Ressourcenauslastung",
    f"{EMOJI.get('status_quick', '📊')} quickstatus": "Kompakte Statusübersicht",
    f"{EMOJI.get('status_detailed', '📈')} detailedstatus": "Detaillierte Systeminformationen (Admin)",
    f"{EMOJI.get('backup', '📦')} backup": "Vollständiges Musikordner-Backup",
    f"{EMOJI.get('scroll', '📜')} view_scripts": "Gespeicherte Skripte anzeigen & laden",
    f"{EMOJI.get('test_tube', '🧪')} tests": "Interaktiven Unit-Test-Runner öffnen",
    # Logger-Management Befehle (bestehend)
    f"{EMOJI.get('settings', '⚙️')} setloglevel": "Log-Level eines Loggers ändern",
    f"{EMOJI.get('info', 'ℹ️')} loglevels": "Aktuelle Log-Level anzeigen",
    f"{EMOJI.get('scroll', '📜')} viewlogs": "Letzte Log-Einträge anzeigen",
    f"{EMOJI.get('trash', '🗑️')} clearlogs": "Alle Log-Dateien löschen",
    # Bot-Steuerung Befehle
    f"{EMOJI.get('stop_button', '⏹️')} stop": "Bot stoppen oder neu starten",
    f"{EMOJI.get('computer', '🖥️')} config_state": "Aktuelle Konfiguration anzeigen",
    f"{EMOJI.get('information_source', 'ℹ️')} version_info": "Version und Details des Bots anzeigen",
    # Hilfe
    f"{EMOJI.get('help', '❓')} help": "Befehlsübersicht & Hilfe",
    f"{EMOJI.get('help', '❓')} context_help": "Hilfe zum aktuellen Menüpunkt",
}
