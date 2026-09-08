from utils.title_cleanup import light_title_cleanup


def test_removes_german_feature_credit_at_end():
    """Entfernt '(MIT Artist)' als abschließenden Titel-Credit."""
    assert light_title_cleanup("IMMER (MIT MAKKO)", "Ski Aggu") == "IMMER"


def test_removes_german_feature_credit_case_insensitive():
    """Der '(mit Artist)'-Credit wird unabhängig von Groß-/Kleinschreibung entfernt."""
    assert light_title_cleanup("IMMER (mit Makko)", "Ski Aggu") == "IMMER"


def test_removes_german_feature_credit_with_multiple_artists():
    """Mehrere Namen im abschließenden '(MIT ...)'-Block werden entfernt."""
    assert (
        light_title_cleanup("IMMER (MIT MAKKO & Ski Aggu)", "Ski Aggu")
        == "IMMER"
    )


def test_does_not_remove_non_terminal_mit():
    """Normale 'mit'-Vorkommen innerhalb eines Titels bleiben erhalten."""
    assert light_title_cleanup("Komm mit mir", "Ski Aggu") == "Komm mit mir"


def test_does_not_remove_other_parenthetical_content():
    """Andere abschließende Klammerinhalte bleiben erhalten."""
    assert light_title_cleanup("IMMER (Live)", "Ski Aggu") == "IMMER (Live)"
