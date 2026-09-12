# handlers/menu/definitions.py
# -*- coding: utf-8 -*-
"""
Menü-Definitionen: Aufbau der Menü-Hierarchie (MenuItem-Baum) und der
flachen Registry.

ARCH-024/P-3 (Definitions Extraction): 1:1 aus
handlers/menu/rich_menu_system.py::initialize_menu_structure()/
_build_registry() verschoben (reine Move-Operation).

Architekturentscheidung (siehe
docs/MusicBot_ARCH-024_Menu_File_Decomposition.md, Abschnitt P-3):
build_menu_tree() nimmt die RichMenuSystem-Instanz (`system`) entgegen,
nicht nur einzelne Abhängigkeiten - anders als die actions/-Module, die
bewusst keine Rückreferenz auf ihren Aufrufer halten. Grund: die
MenuItem.handler-Bindungen SIND per Definition an Methoden von
RichMenuSystem selbst gebunden (die dünnen `_handle_*`-Delegatoren aus
ARCH-024/P-2) - das ist keine neue Kopplung, sondern die bereits
bestehende, unveränderte Verdrahtung. Eine Umgestaltung auf einzeln
injizierte Callables hätte hier keinen Kohäsionsgewinn gebracht, nur
eine sehr lange Parameterliste erzeugt.
"""

from typing import Dict

from handlers.menu.models import AccessLevel, MenuItem


