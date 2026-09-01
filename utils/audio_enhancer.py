"""
Audio Enhancer Service für den Bot
Loudness-Normalisierung (FFmpeg loudnorm) für den Download-Workflow.

ARCH-017 Phase 2 (docs/archive/arch/MusicBot_ARCH-017_Download_Audio_Enhancement_Characterization.md):
die zuvor hier enthaltenen ReplayGain-, Künstlerbild- und MusicBrainz-ID-
Fähigkeiten wurden entfernt, da sie im gesamten Repository nachweislich
keinen produktiven Aufrufer besaßen (nie instanziiert, 0 Aufrufe außerhalb
dieser Datei) und teilweise bereits durch aktiv genutzte Komponenten
(services/clients/musicbrainz_client.py, services/metadata/cover_processor.py)
abgedeckt waren. Erhalten bleibt ausschließlich die tatsächlich aktiv
genutzte Loudness-Normalisierung.

2026-09-Fix (entdeckt während der Entwicklung von
scripts/normalize_test_library_loudness.py, siehe dortiger Docstring):
normalize_loudness() re-encodete zuvor JEDE Datei mit eingebettetem
Cover fehlerhaft - der Cover-Bildstream (covr-Atom, von ffmpeg als
"attached pic" demuxt) wurde ohne Stream-Mapping mitverarbeitet, der
FFmpeg-Encode-Versuch schlug fehl und hinterließ eine leere Zieldatei,
die trotzdem als Erfolg gemeldet wurde (weder Return-Code noch
Dateigröße wurden geprüft). In der Live-Downloadpipeline bisher
folgenlos, da normalize_loudness() dort vor dem Cover-Embedding läuft -
für Reprocessing bereits getaggter Dateien war der Defekt jedoch akut
(Live-Reproduktion: 8/8 echte Testbibliotheks-Dateien mit Cover
betroffen). Fix: explizites Stream-Mapping (Cover per -c:v copy
unverändert übernehmen statt neu zu kodieren) plus Return-Code-/
Dateigrößen-Prüfung vor dem Ersetzen der Originaldatei.

BEKANNTER, SEPARATER, NICHT BEHOBENER DEFEKT (bei der Verifikation des
obigen Fixes live entdeckt, auf ausdrücklichen Wunsch NUR dokumentiert):
normalize_loudness() setzt weiterhin kein "-map_metadata 0", d.h. welche
Metadaten-Atome den FFmpeg-Re-Encode überleben, ist reines
FFmpeg-Standardverhalten. Live reproduziert (echte Testbibliothek,
8 Dateien): das freeform-Atom "----:com.apple.iTunes:GENRE" (Komma-
separiert) ging bei ALLEN 8 Dateien vollständig verloren - sein Wert
überschrieb dabei sogar den eigentlichen "©gen"-Tag. Bei einer Datei mit
gesetzten MusicBrainz-IDs gingen zusätzlich "----:com.apple.iTunes:
MusicBrainz Artist Id" und "...Release Group Id" komplett verloren. In
der Live-Downloadpipeline bisher folgenlos (gleicher Grund wie beim
Cover-Defekt: normalize_loudness() läuft dort vor dem Tag-Schreiben),
für Reprocessing bereits getaggter Dateien mit MusicBrainz-IDs/Genre-
Freeform-Tags jedoch real relevant. scripts/normalize_test_library_
loudness.py deckt das über seinen Metadaten-Diff auf (Status FAILED
statt stillschweigender Datenverlust), behebt es aber nicht.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioEnhancer:
    """Loudness-Normalisierung für heruntergeladene Audiodateien."""

    # Ziel-LUFS Werte für verschiedene Content-Typen
    TARGET_LUFS = {
        'music': -16.0,      # Standard für Musik (Spotify, Apple Music)
        'podcast': -18.0,    # Podcasts (weniger komprimiert)
        'audiobook': -20.0,  # Hörbücher
        'default': -16.0
    }

    @classmethod
    def get_target_lufs(cls, content_type: str = 'music') -> float:
        """
        Gibt den Ziel-LUFS Wert für einen Content-Typ zurück

        Args:
            content_type: 'music', 'podcast', 'audiobook' oder 'default'

        Returns:
            Ziel-LUFS Wert als Float
        """
        return cls.TARGET_LUFS.get(content_type.lower(), cls.TARGET_LUFS['default'])

    @staticmethod
    def normalize_loudness(filepath: str, target_lufs: float = -16.0) -> bool:
        """
        Normalisiert die Lautheit einer Audiodatei mit ffmpeg loudnorm

        Args:
            filepath: Pfad zur Audiodatei
            target_lufs: Ziel-LUFS Wert (z.B. -16 für Musik, -18 für Podcasts)

        Returns:
            True bei Erfolg, False bei Fehler
        """
        path = Path(filepath)

        if not path.exists():
            logger.error(f"Datei nicht gefunden: {path}")
            return False

        # Nur für unterstützte Formate
        if path.suffix.lower() not in ('.m4a', '.mp4', '.mp3'):
            logger.debug(f"Überspringe Lautheits-Normalisierung für {path.suffix}")
            return True

        # Temporäre Datei für die Verarbeitung
        temp_path = path.parent / f"temp_loudnorm_{path.name}"

        try:
            # loudnorm Filter mit Messung und Anwendung in einem Durchlauf
            # Zuerst die Datei analysieren, dann die Gains anwenden
            cmd_analyze = [
                'ffmpeg', '-i', str(path),
                '-af', f'loudnorm=I={target_lufs}:LRA=11:TP=-1.5:print_format=json',
                '-f', 'null', '-'
            ]

            result = subprocess.run(cmd_analyze, capture_output=True, text=True, timeout=60)

            # JSON Output parsen für die Messwerte
            import json
            import re

            # Extrahiere JSON aus der Ausgabe
            json_match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', result.stderr)
            if json_match:
                analysis = json.loads(json_match.group())

                # Zweiter Durchlauf mit den gemessenen Werten
                input_i = analysis.get('input_i', target_lufs)
                input_tp = analysis.get('input_tp', -1.5)
                input_lra = analysis.get('input_lra', 11)
                input_thresh = analysis.get('input_thresh', -33)
                target_offset = target_lufs - float(input_i)

                # loudnorm mit korrigierten Werten
                #
                # -map 0:a -map "0:v?" -c:v copy (2026-09-Fix, entdeckt
                # waehrend der Entwicklung von
                # scripts/normalize_test_library_loudness.py): ohne
                # explizites Stream-Mapping behandelt der MOV/MP4-Demuxer
                # ein eingebettetes Cover (covr-Atom) als angehaengten
                # Bildstream ("attached pic", Codec mjpeg). Ohne -map versuchte ffmpeg zuvor,
                # diesen Stream als regulaeres Video mit dem Standard-
                # Videocodec (libx264) in den ipod/mp4-Container zu
                # re-encodieren - das schlaegt fehl ("Could not find tag
                # for codec h264..."), liess aber bereits eine leere
                # Zieldatei zurueck (siehe Return-Code-Pruefung unten).
                # -map 0:a waehlt ausschliesslich den Audiostream fuer den
                # loudnorm-Filter, -map "0:v?" uebernimmt einen eventuell
                # vorhandenen Bildstream OPTIONAL (kein Fehler ohne Cover)
                # unveraendert per -c:v copy statt ihn neu zu kodieren -
                # das Cover bleibt dadurch byteidentisch erhalten.
                # -disposition:v:0 attached_pic haelt die Kennzeichnung als
                # Cover (nicht als regulaere Videospur) explizit bei.
                cmd_apply = [
                    'ffmpeg', '-i', str(path),
                    '-map', '0:a', '-map', '0:v?',
                    '-af', f'loudnorm=I={target_lufs}:LRA=11:TP=-1.5:measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:measured_thresh={input_thresh}:linear=true:print_format=json',
                    '-c:a', 'aac', '-b:a', '192k',
                    '-c:v', 'copy', '-disposition:v:0', 'attached_pic',
                    '-y', str(temp_path)
                ]

                apply_result = subprocess.run(cmd_apply, capture_output=True, text=True, timeout=120)

                # Erfolg nur bei echtem ffmpeg-Erfolg (Return-Code 0) UND
                # nicht-leerer Zieldatei - 2026-09-Fix: zuvor wurde jede
                # Existenz von temp_path als Erfolg gewertet, auch wenn
                # ffmpeg fehlgeschlagen war und nur eine leere Datei
                # zurueckliess (empirisch reproduziert, siehe oben) - das
                # ersetzte die gueltige Originaldatei stillschweigend
                # durch eine leere.
                if (
                    apply_result.returncode == 0
                    and temp_path.exists()
                    and temp_path.stat().st_size > 0
                ):
                    temp_path.replace(path)
                    logger.info(f"🔊 Lautheit normalisiert: {target_lufs:+5.1f} LUFS (Delta: {target_offset:+.1f})")
                    return True
                else:
                    logger.error(
                        f"ffmpeg-Anwendung fehlgeschlagen (returncode="
                        f"{apply_result.returncode}) fuer {path} - Original bleibt "
                        f"unveraendert: {apply_result.stderr[-500:]}"
                    )

            # Fallback: Einfache Normalisierung ohne Analyse
            cmd_fallback = [
                'ffmpeg', '-i', str(path),
                '-map', '0:a', '-map', '0:v?',
                '-af', f'loudnorm=I={target_lufs}:TP=-1.5:LRA=11',
                '-c:a', 'aac', '-b:a', '192k',
                '-c:v', 'copy', '-disposition:v:0', 'attached_pic',
                '-y', str(temp_path)
            ]

            fallback_result = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=120)

            if (
                fallback_result.returncode == 0
                and temp_path.exists()
                and temp_path.stat().st_size > 0
            ):
                temp_path.replace(path)
                logger.info(f"🔊 Lautheit normalisiert (Fallback): {target_lufs} LUFS")
                return True
            else:
                logger.error(
                    f"ffmpeg-Fallback fehlgeschlagen (returncode="
                    f"{fallback_result.returncode}) fuer {path} - Original bleibt "
                    f"unveraendert: {fallback_result.stderr[-500:]}"
                )

        except subprocess.TimeoutExpired:
            logger.error(f"ffmpeg Timeout bei Lautheits-Normalisierung für {path}")
        except Exception as e:
            logger.error(f"Fehler bei Lautheits-Normalisierung für {path}: {e}")
        finally:
            # Aufräumen
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass

        return False
