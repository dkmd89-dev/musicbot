# tests/test_lastfm_client_network_repr_scrubbing.py
# -*- coding: utf-8 -*-
"""
Baseline v5/v6 Technical Debt (P3, latentes Secret-Leak-Risiko):
pylast.LastFMNetwork.__repr__() baut api_key/api_secret/session_key/
password_hash direkt in den Repr-String ein (live gegen die installierte
pylast-Version verifiziert: `repr(pylast.LastFMNetwork(api_key="X",
api_secret="Y", ...))` == "pylast.LastFMNetwork('X', 'Y', '', 'None',
'None')"). Da praktisch jedes von einem Network-Objekt erzeugte
pylast-Domainobjekt (Artist, Track, Album, Tag, ...) sein eigenes
__repr__() wiederum ueber repr(self.network) aufbaut, wuerde JEDES
versehentliche repr()/f"{obj!r}"-Logging eines beliebigen pylast-Objekts -
nicht nur des Network-Objekts selbst - alle vier Secrets im Klartext
offenlegen. Aktuell nirgends im Code aufgerufen (kein aktives Leck, siehe
tests/test_lastfm_client.py fuer die bestehende Characterization), aber
ein latentes Risiko bei kuenftigen Aenderungen (z.B. ein Debug-Log wie
f"Artist-Objekt: {artist_obj!r}").

__str__() ("{name} Network") war bereits sicher (verifiziert, kein
Secret-Bezug) und wird hier nicht angefasst - nur __repr__() ist
betroffen.

Fix: services/clients/lastfm_client.py patcht pylast.LastFMNetwork.__repr__
beim Modul-Import auf eine sichere, redigierte Fassung. Instanz-Attribute
koennen __repr__ nicht ueberschreiben (Python loest Dunder-Methoden fuer
eingebaute Funktionen wie repr() immer auf der Klasse auf, nie auf der
Instanz) - der Patch muss daher auf Klassenebene erfolgen und wirkt damit
automatisch auch fuer Artist/Track/etc., deren __repr__() lediglich
repr(self.network) delegiert.
"""

import pylast

# Import loest den __repr__-Patch aus (Modul-Seiteneffekt beim Import,
# siehe services/clients/lastfm_client.py).
import services.clients.lastfm_client  # noqa: F401

SECRET_API_KEY = "SUPER_SECRET_LASTFM_API_KEY_123"
SECRET_API_SECRET = "SUPER_SECRET_LASTFM_API_SECRET_456"


def _make_network():
    return pylast.LastFMNetwork(
        api_key=SECRET_API_KEY,
        api_secret=SECRET_API_SECRET,
        username=None,
        password_hash=None,
    )


class TestLastFMNetworkReprIsScrubbed:
    def test_repr_does_not_contain_api_key(self):
        network = _make_network()
        assert SECRET_API_KEY not in repr(network)

    def test_repr_does_not_contain_api_secret(self):
        network = _make_network()
        assert SECRET_API_SECRET not in repr(network)

    def test_repr_is_a_stable_redacted_placeholder(self):
        network = _make_network()
        assert repr(network) == "pylast.LastFMNetwork(<redacted>)"

    def test_str_remains_unaffected_and_secret_free(self):
        """__str__() war bereits sicher - Nichtregressionsschutz, dass der
        __repr__-Patch dieses Verhalten nicht veraendert."""
        network = _make_network()
        text = str(network)
        assert SECRET_API_KEY not in text
        assert SECRET_API_SECRET not in text
        assert text == "Last.fm Network"


class TestDependentPylastObjectsInheritTheScrubbedRepr:
    """Der eigentliche Kern des Funds: nicht nur das Network-Objekt selbst,
    sondern JEDES pylast-Domainobjekt, dessen __repr__() repr(self.network)
    delegiert, muss ebenfalls sicher sein."""

    def test_artist_repr_does_not_contain_secrets(self):
        network = _make_network()
        artist = pylast.Artist("Test Artist", network)

        text = repr(artist)

        assert SECRET_API_KEY not in text
        assert SECRET_API_SECRET not in text
        assert "pylast.LastFMNetwork(<redacted>)" in text

    def test_artist_str_is_unaffected(self):
        network = _make_network()
        artist = pylast.Artist("Test Artist", network)
        assert str(artist) == "Test Artist"
