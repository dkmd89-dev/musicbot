# tests/test_menu_content_user_context.py
# -*- coding: utf-8 -*-
"""
Regressionstest fuer handlers/menu/content/user_context.py::FEATURES.

Telegram Start/Help/Menu UX Finalization v2: das "commands"-Feld wurde
entfernt, da es ausschliesslich erfundene, nie registrierte
Telegram-Befehle enthielt (siehe Moduldocstring). Dieser Test verhindert
ein versehentliches Wiedereinfuehren eines solchen Felds ohne
Verifikation gegen die echte Command-Registrierung.
"""

from handlers.menu.content.user_context import FEATURES


def test_features_have_no_commands_field():
    for feature_id, feature in FEATURES.items():
        assert "commands" not in feature, (
            f"FEATURES['{feature_id}'] enthaelt wieder ein 'commands'-Feld - "
            "gegen die tatsaechliche Telegram-Command-Registrierung pruefen, "
            "bevor es reaktiviert wird (siehe Moduldocstring)."
        )


def test_features_have_required_keys():
    for feature_id, feature in FEATURES.items():
        assert "emoji" in feature
        assert "title" in feature
        assert "description" in feature
        assert "min_role" in feature
        assert "menu_id" in feature
