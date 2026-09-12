"""
Phase F1 (Family Hub) - Tests für services/family/family_service.py.

Fokus: die serverseitige Zugriffsprüfung aus dem Master-Prompt
("Telegram User ID -> Familienmitglied? -> Family ID -> Zugriff erlaubt")
und Family-Isolation (ein Mitglied der Familie A darf niemals als
Mitglied der Familie B erkannt werden; ein normaler Bot-Benutzer ohne
Family-Eintrag hat keinerlei Zugriff).

Nutzt ein FakeFamilyRepository statt der echten data/family_data.json,
analog zum Fake/Mock-Prinzip für Persistenz in diesem Projekt (CLAUDE.md
Abschnitt 7/8).
"""

import copy

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


FAMILIES = {
    "main": {
        "name": "Familie",
        "members": {
            "490171109": {
                "display_name": "dkmd",
                "navidrome_user": "dkmd",
                "active": True,
                "notifications": True,
            },
            "7851063538": {
                "display_name": "marina",
                "navidrome_user": "marina",
                "active": True,
                "notifications": True,
            },
            "999": {
                "display_name": "Inaktiv",
                "navidrome_user": "inaktiv",
                "active": False,
                "notifications": True,
            },
            "888": {
                "display_name": "OhneNotify",
                "navidrome_user": "ohnenotify",
                "active": True,
                "notifications": False,
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
    # Deep copy - einige Tests (set_notifications) mutieren die Fake-
    # Repository über update_member(); ohne Kopie würde das den
    # modulweiten FAMILIES-Fixture-Dict dauerhaft verändern und andere
    # Tests je nach Ausführungsreihenfolge verfälschen.
    return FamilyService(repository=FakeFamilyRepository(copy.deepcopy(FAMILIES)))


class TestGetFamilyIdForTelegramUser:
    def test_known_member_resolves_to_correct_family_id(self):
        service = _make_service()
        assert service.get_family_id_for_telegram_user(490171109) == "main"

    def test_member_of_other_family_resolves_to_that_family_only(self):
        service = _make_service()
        assert service.get_family_id_for_telegram_user(555) == "other"

    def test_unknown_telegram_id_resolves_to_none(self):
        service = _make_service()
        assert service.get_family_id_for_telegram_user(123456789) is None

    def test_accepts_int_and_str_telegram_id_consistently(self):
        service = _make_service()
        assert service.get_family_id_for_telegram_user(
            "490171109"
        ) == service.get_family_id_for_telegram_user(490171109)


class TestFamilyIsolation:
    def test_member_of_main_is_not_treated_as_member_of_other(self):
        service = _make_service()
        assert service.get_family_id_for_telegram_user(490171109) != "other"

    def test_get_members_of_main_does_not_leak_members_of_other(self):
        service = _make_service()
        members = service.get_members("main")
        assert "555" not in members

    def test_get_members_of_unknown_family_id_returns_empty_dict(self):
        service = _make_service()
        assert service.get_members("does-not-exist") == {}

    def test_stranger_without_family_entry_has_no_access(self):
        service = _make_service()
        stranger_id = 42
        assert service.is_family_member(stranger_id) is False
        assert service.is_active_family_member(stranger_id) is False
        assert service.get_member(stranger_id) is None
        assert service.notifications_enabled(stranger_id) is False


class TestActiveMemberCheck:
    def test_active_member_passes_access_check(self):
        service = _make_service()
        assert service.is_active_family_member(490171109) is True

    def test_inactive_member_fails_access_check_despite_being_a_member(self):
        service = _make_service()
        assert service.is_family_member(999) is True
        assert service.is_active_family_member(999) is False

    def test_get_members_active_only_excludes_inactive_member(self):
        service = _make_service()
        active_members = service.get_members("main", active_only=True)
        assert "999" not in active_members
        assert "490171109" in active_members


class TestNotifications:
    def test_notifications_enabled_true_for_active_member_with_flag_set(self):
        service = _make_service()
        assert service.notifications_enabled(490171109) is True

    def test_notifications_enabled_false_when_flag_disabled(self):
        service = _make_service()
        assert service.notifications_enabled(888) is False

    def test_notifications_enabled_false_for_inactive_member_even_if_flag_set(self):
        service = _make_service()
        assert service.notifications_enabled(999) is False


class TestGetNavidromeUsers:
    def test_returns_mapping_of_telegram_id_to_navidrome_user(self):
        service = _make_service()
        mapping = service.get_navidrome_users("main")
        assert mapping == {
            "490171109": "dkmd",
            "7851063538": "marina",
            "888": "ohnenotify",
        }

    def test_excludes_inactive_members_by_default(self):
        service = _make_service()
        mapping = service.get_navidrome_users("main")
        assert "999" not in mapping

    def test_active_only_false_includes_inactive_members(self):
        service = _make_service()
        mapping = service.get_navidrome_users("main", active_only=False)
        assert "999" in mapping

    def test_unknown_family_id_returns_empty_mapping(self):
        service = _make_service()
        assert service.get_navidrome_users("does-not-exist") == {}


class TestSetNotifications:
    def test_enables_and_persists_for_known_member(self):
        service = _make_service()
        ok = service.set_notifications(888, True)

        assert ok is True
        assert service.notifications_enabled(888) is True

    def test_disables_for_known_member(self):
        service = _make_service()
        ok = service.set_notifications(490171109, False)

        assert ok is True
        assert service.notifications_enabled(490171109) is False

    def test_returns_false_for_stranger(self):
        service = _make_service()
        ok = service.set_notifications(42, True)
        assert ok is False
