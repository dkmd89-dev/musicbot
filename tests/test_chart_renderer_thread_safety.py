"""
AE-10 (docs/MusicBot_ARCHITECTURE_EVOLUTION.md): ChartRenderer.create_chart()
mutiert den globalen matplotlib.pyplot-Zustand (plt.style.use(),
plt.subplots(), plt.tight_layout(), plt.savefig() - alle ohne explizite
Figure-Referenz, operieren implizit auf plt.gcf()) ohne jede Synchronisation.
Solange create_chart() synchron und direkt im Event-Loop-Thread lief, war
das durch GIL + fehlende await-Punkte de-facto serialisiert. Der AE-10-Fix
(handlers/mugge_statistik_handler.py) verlagert die Aufrufe ueber
asyncio.to_thread() in den Default-ThreadPoolExecutor - damit koennen jetzt
echte, gleichzeitig laufende OS-Threads create_chart() aufrufen.

Empirisch im Rahmen des AE-10-Audits nachgewiesen:
  1. Ohne gepinntes Backend waehlt matplotlib je nach Laufzeitumgebung ein
     GUI-Backend (hier: TkAgg, weil DISPLAY gesetzt ist). Ein einzelner (!)
     Aufruf aus einem Nicht-Haupt-Thread fuehrt dort zu einem
     Prozessabsturz (SIGABRT, Tcl "main thread is not in main loop").
  2. Selbst mit einem headless-sicheren Backend (Agg) teilen sich alle
     Aufrufe die globale "aktuelle Figure" (plt.gcf()) - zwei ueberlappende
     Aufrufe koennen sich gegenseitig die Figur unterschieben: Thread A hat
     nachweislich das Diagramm von Thread B gespeichert.

Fix: matplotlib.use("Agg") gepinnt vor dem pyplot-Import (siehe
TestBackendPinning) + ein prozessweiter threading.Lock()
(ChartRenderer._render_lock) um den gesamten pyplot-beruehrenden Codeblock.
"""

import threading
from unittest.mock import patch

import matplotlib.pyplot as plt

from services.statistik.chart_renderer import ChartRenderer


def _make_stats(username: str, chart_type: str = "songs"):
    key = "top_songs" if chart_type == "songs" else "top_artists"
    return {
        "period": "month",
        "navidrome_username": username,
        key: [(f"{username}-Item-{i}", 10 - i) for i in range(5)],
    }