def build_menu_tree(system) -> MenuItem:
    """Erstellt die Menü-Hierarchie. `system` ist die RichMenuSystem-
    Instanz, deren dünne `_handle_*`-Delegatoren (ARCH-024/P-2) als
    MenuItem.handler gebunden werden."""
    # Hauptmenü
    root_menu = MenuItem(
        id="main",
        title="Hauptmenü",
        emoji="🏠",
        description="Willkommen beim Musik-Bot",
    )

    # Download-Menü
    # Download-Control-Center 2026-09-02 (Nutzer-Vorgabe): handler=
    # macht "download" zu einem eigenen Aktions-Menüpunkt statt der
    # generischen render_menu()-Darstellung seiner Kinder (analog zu
    # dup:/status_/backup_/restart: - siehe _handle_download_menu()
    # weiter unten). Die beiden statischen Kinder darunter bleiben in
    # der Registry bestehen (harmlos, ungenutzt) - _handle_download_menu()
    # baut die Tastatur komplett selbst.
    download_menu = MenuItem(
        id="download",
        title="Downloads",
        emoji="📥",
        description="Musik herunterladen",
        handler=system._handle_download_menu,
        is_action=True,
    )
    download_menu.add_child(
        MenuItem(
            id="download_single",
            title="Einzelner Track",
            emoji="🎵",
            handler=system._handle_download_single,
            is_action=True,
        )
    )
    download_menu.add_child(
        MenuItem(
            id="download_playlist",
            title="Playlist",
            emoji="📋",
            handler=system._handle_download_playlist,
            is_action=True,
        )
    )

    # Statistik-Menü
    stats_menu = MenuItem(
        id="stats",
        title="Statistiken",
        emoji="📊",
        description="Übersichten und Analysen",
    )
    stats_menu.add_child(
        MenuItem(
            id="stats_monthly",
            title="Monatsrückblick",
            emoji="📅",
            handler=system._handle_stats_monthly,
            is_action=True,
        )
    )
    stats_menu.add_child(
        MenuItem(
            id="stats_yearly",
            title="Jahresrückblick",
            emoji="🎆",
            handler=system._handle_stats_yearly,
            is_action=True,
        )
    )
    stats_menu.add_child(
        MenuItem(
            id="stats_top_songs",
            title="Top Songs",
            emoji="🎵",
            handler=system._handle_stats_top_songs,
            is_action=True,
        )
    )
    stats_menu.add_child(
        MenuItem(
            id="stats_top_artists",
            title="Top Künstler",
            emoji="🎤",
            handler=system._handle_stats_top_artists,
            is_action=True,
        )
    )
    stats_menu.add_child(
        MenuItem(
            id="stats_timeline",
            title="Music Timeline",
            emoji="📅",
            handler=system._handle_stats_timeline,
            is_action=True,
        )
    )
    stats_menu.add_child(
        MenuItem(
            id="stats_library_overview",
            title="Library Übersicht",
            emoji="📚",
            handler=system._handle_stats_library_overview,
            is_action=True,
        )
    )

    # Familien-Statistik (Phase F2, Family Hub) - neuer Zweig NEBEN den
    # bestehenden persönlichen Statistik-Punkten (stats_monthly/...),
    # die unverändert bleiben (Master-Prompt: "Bestehende Callback-Namen
    # und Navigation nicht unnötig brechen"). Zugriff wird serverseitig
    # in FamilyStatsHandler geprüft (Family-Membership), nicht hier.
    family_stats_menu = MenuItem(
        id="family_stats",
        title="Familien-Statistik",
        emoji="👨‍👩‍👧‍👦",
        description="Statistiken für alle Familienmitglieder",
    )
    family_stats_menu.add_child(
        MenuItem(
            id="family_stats_top_songs",
            title="Top Songs Familie",
            emoji="🎵",
            handler=system._handle_family_stats_top_songs,
            is_action=True,
        )
    )
    family_stats_menu.add_child(
        MenuItem(
            id="family_stats_top_artists",
            title="Top Künstler Familie",
            emoji="🎤",
            handler=system._handle_family_stats_top_artists,
            is_action=True,
        )
    )
    family_stats_menu.add_child(
        MenuItem(
            id="family_stats_member",
            title="Statistik pro Person",
            emoji="👥",
            handler=system._handle_family_stats_member,
            is_action=True,
        )
    )
    family_stats_menu.add_child(
        MenuItem(
            id="family_stats_champion",
            title="Musik-Champion",
            emoji="🏆",
            handler=system._handle_family_stats_champion,
            is_action=True,
        )
    )
    family_stats_menu.add_child(
        MenuItem(
            id="family_stats_listening_times",
            title="Hörzeiten",
            emoji="⏰",
            handler=system._handle_family_stats_listening_times,
            is_action=True,
        )
    )
    family_stats_menu.add_child(
        MenuItem(
            id="family_stats_monthly_trend",
            title="Monatsentwicklung",
            emoji="📈",
            handler=system._handle_family_stats_monthly_trend,
            is_action=True,
        )
    )
    stats_menu.add_child(family_stats_menu)

    # Familien-Chat (Phase F3, Family Hub) - eigenes Top-Level-Menü
    # (Geschwister von "stats", nicht darunter verschachtelt), analog
    # zur Master-Prompt-Zielstruktur. Zugriff wird serverseitig in
    # FamilyChatHandler geprüft (Family-Membership), nicht hier.
    family_chat_menu = MenuItem(
        id="family_chat",
        title="Familien-Chat",
        emoji="💬",
        description="Privater Chat für Familienmitglieder",
    )
    family_chat_menu.add_child(
        MenuItem(
            id="family_chat_send",
            title="Nachricht senden",
            emoji="📝",
            handler=system._handle_family_chat_send,
            is_action=True,
        )
    )
    family_chat_menu.add_child(
        MenuItem(
            id="family_chat_recent",
            title="Letzte Nachrichten",
            emoji="📋",
            handler=system._handle_family_chat_recent,
            is_action=True,
        )
    )
    family_chat_menu.add_child(
        MenuItem(
            id="family_chat_notifications",
            title="Benachrichtigungen",
            emoji="🔔",
            handler=system._handle_family_chat_notifications,
            is_action=True,
        )
    )

    # Familien-Challenge (Phase F4, Family Hub) - eigenes Top-Level-
    # Menü, analog zu family_chat. Zugriff wird serverseitig in
    # FamilyChallengeHandler geprüft (Family-Membership), nicht hier.
    family_challenge_menu = MenuItem(
        id="family_challenge",
        title="Familien-Challenge",
        emoji="🎯",
        description="Tägliche Musik-Challenge für die Familie",
    )
    family_challenge_menu.add_child(
        MenuItem(
            id="family_challenge_today",
            title="Heutige Challenge",
            emoji="❓",
            handler=system._handle_family_challenge_today,
            is_action=True,
        )
    )
    family_challenge_menu.add_child(
        MenuItem(
            id="family_challenge_answer",
            title="Antworten",
            emoji="✅",
            handler=system._handle_family_challenge_answer,
            is_action=True,
        )
    )
    family_challenge_menu.add_child(
        MenuItem(
            id="family_challenge_leaderboard",
            title="Punktestand",
            emoji="🏆",
            handler=system._handle_family_challenge_leaderboard,
            is_action=True,
        )
    )

    # Admin-Menü
    admin_menu = MenuItem(
        id="admin",
        title="Administration",
        emoji="⚙️",
        access_level=AccessLevel.ADMIN,
        description="System-Verwaltung",
    )

    # Admin-Menü-Reorg (UX/Navigation, siehe Analyse-Bericht): drei
    # thematische Gruppen-Container - reine Navigationsknoten (kein
    # handler=, kein eigenes callback_data noetig, automatisch
    # "menu:<id>", bereits durch das generische "^menu:"-Pattern in
    # RichMenuHandler.get_telegram_handlers() abgedeckt, siehe
    # docs/MusicBot_TELEGRAM_MENU_SYSTEM.md Abschnitt 6 - kein neuer
    # CallbackQueryHandler noetig). Duplikat-Verwaltung und
    # Benutzerverwaltung bleiben bewusst direkte Administration-Kinder
    # (CLAUDE.md Abschnitt 5/15: Duplicate Detection ist eine eigene
    # P0-Domaene, nicht Teil von "Bibliothek").
    admin_group_library = MenuItem(
        id="admin_group_library",
        title="Bibliothek & Navidrome",
        emoji="🎵",
        access_level=AccessLevel.ADMIN,
        description="Library-Diagnose, Reprocessing und Navidrome-Scan",
    )
    admin_group_operations = MenuItem(
        id="admin_group_operations",
        title="Bot & Betrieb",
        emoji="🤖",
        access_level=AccessLevel.ADMIN,
        description="Bot-Neustart, Wartungsmodus und Backups",
    )
    admin_group_diagnostics = MenuItem(
        id="admin_group_diagnostics",
        title="Diagnose & Monitoring",
        emoji="🩺",
        access_level=AccessLevel.ADMIN,
        description="System-Status, Logs, Fehler und Logger-Steuerung",
    )

    # System-Status
    admin_group_diagnostics.add_child(
        MenuItem(
            id="admin_status",
            title="System-Status",
            emoji="📊",
            access_level=AccessLevel.ADMIN,
            callback_data="status_menu",
            handler=system._handle_status_menu,
            is_action=True,
        )
    )

    # Benutzerverwaltung
    admin_users_item = MenuItem(
        id="admin_users",
        title="Benutzerverwaltung",
        emoji="👥",
        access_level=AccessLevel.ADMIN,
        is_action=True,
    )

    # System-Logs
    admin_group_diagnostics.add_child(
        MenuItem(
            id="admin_logs",
            title="System-Logs",
            emoji="📄",
            access_level=AccessLevel.ADMIN,
            is_action=True,
        )
    )

    # Duplikat-Verwaltung
    duplicate_menu = MenuItem(
        id="admin_duplicates",
        title="Duplikat-Verwaltung",
        emoji="♻️",
        access_level=AccessLevel.ADMIN,
        description="Verwaltung des Download-Duplikat-Cache",
    )
    duplicate_menu.add_child(
        MenuItem(
            id="dup_show_stats",
            title="Statistiken anzeigen",
            emoji="📊",
            callback_data="dup:show_stats",
            is_action=True,
            handler=None,
        )
    )
    duplicate_menu.add_child(
        MenuItem(
            id="dup_clear_cache_confirm",
            title="Cache leeren",
            emoji="🗑️",
            callback_data="dup:clear_cache_confirm",
            is_action=True,
            handler=None,
        )
    )

    # Error-Verwaltung
    error_menu = MenuItem(
        id="admin_errors",
        title="Error-Verwaltung",
        emoji="🚨",
        access_level=AccessLevel.ADMIN,
        description="Überwachung und Verwaltung des Error Handlers",
    )
    error_menu.add_child(
        MenuItem(
            id="erradmin_stats",
            title="Statistiken",
            emoji="📊",
            callback_data="erradmin:show_stats",
            is_action=True,
        )
    )
    error_menu.add_child(
        MenuItem(
            id="erradmin_report",
            title="Gesundheitsbericht",
            emoji="🏥",
            callback_data="erradmin:show_report",
            is_action=True,
        )
    )
    error_menu.add_child(
        MenuItem(
            id="erradmin_recent",
            title="Letzte Fehler",
            emoji="🕐",
            callback_data="erradmin:show_recent",
            is_action=True,
        )
    )
    error_menu.add_child(
        MenuItem(
            id="erradmin_reset_confirm",
            title="Statistiken zurücksetzen",
            emoji="🔄",
            callback_data="erradmin:reset_confirm",
            is_action=True,
        )
    )
    admin_group_diagnostics.add_child(error_menu)

    # Logger-Management
    logger_menu = MenuItem(
        id="logger",
        title="Logger-Verwaltung",
        emoji="📈",
        access_level=AccessLevel.ADMIN,
        description="Erweiterte Logger-Steuerung und -Überwachung",
    )
    # TGPERM-001-Fix (siehe docs/audits/FULL_PROJECT_ARCHITECTURE_AUDIT_
    # 2026-09-12.md): callback_data wird hier bewusst explizit auf die
    # ID gesetzt statt der automatischen "menu:<id>"-Generierung
    # (MenuItem.__post_init__) zu ueberlassen. Ohne dieses Override
    # dispatchte handle_callback() diese ADMIN-Items ueber den
    # generischen "menu:"-Fallback (Ende von handle_callback(), ruft
    # menu_item.handler() OHNE jede Berechtigungspruefung auf) statt
    # ueber den bereits vorhandenen, in _ADMIN_ONLY_PREFIXES gegateten
    # "logger_"-Praefixpfad (_handle_logger_callback()'s routing_map,
    # die exakt dieselben IDs bereits kennt). Die vormaligen
    # `handler=system._handle_logger_*`-Wrapper sind dadurch obsolet und
    # wurden entfernt (siehe frueher "LOGGER-HANDLER WRAPPER").
    logger_menu.add_child(
        MenuItem(
            id="logger_main_menu",
            title="Logger-Übersicht",
            emoji="🏠",
            access_level=AccessLevel.ADMIN,
            callback_data="logger_main_menu",
            is_action=True,
        )
    )
    logger_menu.add_child(
        MenuItem(
            id="logger_modules_list",
            title="Module verwalten",
            emoji="📦",
            access_level=AccessLevel.ADMIN,
            callback_data="logger_modules_list",
            is_action=True,
        )
    )
    logger_menu.add_child(
        MenuItem(
            id="logger_global_level",
            title="Globales Level",
            emoji="🌍",
            access_level=AccessLevel.ADMIN,
            callback_data="logger_global_level",
            is_action=True,
        )
    )
    logger_menu.add_child(
        MenuItem(
            id="logger_files_list",
            title="Log-Dateien",
            emoji="📁",
            access_level=AccessLevel.ADMIN,
            callback_data="logger_files_list",
            is_action=True,
        )
    )
    logger_menu.add_child(
        MenuItem(
            id="logger_global_stats",
            title="Statistiken",
            emoji="📈",
            access_level=AccessLevel.ADMIN,
            callback_data="logger_global_stats",
            is_action=True,
        )
    )
    logger_menu.add_child(
        MenuItem(
            id="logger_handlers_list",
            title="Handler-Verwaltung",
            emoji="⚡",
            access_level=AccessLevel.ADMIN,
            callback_data="logger_handlers_list",
            is_action=True,
        )
    )
    logger_menu.add_child(
        MenuItem(
            id="logger_cleanup_menu",
            title="Bereinigung",
            emoji="🧹",
            access_level=AccessLevel.ADMIN,
            callback_data="logger_cleanup_menu",
            is_action=True,
        )
    )
    admin_group_diagnostics.add_child(logger_menu)

    # Backup-Verwaltung
    backup_menu = MenuItem(
        id="admin_backup",
        title="Backup-Verwaltung",
        emoji="💾",
        access_level=AccessLevel.ADMIN,
        description="Sicherung von Bot-Verzeichnis und Musikbibliothek",
    )
    backup_menu.add_child(
        MenuItem(
            id="backup_main",
            title="Backup-Übersicht",
            emoji="🏠",
            access_level=AccessLevel.ADMIN,
            callback_data="backup_main",
            handler=system._handle_backup_main,
            is_action=True,
        )
    )
    backup_menu.add_child(
        MenuItem(
            id="backup_bot_confirm",
            title="Bot sichern",
            emoji="🤖",
            access_level=AccessLevel.ADMIN,
            callback_data="backup_bot_confirm",
            handler=system._handle_backup_bot_confirm,
            is_action=True,
        )
    )
    backup_menu.add_child(
        MenuItem(
            id="backup_lib_confirm",
            title="Library sichern",
            emoji="🎵",
            access_level=AccessLevel.ADMIN,
            callback_data="backup_lib_confirm",
            handler=system._handle_backup_lib_confirm,
            is_action=True,
        )
    )
    backup_menu.add_child(
        MenuItem(
            id="backup_list_bot",
            title="Bot-Backups",
            emoji="📋",
            access_level=AccessLevel.ADMIN,
            callback_data="backup_list_bot",
            handler=system._handle_backup_list_bot,
            is_action=True,
        )
    )
    backup_menu.add_child(
        MenuItem(
            id="backup_list_lib",
            title="Library-Backups",
            emoji="📋",
            access_level=AccessLevel.ADMIN,
            callback_data="backup_list_lib",
            handler=system._handle_backup_list_lib,
            is_action=True,
        )
    )
    admin_group_operations.add_child(backup_menu)

    # ====== NEU: BOT-NEUSTART ======
    admin_group_operations.add_child(
        MenuItem(
            id="admin_restart",
            title="Bot neu starten",
            emoji="🔄",
            access_level=AccessLevel.ADMIN,
            callback_data="restart:show",
            handler=system._handle_restart_show,
            is_action=True,
            description="Bot-Service via systemctl neu starten",
        )
    )
    # ====== ENDE BOT-NEUSTART ======

    # ====== NEU: WARTUNGSMODUS ======
    admin_group_operations.add_child(
        MenuItem(
            id="admin_maintenance",
            title="Wartungsmodus",
            emoji="🛠️",
            access_level=AccessLevel.ADMIN,
            callback_data="maint:show",
            handler=system._handle_maintenance_show,
            is_action=True,
            description="Bot für alle außer Admins pausieren/fortsetzen",
        )
    )
    # ====== ENDE WARTUNGSMODUS ======

    # ====== NEU: METADATA-REPROCESSING ======
    # Nutzer-Entscheidung: nur Owner (nicht Admin) - greift auf
    # Metadata-/Auto-Learn-Dateien zu, siehe docs/FINDINGS_INDEX.md.
    admin_group_library.add_child(
        MenuItem(
            id="admin_reprocessing",
            title="Reprocessing",
            emoji="🔧",
            access_level=AccessLevel.OWNER,
            callback_data="reprocess:show",
            handler=system._handle_reprocessing_show,
            is_action=True,
            description="Metadata eines Test-Artists erneut verarbeiten",
        )
    )
    # ====== ENDE METADATA-REPROCESSING ======

    # ====== NEU: MUSICBOT DOCTOR (Phase 3, P1.3) ======
    admin_group_library.add_child(
        MenuItem(
            id="admin_library_doctor",
            title="MusicBot Doctor",
            emoji="🩺",
            access_level=AccessLevel.ADMIN,
            callback_data="doctor:scan",
            handler=system._handle_doctor_scan,
            is_action=True,
            description="Library Health-Scan + sichere Tag-/Namens-Reparaturen",
        )
    )
    # ====== ENDE MUSICBOT DOCTOR ======

    # ====== NEU: LIBRARY HEALTH REVIEW ======
    admin_group_library.add_child(
        MenuItem(
            id="admin_library_health_review",
            title="Library Health Review",
            emoji="🔎",
            access_level=AccessLevel.ADMIN,
            callback_data="review:start",
            handler=system._handle_review_start,
            is_action=True,
            description="Offene Health-Findings nach Kategorie prüfen "
                        "(Resolve/False Positive)",
        )
    )
    # ====== ENDE LIBRARY HEALTH REVIEW ======

    # ====== NEU: REPAIR MUSICBOT ======
    admin_group_library.add_child(
        MenuItem(
            id="admin_repair_musicbot",
            title="Repair MusicBot",
            emoji="🛠️",
            access_level=AccessLevel.ADMIN,
            callback_data="repair:start",
            handler=system._handle_repair_start,
            is_action=True,
            description="Reparaturplan/-vorschläge, SAFE_AUTOMATIC-Ausführung, "
                        "Historie & Statistik",
        )
    )
    # ====== ENDE REPAIR MUSICBOT ======

    # Admin-Menü-Reorg: Gruppen-Container an Administration haengen -
    # Reihenfolge hier = Anzeige-Reihenfolge im Menü (siehe
    # Analyse-Bericht, Abschnitt F/H).
    admin_menu.add_child(admin_group_library)
    admin_menu.add_child(admin_group_operations)
    admin_menu.add_child(admin_group_diagnostics)
    admin_menu.add_child(duplicate_menu)
    admin_menu.add_child(admin_users_item)

    # Test-Menü
    test_menu = MenuItem(
        id="tests",
        title="Test-System",
        emoji="🧪",
        access_level=AccessLevel.ADMIN,
        description="Unit-, Integrations- und Performance-Tests ausführen",
    )
    test_menu.add_child(
        MenuItem(
            id="test_unit",
            title="Unit Tests ausführen",
            emoji="🔬",
            access_level=AccessLevel.ADMIN,
            is_action=True,
        )
    )
    test_menu.add_child(
        MenuItem(
            id="test_integration",
            title="Integration Tests ausführen",
            emoji="🔗",
            access_level=AccessLevel.ADMIN,
            is_action=True,
        )
    )
    test_menu.add_child(
        MenuItem(
            id="test_performance",
            title="Performance Tests ausführen",
            emoji="⚡",
            access_level=AccessLevel.ADMIN,
            is_action=True,
        )
    )

    # Navidrome-Menü
    navidrome_menu = MenuItem(
        id="navidrome",
        title="Navidrome Mediathek",
        emoji="🎵",
        access_level=AccessLevel.USER,
        description="Durchsuche und verwalte deine Musikbibliothek",
    )

    # Browse-Untermenüs
    browse_menu = MenuItem(
        id="navidrome_browse",
        title="Durchsuchen",
        emoji="🔍",
        description="Musikbibliothek nach Kategorien durchsuchen",
    )
    browse_menu.add_child(
        MenuItem(
            id="nav_browse_artists",
            title="Künstler",
            emoji="🎤",
            handler=system._handle_navidrome_browse_artists,
            is_action=True,
        )
    )
    browse_menu.add_child(
        MenuItem(
            id="nav_browse_albums",
            title="Alben",
            emoji="💿",
            handler=system._handle_navidrome_browse_albums,
            is_action=True,
        )
    )
    browse_menu.add_child(
        MenuItem(
            id="nav_browse_genres",
            title="Genres",
            emoji="🎭",
            handler=system._handle_navidrome_browse_genres,
            is_action=True,
        )
    )
    browse_menu.add_child(
        MenuItem(
            id="nav_browse_playlists",
            title="Playlists",
            emoji="📋",
            handler=system._handle_navidrome_browse_playlists,
            is_action=True,
        )
    )

    # Suche-Menü
    search_menu = MenuItem(
        id="navidrome_search",
        title="Suchen",
        emoji="🔎",
        description="Musikbibliothek durchsuchen",
    )
    search_menu.add_child(
        MenuItem(
            id="nav_search",
            title="Überall suchen",
            emoji="🔍",
            handler=system._handle_navidrome_search_all,
            is_action=True,
        )
    )
    search_menu.add_child(
        MenuItem(
            id="nav_search_artists",
            title="Künstler suchen",
            emoji="🎤",
            handler=system._handle_navidrome_search_artists,
            is_action=True,
        )
    )
    search_menu.add_child(
        MenuItem(
            id="nav_search_albums",
            title="Alben suchen",
            emoji="💿",
            handler=system._handle_navidrome_search_albums,
            is_action=True,
        )
    )
    search_menu.add_child(
        MenuItem(
            id="nav_search_songs",
            title="Songs suchen",
            emoji="🎵",
            handler=system._handle_navidrome_search_songs,
            is_action=True,
        )
    )

    navidrome_menu.add_child(browse_menu)
    navidrome_menu.add_child(search_menu)
    navidrome_menu.add_child(
        MenuItem(
            id="nav_playlists",
            title="Meine Playlists",
            emoji="📋",
            handler=system._handle_navidrome_my_playlists,
            is_action=True,
        )
    )
    navidrome_menu.add_child(
        MenuItem(
            id="nav_favorites",
            title="Favoriten",
            emoji="⭐",
            handler=system._handle_navidrome_favorites,
            is_action=True,
        )
    )
    navidrome_menu.add_child(
        MenuItem(
            id="nav_recent",
            title="Zuletzt gespielt",
            emoji="🕐",
            handler=system._handle_navidrome_recent,
            is_action=True,
        )
    )
    navidrome_menu.add_child(
        MenuItem(
            id="nav_link_stats",
            title="Statistiken",
            emoji="📊",
            callback_data="menu:stats",
            handler=None,
            is_action=False,
        )
    )

    # Menüs zum Root hinzufügen
    root_menu.add_child(download_menu)
    root_menu.add_child(stats_menu)
    root_menu.add_child(family_chat_menu)
    root_menu.add_child(family_challenge_menu)
    root_menu.add_child(admin_menu)
    root_menu.add_child(test_menu)
    root_menu.add_child(navidrome_menu)

    return root_menu


def populate_registry(registry: Dict[str, MenuItem], menu: MenuItem) -> None:
    """Baut flache Registry für schnellen Zugriff - mutiert `registry`
    in place (Dict-Identität bleibt erhalten, siehe
    RichMenuSystem._build_registry())."""
    registry[menu.id] = menu
    for child in menu.children:
        populate_registry(registry, child)
