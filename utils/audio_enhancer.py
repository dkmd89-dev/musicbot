"""
Audio Enhancer Service für den Bot
Loudness-Normalisierung (FFmpeg loudnorm) für den Download-Workflow.

ARCH-017 Phase 2 (docs/MusicBot_ARCH-017_Download_Audio_Enhancement_Characterization.md):
die zuvor hier enthaltenen ReplayGain-, Künstlerbild- und MusicBrainz-ID-
Fähigkeiten wurden entfernt, da sie im gesamten Repository nachweislich
keinen produktiven Aufrufer besaßen (nie instanziiert, 0 Aufrufe außerhalb
dieser Datei) und teilweise bereits durch aktiv genutzte Komponenten
(services/clients/musicbrainz_client.py, services/metadata/cover_processor.py)
abgedeckt waren. Erhalten bleibt ausschließlich die tatsächlich aktiv
genutzte Loudness-Normalisierung.
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
                cmd_apply = [
                    'ffmpeg', '-i', str(path),
                    '-af', f'loudnorm=I={target_lufs}:LRA=11:TP=-1.5:measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:measured_thresh={input_thresh}:linear=true:print_format=json',
                    '-c:a', 'aac', '-b:a', '192k',
                    '-y', str(temp_path)
                ]

                subprocess.run(cmd_apply, capture_output=True, text=True, timeout=120)

                # Ersetze Original mit normalisierter Version
                if temp_path.exists():
                    temp_path.replace(path)
                    logger.info(f"🔊 Lautheit normalisiert: {target_lufs:+5.1f} LUFS (Delta: {target_offset:+.1f})")
                    return True

            # Fallback: Einfache Normalisierung ohne Analyse
            cmd_fallback = [
                'ffmpeg', '-i', str(path),
                '-af', f'loudnorm=I={target_lufs}:TP=-1.5:LRA=11',
                '-c:a', 'aac', '-b:a', '192k',
                '-y', str(temp_path)
            ]

            subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=120)

            if temp_path.exists():
                temp_path.replace(path)
                logger.info(f"🔊 Lautheit normalisiert (Fallback): {target_lufs} LUFS")
                return True

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
