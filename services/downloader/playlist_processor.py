# services/downloader/utils/playlist_processor.py (KORRIGIERTE VERSION)
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from collections import Counter

# NEU: Erweiterte Imports für Normalisierung und Parsing
from utils.artist_map import ArtistNormalizer, ArtistConfig
from utils.youtube_parser import parse_youtube_title


class PlaylistProcessor:
    """Erweiterte Playlist-Verarbeitung mit Enhanced Components und Artist-Override-Priorisierung"""

    def __init__(self, logger_factory: Optional[Callable] = None, config=None):
        """
        Initialisiert den Prozessor und die erweiterten Komponenten.

        `config` ist optional injizierbar (ARCH-003, P-8) - ohne Angabe wird
        wie bisher die globale `config.Config` selbst geladen, damit sich
        das Default-Verhalten für bestehende Aufrufer (z.B.
        `download_utils.py`, das PlaylistProcessor ohne config konstruiert)
        nicht ändert.
        """
        # ➡️ Custom logger integration mit Dependency Injection
        self.logger = (
            logger_factory("PlaylistProcessor")
            if logger_factory
            else self._get_default_logger()
        )

        self.dominant_artist_threshold = 0.6
        self.logger_factory = (
            logger_factory  # Speichere die Factory für Unterkomponenten
        )

        # 🆕 NEU: Enhanced Components laden
        try:
            if config is None:
                # Fallback: globale Konfiguration selbst laden (unverändertes
                # Default-Verhalten, falls kein config injiziert wurde).
                from config import Config

                config = Config()

            # ✅ FIX: Entferne logger_factory Parameter - ArtistNormalizer nutzt jetzt get_module_logger
            self.artist_normalizer = ArtistNormalizer(
                ArtistConfig(
                    library_dir=getattr(config, "LIBRARY_DIR", Path("./music_library")),
                    override_file=getattr(
                        config, "ARTIST_OVERRIDE_FILE", Path("./artist_overrides.json")
                    ),
                )
                # KEIN logger_factory Parameter mehr!
            )

            self.enhanced_processing_enabled = getattr(
                config, "ENHANCED_METADATA_PROCESSING", True
            )
            if self.enhanced_processing_enabled:
                self.logger.info("✅ Enhanced Playlist Processing aktiviert")
            else:
                self.logger.info(
                    "ℹ️ Enhanced Playlist Processing ist per Konfiguration deaktiviert."
                )

        except (ImportError, Exception) as e:
            self.logger.warning(
                f"⚠️ Enhanced Components nicht verfügbar, fahre im Standard-Modus fort: {e}"
            )
            self.artist_normalizer = None
            self.enhanced_processing_enabled = False

    def _get_default_logger(self):
        """Fallback-Logger falls keine Factory übergeben wurde"""
        import logging

        logger = logging.getLogger("PlaylistProcessor")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def some_method(self):
        """Beispielmethode für die Verwendung von youtube_parser"""
        track_title = "Artist - Song Title"
        parsed = parse_youtube_title(
            track_title,
            logger_factory=self.logger_factory,  # ✅ Korrekt: Logger-Factory übergeben
        )
        return parsed

    def _log_playlist_info(self, message: str):
        """Info-Logging für Playlist-Verarbeitung"""
        self.logger.info(message)

    def _log_playlist_debug(self, message: str):
        """Debug-Logging für Playlist-Verarbeitung"""
        self.logger.debug(message)

    def _log_playlist_warning(self, message: str):
        """Warning-Logging für Playlist-Verarbeitung"""
        self.logger.warning(message)

    def _log_playlist_error(self, message: str):
        """Error-Logging für Playlist-Verarbeitung"""
        self.logger.error(message)

    def determine_dominant_artist(
        self, playlist_tracks: List[Dict[str, Any]]
    ) -> Optional[str]:
        """👑 ERWEITERTE dominante Artist-Erkennung mit Override-Priorisierung."""
        self._log_playlist_info(
            "🔍 📊 Starte ERWEITERTE Playlist-Analyse für dominanten Artist..."
        )

        if not playlist_tracks:
            self._log_playlist_warning("⚠️ Keine Tracks in Playlist gefunden")
            return None

        artist_counts = Counter()
        collaboration_artists = {}  # Speichert alle Artists aus Kollaborationen
        total_tracks = len(playlist_tracks)

        for idx, track in enumerate(playlist_tracks, 1):
            # 🆕 ERWEITERTE Artist-Extraktion
            potential_artists = [
                track.get("artist"),
                track.get("uploader"),
            ]

            # YouTube-Parser Integration für zusätzliche Kandidaten
            if self.enhanced_processing_enabled and track.get("title"):
                try:
                    parsed = parse_youtube_title(track["title"])
                    if parsed.get("artist"):
                        potential_artists.insert(1, parsed["artist"])  # Hohe Priorität
                        self._log_playlist_debug(
                            f"   🔍 YouTube-Parser: '{track['title']}' → Artist: '{parsed['artist']}'"
                        )
                except Exception as e:
                    self._log_playlist_debug(f"   ⚠️ YouTube-Parser Fehler: {e}")

            # Artist-Normalisierung anwenden
            found_artist = False
            for artist in potential_artists:
                if artist and len(str(artist).strip()) > 1:
                    # 🎯 NEUE LOGIK: Prüfe auf Kollaborationen und extrahiere alle Artists
                    collaboration_parts = self._extract_collaboration_artists(
                        str(artist)
                    )

                    if len(collaboration_parts) > 1:
                        self._log_playlist_debug(
                            f"   🤝 Kollaboration erkannt: '{artist}' → {collaboration_parts}"
                        )
                        # Speichere alle Kollaborationspartner für spätere Analyse
                        for collab_artist in collaboration_parts:
                            if collab_artist not in collaboration_artists:
                                collaboration_artists[collab_artist] = []
                            collaboration_artists[collab_artist].append(idx)

                    # Bevorzugter Weg: Normalisierung
                    if self.enhanced_processing_enabled and self.artist_normalizer:
                        try:
                            normalized_artist = self._normalize_with_override_priority(
                                str(artist).strip()
                            )
                            if (
                                normalized_artist
                                and normalized_artist.lower() != "unknown"
                            ):
                                artist_counts[normalized_artist] += 1
                                self._log_playlist_debug(
                                    f"   🎤 Track {idx:02d}: '{artist}' → '{normalized_artist}' erkannt"
                                )
                                found_artist = True
                                break
                        except Exception as e:
                            self._log_playlist_debug(
                                f"   ⚠️ Normalisierung fehlgeschlagen für '{artist}': {e}"
                            )

                    # Fallback ohne Normalisierung, falls deaktiviert oder fehlgeschlagen
                    if not found_artist:
                        cleaned_artist = self._clean_artist_name(str(artist))
                        if cleaned_artist and len(cleaned_artist) > 1:
                            artist_counts[cleaned_artist] += 1
                            self._log_playlist_debug(
                                f"   🎤 Track {idx:02d}: Artist '{cleaned_artist}' erkannt (ohne Normalisierung)"
                            )
                            break

        if not artist_counts:
            self._log_playlist_warning("⚠️ Keine gültigen Artists in Playlist gefunden")
            return None

        # 🎯 NEUE OVERRIDE-PRIORISIERUNG: Prüfe ob ein Artist aus den Overrides häufig vorkommt
        dominant_artist_from_overrides = self._find_dominant_override_artist(
            artist_counts, collaboration_artists
        )

        if dominant_artist_from_overrides:
            self._log_playlist_info(
                f"⭐ Override-basierter dominanter Artist erkannt: '{dominant_artist_from_overrides}'"
            )
            return dominant_artist_from_overrides

        # Fallback: Standard-Logik
        most_common_artist, count = artist_counts.most_common(1)[0]
        dominance_ratio = count / total_tracks

        self._log_playlist_info(f"📈 ERWEITERTE Artist-Statistik:")
        for artist, cnt in artist_counts.most_common(5):
            percentage = (cnt / total_tracks) * 100
            self._log_playlist_info(
                f"   🎤 {artist}: {cnt}/{total_tracks} ({percentage:.1f}%)"
            )

        if dominance_ratio >= self.dominant_artist_threshold:
            self._log_playlist_info(
                f"✅ 👑 ENHANCED: Dominanter Artist erkannt: '{most_common_artist}' ({dominance_ratio:.1%})"
            )
            return most_common_artist
        else:
            self._log_playlist_info(
                f"❌ Kein dominanter Artist gefunden. Höchster: '{most_common_artist}' ({dominance_ratio:.1%})"
            )
            return None

    def _extract_collaboration_artists(self, artist_string: str) -> List[str]:
        """🤝 Extrahiert alle Artists aus einem Kollaborations-String."""
        if not artist_string:
            return []

        # Verschiedene Trennzeichen für Kollaborationen
        separators = [",", " x ", " X ", " & ", " and ", " feat. ", " ft. ", " with "]

        # Normalisiere alle Trennzeichen zu Kommas
        normalized = artist_string
        for sep in separators:
            normalized = normalized.replace(sep, ",")

        # Splitte und bereinige
        artists = [artist.strip() for artist in normalized.split(",") if artist.strip()]

        return artists

    def _normalize_with_override_priority(self, artist_string: str) -> str:
        """🎯 Normalisiert Artist-String mit Priorität auf Override-bekannte Artists."""
        if not self.artist_normalizer:
            return self._clean_artist_name(artist_string)

        # 1. Prüfe zuerst, ob der gesamte String in Overrides ist
        try:
            normalized = self.artist_normalizer.normalize(artist_string)
            if normalized and normalized.lower() != "unknown":
                return normalized
        except:
            pass

        # 2. Bei Kollaborationen: Prüfe jeden Artist einzeln und wähle den aus Overrides
        collaboration_artists = self._extract_collaboration_artists(artist_string)

        if len(collaboration_artists) > 1:
            self._log_playlist_debug(
                f"   🔍 Analysiere Kollaboration: {collaboration_artists}"
            )

            # Prüfe welche Artists in den Overrides/Library bekannt sind
            known_artists = []
            for artist in collaboration_artists:
                try:
                    normalized = self.artist_normalizer.normalize(artist.strip())
                    # Prüfe ob Artist in Library oder Overrides bekannt ist
                    if self._is_artist_known(artist.strip(), normalized):
                        known_artists.append((artist.strip(), normalized))
                        self._log_playlist_debug(
                            f"     ✅ Bekannter Artist gefunden: '{artist}' → '{normalized}'"
                        )
                except:
                    continue

            # Wenn bekannte Artists gefunden wurden, nehme den ersten
            if known_artists:
                chosen_artist, normalized_name = known_artists[0]
                self._log_playlist_info(
                    f"🎯 Override-Priority: '{artist_string}' → '{normalized_name}' (bekannt aus Library/Overrides)"
                )
                return normalized_name

            # Fallback: Ersten Artist der Kollaboration normalisieren
            try:
                first_artist = collaboration_artists[0]
                normalized = self.artist_normalizer.normalize(first_artist)
                if normalized and normalized.lower() != "unknown":
                    self._log_playlist_debug(
                        f"   📝 Kollaboration Fallback: '{artist_string}' → '{normalized}' (erster Artist)"
                    )
                    return normalized
            except:
                pass

        # 3. Standard-Normalisierung als letzter Fallback
        return self._clean_artist_name(artist_string)

    def _is_artist_known(self, raw_artist: str, normalized_artist: str) -> bool:
        """🔍 Prüft ob ein Artist in der Library oder den Overrides bekannt ist."""
        if not self.artist_normalizer:
            return False

        try:
            # Prüfe Library Artists
            if normalized_artist in self.artist_normalizer.library_artists:
                return True

            # Prüfe Overrides
            if raw_artist.lower().strip() in [
                k.lower() for k in self.artist_normalizer.overrides.keys()
            ]:
                return True

            if normalized_artist in self.artist_normalizer.overrides.values():
                return True

        except Exception as e:
            self._log_playlist_debug(
                f"   ⚠️ Fehler bei Artist-Bekanntheits-Prüfung: {e}"
            )

        return False

    def _find_dominant_override_artist(
        self, artist_counts: Counter, collaboration_artists: Dict
    ) -> Optional[str]:
        """⭐ Findet dominanten Artist basierend auf Override-Präferenz."""
        if not self.artist_normalizer or not artist_counts:
            return None

        # Sammle alle Artists die in Overrides/Library bekannt sind
        known_artist_scores = {}

        for artist, count in artist_counts.items():
            if self._is_artist_known(artist, artist):
                # Bonuspunkte für bekannte Artists
                bonus_score = count * 1.5  # 50% Bonus für bekannte Artists
                known_artist_scores[artist] = bonus_score
                self._log_playlist_debug(
                    f"   ⭐ Bekannter Artist gefunden: '{artist}' (Score: {bonus_score})"
                )

        if not known_artist_scores:
            return None

        # Finde den bekannten Artist mit der höchsten Score
        best_known_artist = max(known_artist_scores, key=known_artist_scores.get)
        best_score = known_artist_scores[best_known_artist]
        original_count = artist_counts[best_known_artist]

        # Prüfe ob der bekannte Artist mindestens 30% der Tracks hat
        total_tracks = sum(artist_counts.values())
        if original_count / total_tracks >= 0.3:
            self._log_playlist_info(
                f"🎯 Override-Priority aktiviert: '{best_known_artist}' (bekannt, {original_count} Tracks)"
            )
            return best_known_artist

        return None

    def _clean_artist_name(self, artist: str) -> str:
        """🧹 Bereinigt Artist-Namen von häufigen Zusätzen (Fallback-Methode)."""
        if not artist:
            return ""
        cleaned = artist.strip()
        cleanup_patterns = [
            r"\s*-\s*Topic$",
            r"\s*VEVO$",
            r"\s*Official$",
            r"\s*Music$",
            r"\s*Records$",
            r"^\s*Various\s*Artists?\s*$",
        ]
        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", cleaned).strip()

    def clean_track_title(self, title: str, artist: str = None) -> str:
        """✨ ERWEITERTE Titel-Bereinigung mit YouTube-Parser Integration."""
        self._log_playlist_debug(f"🧽 Starte ERWEITERTE Titel-Bereinigung: '{title}'")

        if not title:
            return "Unbekannter Titel"

        original_title = title.strip()

        # 1. Bevorzugter Weg: YouTube-Parser für intelligente Titel-Extraktion
        if self.enhanced_processing_enabled:
            try:
                parsed = parse_youtube_title(title)
                parsed_title = parsed.get("song_title", "")

                if parsed_title and len(parsed_title.strip()) > 2:
                    cleaned_parsed = self._apply_additional_cleanup(parsed_title)
                    if cleaned_parsed and len(cleaned_parsed.strip()) > 2:
                        self._log_playlist_info(
                            f"✨ YouTube-Parser Titel: '{original_title}' → '{cleaned_parsed}'"
                        )
                        return cleaned_parsed
            except Exception as e:
                self._log_playlist_debug(
                    f"⚠️ YouTube-Parser Fehler bei Titel-Bereinigung: {e}"
                )

        # 2. Fallback: Ursprüngliche Bereinigungslogik (erweitert)
        cleaned_title = original_title

        # Artist-Präfix entfernen
        if artist:
            artist_patterns = [
                rf"^{re.escape(artist)}\s*[-—–:]\s*",
                rf"^{re.escape(artist)}\s*\|\s*",
            ]
            for pattern in artist_patterns:
                if re.match(pattern, cleaned_title, re.IGNORECASE):
                    cleaned_title = re.sub(
                        pattern, "", cleaned_title, flags=re.IGNORECASE
                    )
                    self._log_playlist_debug(
                        f"   ✂️ Artist-Präfix entfernt: '{artist}'"
                    )
                    break

        # Erweiterte Bereinigungspatterns
        enhanced_cleanup_patterns = [
            r'\(Aus ["""].*?["""]\)',
            r"\(Live.*?bei.*?\)",
            r"\(.*?Session.*?\)",
            r"\(feat\.?\s+.*?\)",
            r"\(ft\.?\s+.*?\)",
            r"\(with.*?\)",
            r"\[.*?\]",
            r"\(Official.*?\)",
            r"\(.*?Version\)",
            r"\(.*?Mix\)",
            r"\(Live.*?\)",
            r"\(Remix\)",
            r"\(Remaster.*?\)",
            r"\s*-\s*Official.*",
            r"\s*\|\s*Official.*",
            r"\s*-\s*Topic$",
        ]
        for pattern in enhanced_cleanup_patterns:
            cleaned_title = re.sub(pattern, "", cleaned_title, flags=re.IGNORECASE)

        cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip(" -—–")

        if not cleaned_title or len(cleaned_title) < 2:
            self._log_playlist_warning(
                f"⚠️ Titel nach ENHANCED Bereinigung zu kurz, verwende Original"
            )
            return original_title

        if cleaned_title != original_title:
            self._log_playlist_info(
                f"✨ ENHANCED Titel bereinigt (Fallback): '{original_title}' → '{cleaned_title}'"
            )

        return cleaned_title

    def _apply_additional_cleanup(self, title: str) -> str:
        """🧹 Zusätzliche, sanfte Bereinigung für bereits durch den Parser extrahierte Titel."""
        if not title:
            return ""
        cleaned = title
        additional_patterns = [
            r"\s*(official|music|lyric|video|audio)\s*",
            r"\s*\(\s*\)\s*",
            r"\s*\[\s*\]\s*",
        ]
        for pattern in additional_patterns:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", cleaned).strip()

    def process_playlist_metadata(
        self, playlist_tracks: List[Dict[str, Any]], playlist_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        🎯 Hauptfunktion zur Playlist-Verarbeitung, die die erweiterten Methoden nutzt.
        """
        self._log_playlist_info("🎼 📋 Starte Playlist-Metadaten-Verarbeitung...")

        dominant_artist = self.determine_dominant_artist(playlist_tracks)

        processed_tracks = []
        for idx, track in enumerate(playlist_tracks, 1):
            self._log_playlist_debug(
                f"🎵 Verarbeite Track {idx:02d}/{len(playlist_tracks)}"
            )

            # Artist aus dem Track extrahieren und bereinigen (wird als Fallback und für Titel-Bereinigung benötigt)
            raw_artist = track.get("artist") or track.get(
                "uploader", "Unbekannter Künstler"
            )

            # Finalen Künstler für den Track bestimmen
            track_artist = dominant_artist or self._clean_artist_name(raw_artist)

            original_title = track.get("title", "Unbekannter Titel")
            cleaned_title = self.clean_track_title(original_title, track_artist)

            processed_track = track.copy()
            processed_track.update(
                {
                    "artist": track_artist,
                    "title": cleaned_title,
                    # ✅ FIX: Unbereinigten yt-dlp-Originaltitel aufbewahren.
                    #
                    # Problem ohne diesen Fix:
                    #   Der MetadataProcessor bekommt nur "Do Anything For You" statt
                    #   "Gio Mee – Do Anything For You". Damit kann der YouTube-Parser
                    #   keinen Artist extrahieren und fällt auf den Channel-Namen zurück
                    #   → "Deep Territory - Do Anything For You" statt "Gio Mee - ...".
                    #
                    # Lösung:
                    #   original_youtube_title wird in _process_track_metadata_enhanced
                    #   als Eingabe für den YouTube-Parser im MetadataProcessor genutzt.
                    "original_youtube_title": original_title,
                    "track_number": idx,
                    "album": playlist_info.get("title", "Playlist"),
                    "album_artist": dominant_artist or "Various Artists",
                    "playlist_position": idx,
                }
            )

            processed_tracks.append(processed_track)
            self._log_playlist_debug(
                f"   ✅ Track verarbeitet: '{track_artist} - {cleaned_title}'"
            )

        playlist_metadata = {
            "tracks": processed_tracks,
            "dominant_artist": dominant_artist,
            "album": playlist_info.get("title", "Playlist"),
            "album_artist": dominant_artist or "Various Artists",
            "track_count": len(processed_tracks),
            "year": self._extract_year_from_playlist(playlist_info),
            "has_dominant_artist": dominant_artist is not None,
        }

        self._log_playlist_info(f"🎉 Playlist-Verarbeitung abgeschlossen:")
        self._log_playlist_info(f"   💿 Album: '{playlist_metadata['album']}'")
        self._log_playlist_info(
            f"   👑 Dominanter Artist: {dominant_artist or 'Nicht erkannt'}"
        )
        self._log_playlist_info(f"   🎵 Tracks: {len(processed_tracks)}")

        return playlist_metadata

    def _extract_year_from_playlist(
        self, playlist_info: Dict[str, Any]
    ) -> Optional[int]:
        """📅 Extrahiert das wahrscheinlichste Jahr aus den Playlist-Informationen."""
        # Freitext-Quellen (Titel/Beschreibung): Jahreszahl kann irgendwo im
        # Text stehen, Regex-Suche mit Wortgrenzen ist hier korrekt.
        text_sources = [playlist_info.get("title"), playlist_info.get("description")]
        for source in text_sources:
            if source:
                # Bevorzugt Jahreszahlen zwischen 1950 und 2030
                year_match = re.search(r"\b(19[5-9]\d|20[0-2]\d)\b", str(source))
                if year_match:
                    year = int(year_match.group())
                    self._log_playlist_debug(
                        f"📅 Jahr {year} aus '{str(source)[:30]}...' gefunden"
                    )
                    return year

        # BUG-012 (analog BUG-010 in YearResolver): upload_date/release_date
        # liegen im yt-dlp-Standardformat YYYYMMDD vor - durchgehende
        # Ziffernfolge ohne Trennzeichen. Die \b-Wortgrenze der obigen
        # Regex existiert dort NIE (Jahr wird direkt von weiteren Ziffern
        # gefolgt), diese Quellen lieferten dadurch bisher IMMER None.
        # Fix: direktes Slicing statt Wortgrenzen-Regex.
        date_sources = [
            playlist_info.get("upload_date"),
            playlist_info.get("release_date"),
        ]
        for source in date_sources:
            if source and len(str(source)) >= 4:
                try:
                    year = int(str(source)[:4])
                    if 1950 <= year <= 2029:
                        self._log_playlist_debug(
                            f"📅 Jahr {year} aus '{str(source)[:30]}...' gefunden"
                        )
                        return year
                except (ValueError, TypeError):
                    pass

        return None
