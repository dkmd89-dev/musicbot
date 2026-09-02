# services/duplicate/detector.py
# -*- coding: utf-8 -*-
"""
DuplicateDetector – fachlicher Kern der Duplicate-Detection
(URL-/Content-/Parser-/Library-Fallback-Kaskade, Registrierung neuer
Downloads, Statistik).

ARCH-018 Phase 2 (docs/archive/arch/MusicBot_ARCH-018_Duplicate_Handler_Characterization.md):
extrahiert aus handlers/duplicate_handler.py::EnhancedDuplicateHandler.
Dieser Kern (Abschnitt 6 der Characterization) hat keine Telegram-
Abhängigkeit - er wurde bereits vor der Extraktion ausschließlich über
check_for_duplicates()/register_download() von klassen/download_handler.py
konsumiert. handlers/duplicate_handler.py::EnhancedDuplicateHandler bleibt
als reine Telegram-Präsentationsschicht bestehen und hält intern eine
Instanz dieser Klasse (Delegation), damit ihr öffentliches Verhalten für
den bestehenden Präsentations-Anwendungsfall unverändert bleibt.

Verhalten, Signaturen und Logik unverändert gegenüber dem Ausgangszustand
übernommen - keine fachliche Änderung im Rahmen dieser Extraktion.

Phase 2.2 (MusicBot — Duplicate Resolution Phase 2.2, Parität zu
services/duplicate/classification.py::normalize_title_for_identity()):
_clean_title_for_comparison() entfernt zusätzlich ein umschließendes
Anführungszeichen-Paar (_strip_wrapping_quote_pair()) - Fix für einen in
Phase 2.1 (Real Findings Audit) dokumentierten False-Negative-Fund
(inkonsistent gesetzte Anführungszeichen zwischen Single-/Album-Tag
derselben Aufnahme, z. B. '"Bequem"' vs. 'Bequem'). Minimale,
nachweislich notwendige Paritätsanpassung - keine sonstige Änderung an
dieser Klasse.
"""

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Dict, Optional, Callable, Tuple
from datetime import datetime

from config import Config
from logger import get_module_logger

from utils.artist_map import ArtistConfig, ArtistNormalizer
from utils.youtube_parser import parse_youtube_title
from services.downloader.models import DuplicateEntry
from services.duplicate.cache import DuplicateCache
from services.metadata.artist_processor import ArtistProcessor

# Phase 2.2: exakte Kopie von services/duplicate/classification.py::
# _TITLE_QUOTE_PAIRS/_strip_wrapping_quote_pair() - siehe dortige
# Begründung (Real Findings Audit Phase 2.1). Bewusst als freie Funktion
# auf Modulebene (nicht als Instanzmethode), da sie keinen Zugriff auf
# "self" benötigt - exakt dasselbe Muster wie bei den bereits
# bestehenden, in classification.py gespiegelten Methoden dieser Klasse.
_TITLE_QUOTE_PAIRS = (
    ("\u0022", "\u0022"),  # straight double quote, U+0022
    ("'", "'"),  # straight single quote, U+0027
    ("„", "“"),  # „...“  (deutsche Konvention)
    ("“", "”"),  # “...”  (englische Konvention, curly double)
    ("‘", "’"),  # ‘...’  (englische Konvention, curly single)
)


def _strip_wrapping_quote_pair(text: str) -> str:
    """Entfernt GENAU EIN äußeres, vollständig umschließendes und
    zusammenpassendes Anführungszeichen-Paar - siehe
    services/duplicate/classification.py::_strip_wrapping_quote_pair()
    für die vollständige Begründung (identische Implementierung)."""
    if len(text) < 2:
        return text
    for open_q, close_q in _TITLE_QUOTE_PAIRS:
        if text[0] == open_q and text[-1] == close_q:
            inner = text[1:-1].strip()
            return inner if inner else text
    return text


