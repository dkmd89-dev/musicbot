"""
ISOLATION-001 (entdeckt via Live-Test-Download am 2026-08-31, isolierter
Test-Bot ueber run_test_bot.py/config_test.Config): EnhancedMetadataProcessor
._do_init() konstruierte ArtistConfig(...) OHNE mapping_dir=. Das ist ein
eigenstaendiger Fund, verwandt mit aber NICHT identisch zu TESTENV-01
(tests/test_config_test_isolation.py): TESTENV-01 stellte sicher, dass
config_test.Config::GENRE_MAPPING_DIR selbst korrekt isoliert ist - hier
ging es einen Schritt weiter kaputt, weil die isolierte
Config.GENRE_MAPPING_DIR beim Bau der ArtistConfig fuer den
ArtistNormalizer schlicht nie gelesen wurde.

ArtistNormalizer._save_case_preserve_entry() (utils/artist_map.py) faellt
bei fehlendem ArtistConfig.mapping_dir auf den RELATIVEN Pfad "mapping"
zurueck ("self.config.mapping_dir or Path('mapping')"). Je nach
Arbeitsverzeichnis des Bot-Prozesses (typischerweise das Repo-Root) landet
das in der ECHTEN Produktions-mapping/case_preserve.yaml statt in der
isolierten Test-Kopie - unabhaengig davon, dass config_test.Config
GENRE_MAPPING_DIR bereits korrekt auf /tmp/musicbot_test/mapping zeigt.

Live reproduziert: ein Testdownload mit Channel-Name "SQP" (All-Caps,
<=8 Zeichen - case_preserve.yaml Rule 2 in
ArtistNormalizer._standard_normalization()) schrieb "sqp: SQP" in die
ECHTE mapping/case_preserve.yaml. Sofort per "git checkout" rueckgaengig
gemacht, dann hier als Regressionstest festgehalten.

Betraf ausschliesslich diesen einen aktiv erreichbaren Schreibpfad
(_save_case_preserve_entry). Die drei uebrigen "self.config.mapping_dir"-
Aufrufer in utils/artist_map.py (_load_case_preserve, _load_auto_learned,
_save_auto_learned_entry ueber add_auto_learned_alias()/
learn_from_feedback()) sind entweder reine Lesepfade oder - im Fall von
add_auto_learned_alias()/learn_from_feedback() - unbenutzter toter Code
ohne Aufrufer in der echten Pipeline (der produktive Alias-Lernpfad laeuft
ausschliesslich ueber AutoLearnManager, das korrekt Config.GENRE_MAPPING_DIR
verwendet, siehe services/metadata/auto_learn.py).

Fix: enhanced_metadata_processor.py uebergibt jetzt
mapping_dir=getattr(self.config, "GENRE_MAPPING_DIR", None) an ArtistConfig.
"""

from pathlib import Path

import pytest
import yaml

from services.metadata.enhanced_metadata_processor import EnhancedMetadataProcessor


class _MinimalConfig:
    """Nur die von EnhancedMetadataProcessor._do_init() tatsaechlich
    gelesenen Attribute - analog zu HappyPathConfig in
    tests/test_metadata_processor_happy_path.py."""

    def __init__(self, tmp_path: Path, mapping_dir: Path):
        self.LIBRARY_DIR = tmp_path / "library"
        self.DOWNLOAD_DIR = tmp_path / "downloads"
        self.FAIL_DIR = tmp_path / "fail"
        self.PROCESSED_DIR = tmp_path / "processed"
        self.LOG_DIR = tmp_path / "logs"
        self.GENRE_MAPPING_DIR = mapping_dir
        self.ARTIST_OVERRIDE_FILE = tmp_path / "artist_overrides.json"
        self.METADATA_CACHE_DIR = tmp_path / "metadata_cache"
        self.DUPLICATE_CACHE_DIR = tmp_path / "duplicate_cache"
        self.FANART_API_KEY = None


@pytest.fixture
def isolated_config(tmp_path, mapping_dir_copy):
    return _MinimalConfig(tmp_path, mapping_dir_copy)


class TestArtistConfigMappingDirWiring:
    def test_artist_normalizer_mapping_dir_matches_isolated_config(
        self, isolated_config
    ):
        """
        Kernbeweis: die ArtistConfig, mit der EnhancedMetadataProcessor
        seinen ArtistNormalizer baut, muss auf dieselbe isolierte
        GENRE_MAPPING_DIR zeigen wie die uebergebene Config - nicht None
        (was in _save_case_preserve_entry() auf den relativen Produktions-
        Pfad "mapping" zurueckfaellt).
        """
        processor = EnhancedMetadataProcessor(isolated_config)
        assert processor.artist_normalizer.config.mapping_dir == (
            isolated_config.GENRE_MAPPING_DIR
        )
        assert processor.artist_normalizer.config.mapping_dir is not None

    def test_case_preserve_auto_save_writes_into_isolated_mapping_dir(
        self, isolated_config
    ):
        """
        End-to-end-Beweis (live reproduziertes Szenario): ein All-Caps-
        Kandidatenname (Rule 2 in _standard_normalization(), z.B. ein
        YouTube-Channel-Name wie 'SQP') loest beim blossen Aufruf von
        normalize() ein Auto-Save nach case_preserve.yaml aus - das MUSS
        in der isolierten mapping_dir landen, nicht in einer relativen
        "mapping/"-Produktionskopie.
        """
        processor = EnhancedMetadataProcessor(isolated_config)

        case_file = isolated_config.GENRE_MAPPING_DIR / "case_preserve.yaml"
        assert "sqp" not in {
            k.lower() for k in yaml.safe_load(case_file.read_text())["case_preserve"]
        }, "Testvoraussetzung: 'sqp' darf in der kopierten mapping/ noch nicht vorkommen"

        result = processor.artist_normalizer.normalize("SQP")

        assert result == "SQP"
        with open(case_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["case_preserve"].get("sqp") == "SQP", (
            "case_preserve-Autospeicherung hat nicht in der isolierten "
            "GENRE_MAPPING_DIR geschrieben"
        )

        # Kein relativer "mapping/case_preserve.yaml"-Pfad (Produktions-
        # Repo-Root) wurde dabei angefasst - relativ zum tatsaechlichen
        # Prozess-Arbeitsverzeichnis der Testsuite (Repo-Root) geprueft.
        repo_root_relative = Path("mapping") / "case_preserve.yaml"
        if repo_root_relative.resolve() != case_file.resolve():
            if repo_root_relative.exists():
                with open(repo_root_relative, "r", encoding="utf-8") as f:
                    prod_data = yaml.safe_load(f) or {}
                assert "sqp" not in {
                    k.lower() for k in prod_data.get("case_preserve", {})
                }, "Produktions-mapping/case_preserve.yaml wurde faelschlich beschrieben!"
