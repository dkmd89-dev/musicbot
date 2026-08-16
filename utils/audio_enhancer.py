"""
Audio Enhancer Service für den Bot
Integriert ReplayGain, Künstlerbilder und MusicBrainz IDs in den Download-Workflow
"""

import os
import logging
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests
from mutagen.mp4 import MP4
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class EnhancementResult:
    """Ergebnis der Audio-Verbesserung"""
    success: bool
    file: str
    replaygain_gain: Optional[float] = None
    replaygain_peak: Optional[float] = None
    artist_image: Optional[str] = None
    musicbrainz_recording_id: Optional[str] = None
    musicbrainz_artist_id: Optional[str] = None
    musicbrainz_release_id: Optional[str] = None
    isrc: Optional[str] = None
    error: Optional[str] = None


class AudioEnhancer:
    """Hauptservice für Audio-Verbesserungen"""
    
    # Ziel-LUFS Werte für verschiedene Content-Typen
    TARGET_LUFS = {
        'music': -16.0,      # Standard für Musik (Spotify, Apple Music)
        'podcast': -18.0,    # Podcasts (weniger komprimiert)
        'audiobook': -20.0,  # Hörbücher
        'default': -16.0
    }
    
    def __init__(self, bot_instance=None):
        self.bot = bot_instance
        self.base_dir = Path(__file__).parent.parent
        
        # Verzeichnisse an deine Struktur anpassen
        self.artist_images_dir = self.base_dir / "data" / "artist_images"
        self.cache_dir = self.base_dir / "cache" / "audio_enhancer_cache"
        
        self.artist_images_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Session für Connection Pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'TelegramMusicBot/2.0 (https://github.com/yourbot)'
        })
        
        # Last.fm API Key aus Config (falls vorhanden)
        if hasattr(self.bot, 'config'):
            self.lastfm_api_key = getattr(self.bot.config, 'LASTFM_API_KEY', os.getenv('LASTFM_API_KEY', ''))
        else:
            self.lastfm_api_key = os.getenv('LASTFM_API_KEY', '')
    
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
    
    # ==================== 1. REPLAYGAIN ====================
    
    def calculate_replaygain(self, filepath: Path) -> Optional[Tuple[float, float]]:
        """
        Berechnet ReplayGain mit ffmpeg EBU R128
        Ziel: -16 LUFS für AAC (optimal für mobile Player)
        """
        if not filepath.exists():
            logger.error(f"Datei nicht gefunden: {filepath}")
            return None
            
        try:
            cmd = [
                'ffmpeg', '-i', str(filepath),
                '-af', 'ebur128=peak=true',
                '-f', 'null', '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            track_gain = None
            track_peak = None
            
            for line in result.stderr.split('\n'):
                if 'Integrated loudness:' in line:
                    import re
                    match = re.search(r'I:\s+(-?\d+\.?\d*)\s+LUFS', line)
                    if match:
                        loudness = float(match.group(1))
                        # Ziel: -16 LUFS
                        track_gain = round(-16 - loudness, 2)
                        
                if 'Peak:' in line and 'true peak:' not in line:
                    match = re.search(r'Peak:\s+(\d+\.?\d*)', line)
                    if match:
                        track_peak = float(match.group(1))
            
            if track_gain is not None:
                logger.debug(f"ReplayGain für {filepath.name}: {track_gain:+.2f} dB, Peak: {track_peak}")
                return (track_gain, track_peak or 1.0)
                
        except subprocess.TimeoutExpired:
            logger.error(f"ffmpeg Timeout für {filepath}")
        except Exception as e:
            logger.error(f"ReplayGain Fehler bei {filepath}: {e}")
            
        return None
    
    def write_replaygain_tags(self, filepath: Path, gain: float, peak: float) -> bool:
        """Schreibt ReplayGain-Tags in M4A-Datei"""
        try:
            audio = MP4(filepath)
            
            # iTunes-kompatible ReplayGain Tags
            audio['----:com.apple.iTunes:replaygain_track_gain'] = [f"{gain:+.2f} dB"]
            audio['----:com.apple.iTunes:replaygain_track_peak'] = [f"{peak:.6f}"]
            
            audio.save()
            logger.info(f"✅ ReplayGain hinzugefügt: {gain:+.2f} dB")
            return True
            
        except Exception as e:
            logger.error(f"Fehler beim Schreiben von ReplayGain: {e}")
            return False
    
    # ==================== 2. KÜNSTLERBILDER ====================
    
    @lru_cache(maxsize=100)
    def fetch_artist_image(self, artist_name: str) -> Optional[Path]:
        """
        Holt Künstlerbild von Last.fm (primär) oder MusicBrainz (Fallback)
        """
        # Sanitize für Dateinamen
        safe_name = "".join(c for c in artist_name if c.isalnum() or c in ' ._-')
        safe_name = safe_name.strip()[:50]
        image_path = self.artist_images_dir / f"{safe_name}.jpg"
        
        # Bereits vorhanden?
        if image_path.exists():
            return image_path
        
        # Versuche Last.fm
        if self.lastfm_api_key:
            result = self._fetch_lastfm_image(artist_name)
            if result:
                return self._save_image(result, image_path)
        
        # Fallback: MusicBrainz
        result = self._fetch_musicbrainz_image(artist_name)
        if result:
            return self._save_image(result, image_path)
        
        return None
    
    def _fetch_lastfm_image(self, artist_name: str) -> Optional[bytes]:
        """Holt Bild von Last.fm"""
        url = "http://ws.audioscrobbler.com/2.0/"
        params = {
            'method': 'artist.getinfo',
            'artist': artist_name,
            'api_key': self.lastfm_api_key,
            'format': 'json'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            images = data.get('artist', {}).get('image', [])
            if images:
                # Größtes Bild (letztes in der Liste)
                image_url = images[-1]['#text']
                if image_url:
                    img_response = self.session.get(image_url, timeout=15)
                    img_response.raise_for_status()
                    return img_response.content
                    
        except Exception as e:
            logger.debug(f"Last.fm Fehler für {artist_name}: {e}")
            
        return None
    
    def _fetch_musicbrainz_image(self, artist_name: str) -> Optional[bytes]:
        """Holt Bild über MusicBrainz + Cover Art Archive"""
        try:
            # Suche Artist in MusicBrainz
            mb_url = "https://musicbrainz.org/ws/2/artist/"
            params = {'query': f'artist:{artist_name}', 'fmt': 'json', 'limit': 1}
            
            response = self.session.get(mb_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('artists'):
                artist_id = data['artists'][0]['id']
                
                # Hole Bilder von Cover Art Archive
                caa_url = f"https://coverartarchive.org/artist/{artist_id}"
                caa_response = self.session.get(caa_url, timeout=10)
                
                if caa_response.status_code == 200:
                    images = caa_response.json().get('images', [])
                    for img in images:
                        if img.get('front'):
                            image_url = img.get('image')
                            if image_url:
                                img_response = self.session.get(image_url, timeout=15)
                                img_response.raise_for_status()
                                return img_response.content
                                
        except Exception as e:
            logger.debug(f"MusicBrainz Fehler für {artist_name}: {e}")
            
        return None
    
    def _save_image(self, image_data: bytes, image_path: Path) -> Optional[Path]:
        """Speichert und skaliert das Bild"""
        try:
            img = Image.open(io.BytesIO(image_data))
            # Skaliere auf max 1000px
            img.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
            
            # Konvertiere zu RGB falls nötig
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img
            
            img.save(image_path, 'JPEG', quality=85)
            logger.info(f"✅ Künstlerbild gespeichert: {image_path.name}")
            return image_path
            
        except Exception as e:
            logger.error(f"Fehler beim Speichern des Bildes: {e}")
            return None
    
    # ==================== 3. MUSICBRAINZ IDs & ISRC ====================
    
    def fetch_musicbrainz_data(self, title: str, artist: str, duration: Optional[int] = None) -> Dict:
        """
        Holt MusicBrainz Daten für einen Track
        """
        result = {
            'recording_id': None,
            'artist_id': None,
            'release_id': None,
            'isrc': None
        }
        
        # Sanitize für Suche
        clean_title = title.replace('(visualizer)', '').replace('(Official Video)', '').strip()
        main_artist = artist.split(' feat')[0].split(' &')[0].strip()
        
        query = f'track:"{clean_title}" AND artist:"{main_artist}"'
        if duration:
            query += f' AND duration:{duration}'
            
        url = "https://musicbrainz.org/ws/2/recording/"
        params = {
            'query': query,
            'fmt': 'json',
            'inc': 'artists+releases+isrcs'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('recordings'):
                recording = data['recordings'][0]
                
                result['recording_id'] = recording.get('id')
                
                if recording.get('artist-credit'):
                    result['artist_id'] = recording['artist-credit'][0].get('artist', {}).get('id')
                    
                if recording.get('isrcs'):
                    result['isrc'] = recording['isrcs'][0]
                    
                if recording.get('releases'):
                    result['release_id'] = recording['releases'][0].get('id')
                    
                logger.debug(f"MusicBrainz Match: {recording.get('title')} - {result['recording_id']}")
                    
        except Exception as e:
            logger.debug(f"MusicBrainz API Fehler: {e}")
            
        return result
    
    def write_musicbrainz_tags(self, filepath: Path, mb_data: Dict) -> bool:
        """Schreibt MusicBrainz Tags in M4A-Datei"""
        try:
            audio = MP4(filepath)
            updated = False
            
            tag_map = {
                'recording_id': '----:com.apple.iTunes:MusicBrainz Recording Id',
                'artist_id': '----:com.apple.iTunes:MusicBrainz Artist Id',
                'release_id': '----:com.apple.iTunes:MusicBrainz Release Id',
                'isrc': '----:com.apple.iTunes:ISRC'
            }
            
            for key, tag_name in tag_map.items():
                value = mb_data.get(key)
                if value:
                    audio[tag_name] = [value]
                    updated = True
                    
            if updated:
                audio.save()
                logger.info(f"✅ MusicBrainz Tags hinzugefügt: {mb_data.get('recording_id', 'N/A')}")
                return True
                
        except Exception as e:
            logger.error(f"Fehler beim Schreiben von MusicBrainz Tags: {e}")
            
        return False
    
    # ==================== HAUPTMETHODE FÜR BOT-INTEGRATION ====================
    
    def enhance_downloaded_file(self, filepath: str, artist: str = None, title: str = None) -> EnhancementResult:
        """
        Hauptmethode – wird NACH dem Download aufgerufen
        Verbessert die heruntergeladene Datei mit allen Features
        """
        path = Path(filepath)
        
        if not path.exists():
            return EnhancementResult(success=False, file=str(path), error="Datei nicht gefunden")
        
        if path.suffix.lower() != '.m4a':
            logger.warning(f"Überspringe Nicht-M4A: {path}")
            return EnhancementResult(success=False, file=str(path), error="Nur M4A wird unterstützt")
        
        result = EnhancementResult(success=True, file=str(path))
        
        try:
            # Lese bestehende Tags falls nicht übergeben
            if not artist or not title:
                audio = MP4(path)
                artist = artist or audio.get('©ART', [None])[0]
                title = title or audio.get('©nam', [None])[0]
            
            # 1. ReplayGain
            logger.info(f"📊 Berechne ReplayGain für {path.name}")
            rg_values = self.calculate_replaygain(path)
            if rg_values:
                gain, peak = rg_values
                if self.write_replaygain_tags(path, gain, peak):
                    result.replaygain_gain = gain
                    result.replaygain_peak = peak
            
            # 2. Künstlerbild (wenn Artist vorhanden)
            if artist:
                main_artist = artist.split(' feat')[0].split(' &')[0].split(',')[0].strip()
                logger.info(f"🖼️  Suche Bild für: {main_artist}")
                image_path = self.fetch_artist_image(main_artist)
                if image_path:
                    result.artist_image = str(image_path)
            
            # 3. MusicBrainz IDs
            if artist and title:
                logger.info(f"🎵 Suche MusicBrainz Daten für: {artist} - {title}")
                mb_data = self.fetch_musicbrainz_data(title, artist)
                if any(mb_data.values()):
                    if self.write_musicbrainz_tags(path, mb_data):
                        result.musicbrainz_recording_id = mb_data.get('recording_id')
                        result.musicbrainz_artist_id = mb_data.get('artist_id')
                        result.musicbrainz_release_id = mb_data.get('release_id')
                        result.isrc = mb_data.get('isrc')
                    
        except Exception as e:
            logger.error(f"Fehler bei Enhance für {path}: {e}")
            result.success = False
            result.error = str(e)
            
        return result
    
    def enhance_batch(self, directory: str) -> list:
        """Verarbeitet alle M4A-Dateien in einem Verzeichnis"""
        directory = Path(directory)
        files = list(directory.glob("*.m4a")) + list(directory.glob("*.mp4"))
        
        logger.info(f"🔍 Gefunden: {len(files)} Audio-Dateien")
        
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(self.enhance_downloaded_file, str(f)) for f in files]
            for future in futures:
                results.append(future.result())
                
        success_count = sum(1 for r in results if r.success)
        logger.info(f"✅ Fertig: {success_count}/{len(files)} erfolgreich")
        
        return results


# Import für Bildverarbeitung
import io