class DuplicateDetector:
    """Fachlicher Kern der Duplicate-Detection (Telegram-frei)."""

    def __init__(self, config: Config, logger_factory: Optional[Callable] = None):
        # Logger mit Dependency Injection
        self.logger_factory = logger_factory or get_module_logger
        self.logger = self.logger_factory("DuplicateDetector")

        self.config = config
        self.db_path = getattr(
            config, "DUPLICATE_CACHE_DIR", Path("./duplicate_db.json")
        )

        self.duplicate_cache = DuplicateCache(
            cache_dir=getattr(config, "DUPLICATE_CACHE_DIR", "duplicate_cache"),
            logger=self.logger_factory("DuplicateCache"),
        )

        # P1 (docs/audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md):
        # vorher hasattr(config, "artist_config")-Gate, das ausschliesslich
        # auf ein Attribut prueft, das die echte config.Config nirgends im
        # Repo setzt - self.artist_normalizer blieb dadurch in der
        # Produktion IMMER None (P0-E-Fund). ArtistNormalizer ist ein
        # SingletonMixin - welcher Aufrufer ihn zuerst mit welchen Werten
        # konstruiert, ist irrelevant fuer alle anderen Aufrufer im selben
        # Prozess (sie bekommen dieselbe bereits initialisierte Instanz
        # zurueck). Spiegelt deshalb unconditional denselben ArtistConfig-
        # Aufbau wie EnhancedMetadataProcessor.__init__()
        # (services/metadata/enhanced_metadata_processor.py) - dieselben
        # Config-Werte, damit beide Aufrufer bei tatsaechlich erster
        # Konstruktion identisches Verhalten ergeben wuerden. Path(...)-
        # Wrapping hier zusaetzlich explizit (anders als im enhanced_
        # metadata_processor.py-Vorbild) - konsistent zur bereits
        # etablierten Konvention dieser Klasse (self.db_path/
        # check_library_duplicate() wrappen Config-Pfadwerte ebenfalls
        # defensiv), da ArtistNormalizer._load_library_artists() zwingend
        # ein echtes Path-Objekt braucht (.exists()) - reine config.Config
        # liefert bereits Path, einige Test-Fixtures dieser Klasse bisher
        # bewusst Strings (nur ueber Path(library_dir) intern genutzt).
        artist_config = ArtistConfig(
            library_dir=Path(getattr(self.config, "LIBRARY_DIR", "library")),
            override_file=Path(
                getattr(
                    self.config, "ARTIST_OVERRIDE_FILE", "./artist_overrides.json"
                )
            ),
            mapping_dir=(
                Path(mapping_dir)
                if (mapping_dir := getattr(self.config, "GENRE_MAPPING_DIR", None))
                else None
            ),
        )
        self.artist_normalizer = ArtistNormalizer(artist_config)
        # Extract-Korrektur (P1, siehe Kommentar oben): ArtistNormalizer.
        # normalize() entfernt Channel-Suffixe wie "- Topic"/"VEVO"/
        # "Official" NICHT selbststaendig - das uebernimmt erst
        # ArtistProcessor.clean_artist_before_normalization() davor (der
        # Leerzeichen-Separator-Split "Kygo - Topic" -> "Kygo", plus
        # Komma-Split/Music/Records-Regex). Live waehrend der Extract-
        # Phase entdeckt: ohne diesen vorgeschalteten Schritt haette das
        # reine Verdrahten von ArtistNormalizer die urspruengliche P0-E-
        # Luecke nur verschoben statt geschlossen (die kurze, in P0-E
        # ergaenzte Fallback-Liste dieser Klasse waere durch den jetzt
        # immer erfolgreichen artist_normalizer-Zweig unerreichbar
        # geworden, OHNE dass "- Topic" tatsaechlich erkannt wird). Nutzt
        # deshalb denselben ArtistProcessor wie die Metadaten-Pipeline
        # (services/metadata/enhanced_metadata_processor.py) - identische
        # Bereinigung fuer beide Aufrufer.
        self.artist_processor = ArtistProcessor(
            artist_normalizer=self.artist_normalizer,
            logger=self.logger_factory("ArtistProcessor"),
        )

        self.stats = {
            "url_duplicates_found": 0,
            "content_duplicates_found": 0,
            "new_entries_added": 0,
            "total_checks": 0,
            "duplicates_skipped": 0,
        }

        # DUP-05 (docs/FINDINGS_INDEX.md, urspruenglich docs/archive/
        # MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md): zwischen
        # einem "kein Duplikat"-Ergebnis von check_for_duplicates() und der
        # tatsaechlichen Registrierung via register_download() liegt die
        # komplette Download+Verarbeitungsdauer (Sekunden bis Minuten) -
        # ein zweiter, paralleler Request fuer denselben Content sah in
        # dieser Zeit ebenfalls "kein Duplikat" (Check-then-Register-Race,
        # begrenzt auf maximal _download_semaphore gleichzeitige Downloads).
        # Minimaler Fix wie im Audit vorgeschlagen: In-Memory-Set "aktuell
        # in Bearbeitung befindlicher" Hashes, zusaetzlich zum persistenten
        # Cache geprueft. TTL-basierter Ablauf (statt zwingendem
        # try/finally an jeder Aufrufstelle) haelt den Fix bewusst auf
        # DuplicateDetector beschraenkt, ohne klassen/download_handler.py
        # anzufassen - ein verwaister Eintrag (Absturz/Exception waehrend
        # des Downloads) loest sich nach der TTL von selbst auf, statt
        # dauerhaft einen erneuten Download derselben URL/desselben
        # Contents zu blockieren. register_download() raeumt den Eintrag
        # zusaetzlich sofort bei tatsaechlichem Erfolg ab (siehe dort).
        self._in_flight: Dict[str, float] = {}
        self._in_flight_ttl_seconds = getattr(
            config, "DUPLICATE_IN_FLIGHT_TTL_SECONDS", 900
        )

        self.logger.info("🔍 DuplicateDetector initialisiert")

    def _is_in_flight(self, content_or_url_hash: Optional[str]) -> bool:
        if not content_or_url_hash:
            return False
        claimed_at = self._in_flight.get(content_or_url_hash)
        if claimed_at is None:
            return False
        if time.time() - claimed_at > self._in_flight_ttl_seconds:
            # Abgelaufen - vermutlich verwaist (Absturz/Exception ohne
            # register_download()). Kein Match mehr, wird beim naechsten
            # claim ueberschrieben statt den Download dauerhaft zu blockieren.
            del self._in_flight[content_or_url_hash]
            return False
        return True

    def _claim_in_flight(self, *hashes: Optional[str]) -> None:
        now = time.time()
        for h in hashes:
            if h:
                self._in_flight[h] = now

    def _release_in_flight(self, *hashes: Optional[str]) -> None:
        for h in hashes:
            if h:
                self._in_flight.pop(h, None)

    def check_for_duplicates(
        self,
        url: str,
        raw_artist: str = None,
        raw_title: str = None,
        track_metadata: Dict = None,
    ) -> Tuple[bool, Optional[DuplicateEntry], str]:
        self.stats["total_checks"] += 1
        self.logger.debug(f"🔍 Prüfe Duplikate für: {url}")

        url_duplicate = self.duplicate_cache.check_url_duplicate(url)
        if url_duplicate:
            self.stats["url_duplicates_found"] += 1
            self.stats["duplicates_skipped"] += 1
            self.logger.info(
                f"🔗 URL-Duplikat gefunden: {url_duplicate.artist} - {url_duplicate.title}"
            )
            return True, url_duplicate, "url"

        # DUP-05: In-Flight-Check schliesst die Race zwischen zwei
        # parallelen Downloads derselben URL, bevor der erste registriert
        # hat (siehe Begruendung/Kommentar in __init__).
        url_hash = self.duplicate_cache.get_url_hash(url)
        if self._is_in_flight(url_hash):
            self.stats["duplicates_skipped"] += 1
            self.logger.info(
                f"⏳ URL bereits in Bearbeitung (paralleler Download): {url}"
            )
            return True, None, "in_flight"

        content_hash = None
        if raw_artist and raw_title:
            normalized_artist = self._normalize_artist_for_comparison(raw_artist)
            cleaned_title = self._clean_title_for_comparison(
                raw_title, normalized_artist
            )
            content_hash = self.duplicate_cache.get_content_hash(
                normalized_artist, cleaned_title
            )
            content_duplicate = self.duplicate_cache.check_content_duplicate(
                normalized_artist, cleaned_title
            )
            if content_duplicate:
                self.stats["content_duplicates_found"] += 1
                self.stats["duplicates_skipped"] += 1
                self.logger.info(
                    f"🎵 Content-Duplikat gefunden: {content_duplicate.artist} - {content_duplicate.title}"
                )
                return True, content_duplicate, "content"
            if self._is_in_flight(content_hash):
                self.stats["duplicates_skipped"] += 1
                self.logger.info(
                    f"⏳ Content bereits in Bearbeitung (paralleler Download): "
                    f"{normalized_artist} - {cleaned_title}"
                )
                return True, None, "in_flight"

        title_to_parse = raw_title or (
            track_metadata and track_metadata.get("title", "")
        )
        if title_to_parse:
            parsed = parse_youtube_title(title_to_parse)
            if parsed.get("artist") and parsed.get("song_title"):
                parsed_artist = self._normalize_artist_for_comparison(parsed["artist"])
                parsed_title = self._clean_title_for_comparison(
                    parsed["song_title"], parsed_artist
                )
                parsed_duplicate = self.duplicate_cache.check_content_duplicate(
                    parsed_artist, parsed_title
                )
                if parsed_duplicate:
                    self.stats["content_duplicates_found"] += 1
                    self.stats["duplicates_skipped"] += 1
                    self.logger.info(
                        f"🔍 Parsed-Content-Duplikat gefunden: {parsed_duplicate.artist} - {parsed_duplicate.title}"
                    )
                    return True, parsed_duplicate, "parsed_content"

        # 📁 Library-Fallback: Prüfe ob Datei bereits physisch in der Library existiert.
        # Greift auch wenn register_download nie aufgerufen wurde (z.B. nach Neustart).
        title_for_lib = raw_title or (
            track_metadata and track_metadata.get("title", "")
        )
        artist_for_lib = raw_artist or (
            track_metadata and track_metadata.get("artist", "")
        )
        if artist_for_lib and title_for_lib:
            lib_path = self.check_library_duplicate(artist_for_lib, title_for_lib)
            if lib_path:
                self.stats["content_duplicates_found"] += 1
                self.stats["duplicates_skipped"] += 1
                lib_entry = DuplicateEntry(
                    artist=artist_for_lib,
                    title=title_for_lib,
                    url=url,
                    file_path=lib_path,
                    download_date=datetime.now(),
                )
                # Eintrag nachträglich in Cache registrieren
                self.duplicate_cache.add_entry(lib_entry)
                self.logger.info(
                    f"📁 Library-Duplikat erkannt und Cache aktualisiert: "
                    f"'{artist_for_lib} - {title_for_lib}'"
                )
                return True, lib_entry, "library"

        # DUP-05: kein Duplikat gefunden - URL/Content als "in Bearbeitung"
        # markieren, damit ein paralleler zweiter Request fuer dieselbe
        # URL/denselben Content waehrend der laufenden Download-/
        # Verarbeitungsdauer als Duplikat erkannt wird (Race-Fenster
        # geschlossen). Deckt bewusst nur url_hash/content_hash ab
        # (dieselben zwei Ebenen, die register_download() tatsaechlich
        # registriert) - der parsed_content-/Library-Fallback-Pfad bleibt
        # ungeklaimt (kleinster sinnvoller Fix, kein zusaetzlicher Nutzen
        # fuer einen bereits selbst nur als Fallback gedachten Pfad).
        self._claim_in_flight(url_hash, content_hash)
        self.logger.debug("✅ Kein Duplikat gefunden")
        return False, None, "none"

    def check_library_duplicate(self, artist: str, title: str):
        """
        🔎 Prüft direkt in der Library ob Artist/Titel bereits als Datei existiert.
        Fallback wenn der Cache-Eintrag fehlt (z.B. nach Neustart ohne register_download).
        """
        library_dir = getattr(self.config, "LIBRARY_DIR", None)
        if not library_dir:
            return None

        library_path = Path(library_dir)
        if not library_path.exists():
            return None

        normalized_artist = self._normalize_artist_for_comparison(artist)
        cleaned_title = self._clean_title_for_comparison(title, normalized_artist)
        audio_extensions = {".m4a", ".mp3", ".flac", ".ogg", ".opus", ".wav"}

        # Suche den passenden Artist-Ordner in der Library
        search_dirs = []
        try:
            for artist_dir in library_path.iterdir():
                if artist_dir.is_dir():
                    norm_dir = re.sub(r"\s+", " ", artist_dir.name.strip().lower())
                    if norm_dir == normalized_artist.lower():
                        search_dirs.append(artist_dir)
        except Exception as e:
            self.logger.warning(f"⚠️ Library-Scan Fehler: {e}")
            return None

        for search_dir in search_dirs:
            try:
                for file in search_dir.rglob("*"):
                    if file.suffix.lower() not in audio_extensions:
                        continue
                    stem = file.stem
                    # Jahr-Prefix "2025 - " entfernen
                    stem = re.sub(r"^\d{4}\s*-\s*", "", stem)
                    stem_clean = self._clean_title_for_comparison(
                        stem, normalized_artist
                    )
                    if stem_clean.lower() == cleaned_title.lower():
                        self.logger.info(
                            f"📁 Library-Duplikat: '{file.name}' "
                            f"(Artist: {artist}, Titel: {title})"
                        )
                        return file
            except Exception as e:
                self.logger.warning(f"⚠️ Fehler beim Durchsuchen von {search_dir}: {e}")

        return None

    def register_download(
        self,
        url: str,
        artist: str,
        title: str,
        file_path: Optional[Path] = None,
        metadata: Dict = None,
    ):
        # DUP-02 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md):
        # check_for_duplicates() hasht ausschliesslich normalisierte/bereinigte
        # Werte (_normalize_artist_for_comparison/_clean_title_for_comparison),
        # register_download() hashte bisher die rohen, vom Aufrufer
        # uebergebenen Werte direkt - fuer dieselbe Aufnahme konnten Check-
        # und Registrierungs-Hash dadurch strukturell auseinanderlaufen (z.B.
        # bei Artist-Suffixen wie " - Topic" oder Titel-Zusaetzen wie
        # "(Official Video)"). Fix: dieselbe Normalisierung wie beim Check
        # anwenden, bevor der Eintrag gehasht/gespeichert wird - identische
        # kanonische Repraesentation fuer beide Pfade.
        normalized_artist = self._normalize_artist_for_comparison(artist)
        cleaned_title = self._clean_title_for_comparison(title, normalized_artist)

        entry = DuplicateEntry(
            artist=normalized_artist,
            title=cleaned_title,
            url=url,
            file_path=file_path,
            download_date=datetime.now(),
            metadata_hash=self._create_metadata_hash(metadata) if metadata else None,
        )
        if file_path and file_path.exists():
            entry.file_hash = self._create_file_hash(file_path)

        self.duplicate_cache.add_entry(entry)
        self.stats["new_entries_added"] += 1
        self.logger.info(f"📝 Download registriert: {artist} - {title}")

        # DUP-05: In-Flight-Claim jetzt ueberfluessig - der permanente
        # Cache-Eintrag deckt ab sofort denselben Fall ab (der naechste
        # check_for_duplicates()-Aufruf faende ohnehin den url_duplicate/
        # content_duplicate-Treffer zuerst). Sofortige Freigabe statt auf
        # die TTL zu warten, rein aus Hygiene (kleinerer Dict, kein
        # funktionaler Unterschied).
        self._release_in_flight(
            self.duplicate_cache.get_url_hash(url),
            self.duplicate_cache.get_content_hash(normalized_artist, cleaned_title),
        )

    def _normalize_artist_for_comparison(self, artist: str) -> str:
        if not artist:
            return "Unknown"
        # P1 (docs/audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md):
        # self.artist_processor ist seit dem P1-Fix immer gesetzt (kein
        # hasattr(config, "artist_config")-Gate mehr, siehe __init__).
        # clean_artist_before_normalization() MUSS vor normalize() laufen -
        # ArtistNormalizer.normalize() entfernt Channel-Suffixe wie
        # "- Topic"/"VEVO"/"Official" nicht selbststaendig, das ist
        # exklusiv Aufgabe des vorgeschalteten Cleanings (identisch zum
        # Pfad, den ArtistProcessor.determine_best_artist() fuer die
        # Metadaten-Pipeline verwendet - beide Aufrufer nutzen jetzt
        # dieselbe kanonische Bereinigung, nicht nur denselben Normalizer).
        if self.artist_processor:
            try:
                cleaned_for_normalize = self.artist_processor.clean_artist_before_normalization(
                    artist
                )
                if cleaned_for_normalize:
                    normalized = self.artist_normalizer.normalize(cleaned_for_normalize)
                    if normalized and normalized.lower() != "unknown":
                        return normalized
            except Exception as e:
                self.logger.debug(f"⚠️ Artist-Normalisierung fehlgeschlagen: {e}")
        # Fallback (nur erreichbar, falls artist_processor fehlt oder die
        # Normalisierung oben ausnahmsweise fehlschlaegt/leer bleibt) -
        # bewusst dieselben Regeln wie clean_artist_before_normalization()
        # nachgebildet (Komma-Split + Suffix-Liste), damit auch dieser
        # Notfall-Pfad nicht hinter den P0-E-Stand zurueckfaellt.
        cleaned = artist.strip()
        if ", " in cleaned:
            main_artist = cleaned.split(", ")[0].strip()
            if len(main_artist) > 2:
                cleaned = main_artist
        for suffix in [" - Topic", " VEVO", " Official", " Music", " Records"]:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
        return cleaned if cleaned else "Unknown"

    def _clean_title_for_comparison(self, title: str, artist: str = None) -> str:
        if not title:
            return "Unknown"
        cleaned = title.strip()
        if artist and artist.lower() in cleaned.lower():
            for pattern in [
                f"{artist} - ",
                f"{artist} – ",
                f"{artist}: ",
                f"{artist} | ",
            ]:
                if cleaned.lower().startswith(pattern.lower()):
                    cleaned = cleaned[len(pattern) :].strip()
                    break

        patterns_to_remove = [
            r"\(Official.*?\)",
            r"\[.*?\]",
            # DUP-04 (docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md):
            # vorher zwingend \s+ nach "feat"/"ft" - "Featuring" und
            # "feat.Someone"/"ft.Someone" (ohne Leerzeichen) wurden dadurch
            # nicht erkannt (False Negative). Jede Alternative unten
            # konsumiert mindestens ein echtes, unterscheidendes Zeichen
            # (Punkt, "uring" oder Whitespace) - bewusst KEIN \s* anstelle
            # von \s+, da das eine Nullbreiten-Luecke oeffnen wuerde: Inhalte
            # wie "(Featherweight Mix)" muessen unangetastet bleiben (kein
            # Kollaborations-Credit, nur zufaelliges "Feat"-Praefix).
            r"\(feat(?:\.\s*|uring\s*|\s+).*?\)",
            r"\(ft(?:\.\s*|\s+).*?\)",
        ]
        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Phase 2.2 (Parität zu classification.py::normalize_title_for_identity()):
        # entfernt ein umschließendes Anführungszeichen-Paar, siehe Modul-Docstring.
        cleaned = _strip_wrapping_quote_pair(cleaned)
        return cleaned if cleaned else "Unknown"

    def _create_metadata_hash(self, metadata: Dict) -> str:
        if not metadata:
            return None
        relevant_keys = ["title", "artist", "duration", "upload_date"]
        relevant_data = {
            k: v for k, v in metadata.items() if k in relevant_keys and v is not None
        }
        metadata_string = json.dumps(relevant_data, sort_keys=True)
        return hashlib.md5(metadata_string.encode("utf-8")).hexdigest()

    def _create_file_hash(self, file_path: Path) -> str:
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                chunk = f.read(65536)
                if chunk:
                    hash_md5.update(chunk)
                f.seek(-65536, 2)
                chunk = f.read(65536)
                if chunk:
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            self.logger.warning(f"⚠️ Fehler beim Erstellen des Datei-Hash: {e}")
            return None

    def get_statistics(self) -> Dict:
        total_checks = max(self.stats["total_checks"], 1)
        duplicates_found = (
            self.stats["url_duplicates_found"] + self.stats["content_duplicates_found"]
        )
        return {
            **self.stats,
            "url_cache_size": len(self.duplicate_cache.url_cache),
            "content_cache_size": len(self.duplicate_cache.content_cache),
            "duplicate_rate": (duplicates_found / total_checks) * 100,
            "savings_percentage": (self.stats["duplicates_skipped"] / total_checks)
            * 100,
        }

    def cleanup_cache(self, days_old: int = 30):
        self.duplicate_cache.cleanup_old_entries(days_old)

    def invalidate_entry(self, url: str = None, artist: str = None, title: str = None):
        removed_count = 0
        if url:
            url_hash = self.duplicate_cache.get_url_hash(url)
            if url_hash in self.duplicate_cache.url_cache:
                del self.duplicate_cache.url_cache[url_hash]
                removed_count += 1
        if artist and title:
            content_hash = self.duplicate_cache.get_content_hash(artist, title)
            if content_hash in self.duplicate_cache.content_cache:
                del self.duplicate_cache.content_cache[content_hash]
                removed_count += 1
        if removed_count > 0:
            self.duplicate_cache._save_caches()
            self.logger.info(f"🗑️ {removed_count} Duplikat-Einträge invalidiert")