class _NullLock:
    """Steht stellvertretend fuer den ungeschuetzten Vorher-Zustand."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestBackendPinning:
    def test_agg_backend_is_pinned_on_import(self):
        import matplotlib

        assert matplotlib.get_backend().lower() == "agg", (
            "chart_renderer.py muss matplotlib.use('Agg') vor dem "
            "pyplot-Import aufrufen - ohne dieses Pinning waehlt "
            "matplotlib je nach Laufzeitumgebung (z.B. DISPLAY gesetzt) "
            "ein GUI-Backend, das bei Aufrufen aus einem Nicht-Haupt-Thread "
            "(asyncio.to_thread) abstuerzen kann."
        )


class TestConcurrentRenderingDoesNotCrossContaminate:
    def test_unprotected_pyplot_state_is_vulnerable_to_cross_contamination(
        self, tmp_path
    ):
        """
        Diskriminierender Vorher-Beweis (Methodik wie
        test_auto_learn_invariant_fix.py): wird der Schutz-Lock deaktiviert,
        tritt die Kontamination tatsaechlich auf - das beweist, dass der
        Lock im Fix unten wirklich etwas verhindert und nicht nur
        kosmetisch ist.
        """
        renderer = ChartRenderer(tmp_path)

        real_tight_layout = plt.tight_layout
        real_subplots = plt.subplots

        # A haelt an ihrem eigenen tight_layout() an und wartet, bis B seine
        # eigene Figure erzeugt hat (aber noch NICHT gespeichert/geschlossen
        # hat). B haelt direkt nach subplots() an und wartet, bis A ihren
        # gcf()-Schnappschuss gemacht hat - erst dann macht B mit
        # tight_layout()/savefig()/close() weiter. Damit ist die
        # Ueberlappung deterministisch erzwungen, kein Timing-Gluecksspiel.
        A_reached_tight_layout = threading.Event()
        B_created_own_figure = threading.Event()
        A_finished_checking = threading.Event()
        observed = {}

        def patched_tight_layout(*a, **kw):
            real_tight_layout(*a, **kw)
            if "fig_A_id" not in observed:
                # Garantiert Thread A: B wartet unten auf
                # A_reached_tight_layout, bevor B ueberhaupt startet.
                observed["fig_A_id"] = id(plt.gcf())
                A_reached_tight_layout.set()
                assert B_created_own_figure.wait(timeout=5), (
                    "Thread B hat seine Figure nicht rechtzeitig erzeugt"
                )
                observed["gcf_id_when_A_about_to_save"] = id(plt.gcf())
                A_finished_checking.set()

        def patched_subplots(*a, **kw):
            result = real_subplots(*a, **kw)
            if "fig_A_id" in observed and "fig_B_id" not in observed:
                # Garantiert Thread B's eigener subplots()-Aufruf.
                observed["fig_B_id"] = id(result[0])
                B_created_own_figure.set()
                assert A_finished_checking.wait(timeout=5), (
                    "Thread A hat ihre Pruefung nicht rechtzeitig beendet"
                )
            return result

        def thread_a():
            renderer.create_chart(_make_stats("USERA", "songs"), "songs")

        def thread_b():
            assert A_reached_tight_layout.wait(timeout=5), "Thread A ist nicht gestartet"
            renderer.create_chart(_make_stats("USERB", "artists"), "artists")

        with patch.object(ChartRenderer, "_render_lock", _NullLock()), patch(
            "matplotlib.pyplot.tight_layout", patched_tight_layout
        ), patch("matplotlib.pyplot.subplots", patched_subplots):
            tA = threading.Thread(target=thread_a)
            tB = threading.Thread(target=thread_b)
            tA.start()
            tB.start()
            tA.join(timeout=10)
            tB.join(timeout=10)

        assert observed["gcf_id_when_A_about_to_save"] == observed["fig_B_id"], (
            "Erwartete Kontamination trat NICHT auf - dieser Vorher-Beweis "
            "diskriminiert damit nicht zuverlaessig zwischen geschuetzt "
            "und ungeschuetzt. plt.gcf() sollte, nachdem Thread B seine "
            "eigene Figure erzeugt hat, auf Thread B's Figure zeigen - "
            "obwohl Thread A noch mitten in seiner eigenen "
            "Chart-Erstellung haengt und plt.savefig() gleich fuer SEINEN "
            "eigenen Dateipfad aufrufen wird."
        )
        assert observed["gcf_id_when_A_about_to_save"] != observed["fig_A_id"], (
            "plt.gcf() zeigt bei A's savefig() faelschlicherweise wieder "
            "auf A's EIGENE Figure - kein Nachweis der Kontamination."
        )

    def test_render_lock_prevents_cross_contamination(self, tmp_path):
        """
        Der eigentliche Regressionstest: mit dem echten, ungepatchten
        ChartRenderer._render_lock koennen zwei echte, gleichzeitig
        gestartete Threads sich nicht gegenseitig die Figure unterschieben.
        Kein Timing/Sleep - die Mutual-Exclusion-Garantie des Locks macht
        das Ergebnis deterministisch, nicht nur wahrscheinlich.
        """
        renderer = ChartRenderer(tmp_path)
        barrier = threading.Barrier(2)
        results = {}
        errors = []

        def run(label, chart_type):
            try:
                barrier.wait(timeout=5)
                results[label] = renderer.create_chart(
                    _make_stats(label, chart_type), chart_type
                )
            except Exception as e:
                errors.append((label, e))

        threads = [
            threading.Thread(target=run, args=("USERA", "songs")),
            threading.Thread(target=run, args=("USERB", "artists")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Unerwartete Fehler bei gleichzeitigem Rendern: {errors}"
        assert results.get("USERA") is not None and results["USERA"].exists()
        assert results.get("USERB") is not None and results["USERB"].exists()
        assert results["USERA"] != results["USERB"]
