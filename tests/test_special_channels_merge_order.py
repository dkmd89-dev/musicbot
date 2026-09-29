# -*- coding: utf-8 -*-
"""
Regression: Kategorie-Prioritaet von special_channel.yaml im Merge mit
Config.SPECIAL_CHANNELS.

Die Datei-Reihenfolge der Kategorien ist Fachlogik (erste passende Kategorie
gewinnt, siehe get_special_channel_info_prioritized). Der Merge darf sie nicht
von der Hash-Reihenfolge einer set() abhaengig machen — sonst ist die Prioritaet
je Prozessstart zufaellig. Geprueft ueber mehrere PYTHONHASHSEED-Werte in
Subprozessen, weil sich der Hash-Seed nur beim Interpreterstart setzen laesst.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.filenamefixer import (
    get_special_channel_info_prioritized,
    load_special_channels_merged,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

YAML_TEXT = textwrap.dedent(
    """\
    SPECIAL_CHANNELS:
      Podcast:
        - Backstage Boxengasse
      Compilations:
        - Deep Territory
      Playlist:
        - Workout
    """
)

_SUBPROCESS_SNIPPET = textwrap.dedent(
    """\
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    from utils.filenamefixer import load_special_channels_merged

    cfg = SimpleNamespace(
        GENRE_MAPPING_DIR=Path(sys.argv[1]),
        SPECIAL_CHANNELS={"Compilations": ["FitBeatBeats"], "Extra": ["X"]},
    )
    print(",".join(load_special_channels_merged(cfg).keys()))
    """
)


@pytest.mark.parametrize("hash_seed", ["1", "2", "3", "4", "5", "6", "7", "8"])
def test_merge_keeps_yaml_category_order_for_any_hash_seed(tmp_path, hash_seed):
    (tmp_path / "special_channel.yaml").write_text(YAML_TEXT, encoding="utf-8")
    env = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=str(REPO_ROOT))
    out = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SNIPPET, str(tmp_path)],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env, check=True,
    ).stdout.strip().splitlines()[-1]
    # YAML-Kategorien in Datei-Reihenfolge, Config-only-Kategorien danach.
    assert out == "Podcast,Compilations,Playlist,Extra"


def test_merge_appends_config_channels_without_duplicates(tmp_path):
    (tmp_path / "special_channel.yaml").write_text(YAML_TEXT, encoding="utf-8")
    cfg = SimpleNamespace(
        GENRE_MAPPING_DIR=tmp_path,
        SPECIAL_CHANNELS={"Compilations": ["deep territory", "FitBeatBeats"]},
    )
    merged = load_special_channels_merged(cfg)
    assert merged["Compilations"] == ["Deep Territory", "FitBeatBeats"]


def test_overlapping_channel_resolves_to_first_yaml_category(tmp_path):
    (tmp_path / "special_channel.yaml").write_text(
        "SPECIAL_CHANNELS:\n  Podcast:\n    - Foo\n  Playlist:\n    - Foo\n",
        encoding="utf-8",
    )
    cfg = SimpleNamespace(GENRE_MAPPING_DIR=tmp_path, SPECIAL_CHANNELS={})
    merged = load_special_channels_merged(cfg)
    assert get_special_channel_info_prioritized("Foo", merged) == ("Podcast", "Foo")
