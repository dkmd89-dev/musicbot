"""
Daten-Integritaetstest: mapping/artist_overrides.json bleibt frei von
verwaisten Eintraegen (2026-09-03, Genre-Lock-in-/Override-Entkopplungs-
Auftrag).

Ausgangslage: mapping/artist_overrides.json enthielt 174 eindeutige Werte
aus einer frueheren, deutlich groesseren Library-Version - die aktuelle,
echte Produktions-Library (config.LIBRARY_DIR) hat nur noch 12
Artist-Ordner. Die Datei wurde einmalig auf eine Whitelist bereinigt (12
aktuelle Library-Artists + Werte, die von den bestehenden Daten-
Integritaetstests test_artist_overrides_t_low_case_preserve.py und
test_artist_overrides_miksu_macloud_duo.py direkt gegen diese Datei geprueft
werden - per Nutzerentscheidung: "Nur wirklich verwaiste Eintraege
entfernen", nicht strikt auf den Library-Stand reduzieren).

Dieser Test schuetzt gegen erneutes unkontrolliertes Anwachsen (CLAUDE.md
Regel 3: Mapping-Aenderungen wie Codeaenderungen behandeln). Bewusst KEINE
Live-Library-Scan-Kopplung (wuerde den Testlauf an einen Mount binden, der
in anderen Umgebungen fehlt) - dieselbe statische Whitelist wie beim
einmaligen Bereinigungslauf, analog zum etablierten Muster der bestehenden
Overrides-Integritaetstests.
"""

import json

# 12 aktuelle Library-Artists (verifiziert gegen /mnt/musik_bilder/library
# am 2026-09-03) + testabgesichert: 'Miksu & Macloud' (6 Schreibvarianten,
# siehe test_artist_overrides_miksu_macloud_duo.py) + 't-low' (siehe
# test_artist_overrides_t_low_case_preserve.py).
WHITELIST_VALUES_LOWER = {
    "01099",
    "2pac",
    "badchieff",
    "chapo102",
    "clueso",
    "florian künstler",
    "gustav",
    "kings of leon",
    "levin liam",
    "makko",
    "pur",
    "ravyn lenae",
    "miksu & macloud",
    "t-low",
}


class TestArtistOverridesFreeOfOrphans:
    def test_every_value_is_either_a_library_artist_or_test_protected(self):
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        orphans = {v for v in data.values() if v.lower() not in WHITELIST_VALUES_LOWER}
        assert not orphans, f"verwaiste Overrides gefunden: {orphans}"

    def test_expected_key_count_after_cleanup(self):
        """Dokumentiert den bereinigten Stand (2026-09-03): 19 Keys (12
        Library-Artists, davon 'makko' als 1, + 6 Miksu & Macloud-Varianten
        + 't-low' = 19). Kein Anspruch auf ewige Gueltigkeit dieser exakten
        Zahl - wird bei zukuenftigen legitimen Aenderungen bewusst
        angepasst, nicht blind hochgezaehlt."""
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 19

    def test_no_junk_entries_like_pycache(self):
        """Regressionsschutz: der vor der Bereinigung gefundene
        Datenmuell-Eintrag '__pycache__' darf nicht zurueckkehren."""
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        assert "__pycache__" not in data
