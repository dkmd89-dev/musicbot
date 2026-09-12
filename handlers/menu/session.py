# handlers/menu/session.py
# -*- coding: utf-8 -*-
"""
Session-Verwaltung für das RichMenuSystem.

ARCH-021/P-4 (Session/State Extraction): get_session()/
cleanup_expired_sessions() sowie das zugehörige Sessions-Dict und die
Session-Konfiguration (session_timeout/max_sessions) wurden unverändert
aus handlers/menu/rich_menu_system.py hierher verschoben (reine Move-
Operation, siehe ARCH-021/P-4-Audit - Behavior Preservation, keine
funktionale Änderung).

Dieses Modul darf keine Abhängigkeit auf rich_menu_system.py,
rich_menu_handler.py oder Telegram-Infrastruktur haben.

Bewusst NICHT Teil dieser Extraktion (siehe ARCH-021/P-4-Audit
Abschnitt 2.3/2.4/3.4):
  - max_sessions wird weiterhin nur gehalten, nie durchgesetzt
    (bestehender, unveränderter Zustand - keine Kapazitätsbegrenzung).
  - MenuSession.state/.data/.message_id bleiben unangetastet in
    handlers/menu/models.py (teils toter Zustand, nicht Gegenstand
    dieses Schrittes).
  - RichMenuHandler.user_states (Dict[int, str]) ist ein eigenständiger,
    unabhängiger State-Mechanismus und hier nicht betroffen.
"""

from typing import Dict

from handlers.menu.models import MenuSession


class SessionManager:
    """Verwaltet MenuSession-Instanzen (Erzeugung, Ablauf, Bereinigung)."""

    def __init__(self, session_timeout: int, max_sessions: int, logger):
        self.sessions: Dict[int, MenuSession] = {}
        self.session_timeout = session_timeout
        self.max_sessions = max_sessions
        self.logger = logger

    def get_session(self, user_id: int) -> MenuSession:
        """Holt oder erstellt User-Session"""
        if user_id not in self.sessions:
            self.sessions[user_id] = MenuSession(user_id=user_id)
            self.logger.debug(f"📝 Neue Session für User {user_id}")

        session = self.sessions[user_id]

        if session.is_expired(self.session_timeout):
            self.logger.info(f"⏰ Session für User {user_id} abgelaufen, erneuere...")
            self.sessions[user_id] = MenuSession(user_id=user_id)
            session = self.sessions[user_id]

        session.update_activity()
        return session

    def cleanup_expired_sessions(self) -> int:
        """Entfernt abgelaufene Sessions"""
        expired = [
            uid
            for uid, session in self.sessions.items()
            if session.is_expired(self.session_timeout)
        ]

        for uid in expired:
            del self.sessions[uid]

        if expired:
            self.logger.info(f"🧹 {len(expired)} abgelaufene Sessions bereinigt")

        return len(expired)
