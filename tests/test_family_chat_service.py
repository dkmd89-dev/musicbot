"""
Phase F3 (Family Hub) - Tests für services/family/family_chat_service.py.

Nutzt FakeFamilyRepository (wie tests/test_family_service.py) und ein
FakeFamilyMessageRepository (in-memory) - keine echten Dateien.
"""

from services.family.family_chat_service import (
    MAX_MESSAGE_LENGTH,
    FamilyChatService,
)
from services.family.family_service import FamilyService


class FakeFamilyRepository:
    def __init__(self, families):
        self._families = families

    def get_all_families(self):
        return dict(self._families)

    def get_family(self, family_id):
        return self._families.get(family_id, {})

    def update_member(self, family_id, telegram_id, updates):
        family = self._families.get(family_id)
        if not family or telegram_id not in family.get("members", {}):
            return False
        family["members"][telegram_id].update(updates)
        return True


class FakeFamilyMessageRepository:
    def __init__(self):
        self.added = []

    def add_message(self, family_id, sender_user_id, sender_display_name, message):
        entry = {
            "id": len(self.added) + 1,
            "family_id": family_id,
            "sender_user_id": sender_user_id,
            "sender_display_name": sender_display_name,
            "message": message,
            "created_at": "2026-09-12T18:00:00",
        }
        self.added.append(entry)
        return entry

    def get_recent_messages(self, family_id, limit=10):
        return [m for m in self.added if m["family_id"] == family_id][-limit:]


import copy

FAMILIES = {
    "main": {
        "name": "Familie",
        "members": {
            "111": {
                "display_name": "Papa",
                "navidrome_user": "papa",
                "active": True,
                "notifications": True,
            },
            "222": {
                "display_name": "Mama",
                "navidrome_user": "mama",
                "active": True,
                "notifications": True,
            },
            "333": {
                "display_name": "OhneNotify",
                "navidrome_user": "ohnenotify",
                "active": True,
                "notifications": False,
            },
            "444": {
                "display_name": "Inaktiv",
                "navidrome_user": "inaktiv",
                "active": False,
                "notifications": True,
            },
        },
    },
    "other": {
        "name": "Andere Familie",
        "members": {
            "555": {
                "display_name": "Fremd",
                "navidrome_user": "fremd",
                "active": True,
                "notifications": True,
            }
        },
    },
}


def _make_service():
    family_service = FamilyService(repository=FakeFamilyRepository(copy.deepcopy(FAMILIES)))
    message_repo = FakeFamilyMessageRepository()
    return FamilyChatService(family_service=family_service, message_repository=message_repo)


class TestPostMessage:
    def test_stores_message_for_active_member(self):
        service = _make_service()
        entry = service.post_message(111, "Hallo Familie!")

        assert entry is not None
        assert entry["sender_display_name"] == "Papa"
        assert entry["message"] == "Hallo Familie!"
        assert entry["family_id"] == "main"

    def test_returns_none_for_stranger(self):
        service = _make_service()
        assert service.post_message(999, "Hallo") is None

    def test_returns_none_for_inactive_member(self):
        service = _make_service()
        assert service.post_message(444, "Hallo") is None

    def test_returns_none_for_empty_message(self):
        service = _make_service()
        assert service.post_message(111, "   ") is None

    def test_truncates_overly_long_message(self):
        service = _make_service()
        long_text = "x" * (MAX_MESSAGE_LENGTH + 100)
        entry = service.post_message(111, long_text)

        assert len(entry["message"]) == MAX_MESSAGE_LENGTH


class TestGetRecentMessages:
    def test_returns_none_for_stranger(self):
        service = _make_service()
        assert service.get_recent_messages(999) is None

    def test_returns_empty_list_when_no_messages_yet(self):
        service = _make_service()
        assert service.get_recent_messages(111) == []

    def test_returns_messages_of_own_family_only(self):
        service = _make_service()
        service.post_message(111, "Family 1")
        service.message_repository.add_message("other", "555", "Fremd", "Family 2")

        messages = service.get_recent_messages(111)

        assert [m["message"] for m in messages] == ["Family 1"]


class TestGetNotificationRecipients:
    def test_excludes_sender_itself(self):
        service = _make_service()
        recipients = service.get_notification_recipients(111)
        assert "111" not in recipients

    def test_excludes_member_with_notifications_disabled(self):
        service = _make_service()
        recipients = service.get_notification_recipients(111)
        assert "333" not in recipients

    def test_excludes_inactive_member(self):
        service = _make_service()
        recipients = service.get_notification_recipients(111)
        assert "444" not in recipients

    def test_includes_other_active_member_with_notifications_enabled(self):
        service = _make_service()
        recipients = service.get_notification_recipients(111)
        assert recipients == ["222"]

    def test_returns_empty_list_for_stranger(self):
        service = _make_service()
        assert service.get_notification_recipients(999) == []


class TestSetNotifications:
    def test_toggles_via_family_service(self):
        service = _make_service()
        assert service.notifications_enabled(333) is False

        ok = service.set_notifications(333, True)

        assert ok is True
        assert service.notifications_enabled(333) is True
