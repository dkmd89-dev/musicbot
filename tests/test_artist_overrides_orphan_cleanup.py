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
#
# Nachtrag 2026-09-03 (Nutzer-Entscheidung): 'Toobrokeforfiji' wurde durch
# echte Live-Testdownloads dieser Session (Genre-Lock-in-Testphase)
# real vom Auto-Learn-System in artist_overrides.json geschrieben.
# Bewusst als dauerhaft gewuenschter Override behalten, nicht entfernt -
# hier in die Whitelist aufgenommen statt den Eintrag zu loeschen.
#
# Nachtrag 2026-09-07: 'Christina Stürmer' wurde durch einen echten,
# regulaeren Download waehrend laufender Entwicklungsarbeit vom
# Auto-Learn-System in artist_overrides.json geschrieben - echter neuer
# Library-Artist, kein Datenmuell. Analog zu Toobrokeforfiji in die
# Whitelist aufgenommen statt entfernt.
#
# Nachtrag 2026-09-09: PR #194 ('fix(artist): Kollab mit gemeinsamem
# Nachnamen', Commit a7efab6) hat 8 Keys fuer den Deutschrap-/Techno-
# Kollab-Fall 'Fritz & Paul Kalkbrenner' -> Wert 'Fritz Kalkbrenner'
# ergaenzt (7 Kollab-Schreibvarianten + der Self-Eintrag), diesen
# Integritaetstest dabei aber nicht mitgezogen. 'Fritz Kalkbrenner' ist
# ein realer Artist (Fix per test_collab_artist_shared_surname_kalkbrenner.py
# abgesichert) - in die Whitelist aufgenommen, Key-Count 21 -> 29.
#
# Nachtrag 2026-09-12: durch einen echten, regulaeren Download waehrend
# laufender Entwicklungsarbeit hat das Auto-Learn-System den zusaetzlichen
# Key 'fiji' -> 'Toobrokeforfiji' geschrieben (neben dem bereits
# bestehenden Key 'toobrokeforfiji' -> 'Toobrokeforfiji', vermutlich ein
# kuerzerer YouTube-Channel-/Credit-Name derselben Person). Der Wert
# 'Toobrokeforfiji' ist bereits seit 2026-09-03 whitelisted - kein neuer
# Wert, nur ein zusaetzlicher Schreibvarianten-Key. Key-Count 29 -> 30.
WHITELIST_VALUES_LOWER = {
    "01099",
    "2pac",
    "badchieff",
    "chapo102",
    "christina stürmer",
    "clueso",
    "florian künstler",
    "fritz kalkbrenner",
    "gustav",
    "kings of leon",
    "levin liam",
    "makko",
    "pur",
    "ravyn lenae",
    "miksu & macloud",
    "t-low",
    "toobrokeforfiji",
}


class TestArtistOverridesFreeOfOrphans:
    def test_every_value_is_either_a_library_artist_or_test_protected(self):
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        orphans = {v for v in data.values() if v.lower() not in WHITELIST_VALUES_LOWER}
        assert not orphans, f"verwaiste Overrides gefunden: {orphans}"

    def test_expected_key_count_after_cleanup(self):
        """Dokumentiert den bereinigten Stand (zuletzt 2026-09-12): 30 Keys
        - 21 wie beim 2026-09-07-Stand (12 Library-Artists, davon 'makko'
        als 1, + 6 Miksu & Macloud-Varianten + 't-low' + 'toobrokeforfiji'
        + 'christina sturmer') + 8 aus PR #194 fuer den
        'Fritz & Paul Kalkbrenner'-Kollab-Fall (7 Schreibvarianten + Self)
        + 1 neuer Key 'fiji' (zusaetzliche Schreibvariante fuer den
        bereits whitelisteten Wert 'Toobrokeforfiji', echter Download
        2026-09-12). Kein Anspruch auf ewige Gueltigkeit dieser exakten
        Zahl - wird bei zukuenftigen legitimen Aenderungen bewusst
        angepasst, nicht blind hochgezaehlt."""
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 30

    def test_no_junk_entries_like_pycache(self):
        """Regressionsschutz: der vor der Bereinigung gefundene
        Datenmuell-Eintrag '__pycache__' darf nicht zurueckkehren."""
        with open("mapping/artist_overrides.json", encoding="utf-8") as f:
            data = json.load(f)
        assert "__pycache__" not in data
