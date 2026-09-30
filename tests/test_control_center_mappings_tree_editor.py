# tests/test_control_center_mappings_tree_editor.py
# -*- coding: utf-8 -*-
"""
Genre-Hierarchie (M6) im Mapping-Editor: die echte static/pages/mappings_editor_tree.js
läuft zusammen mit mappings.js, dem Editor-Kern und common.js in node gegen Fake-DOM und
Fake-API (Harness aus tests/test_control_center_mappings_editor.py). Geprüft werden Öffnen,
Draft-Änderungen (Hinzufügen, Eltern ändern, Entfernen mit Kinderschutz und Rückgängig),
die Vorschau (Prioritätswirkung, betroffene Unterelemente), Validierungsfehler (422),
Konflikt (409), ehrlicher Speichern-Hinweis (Neustart) und Escaping.
"""
from __future__ import annotations

from tests.test_control_center_mappings_editor import (
    EDITOR_FILES,
    _calls,
    _ev,
    _el,
    _previews,
    _run,
    _save,
    needs_node,
)

_H = "genre-hierarchy"
_URL = f"/api/v1/admin/mappings/{_H}"
_TREE = [
    {"genre": "Hip Hop", "parent": None, "depth": 0, "children": 1},
    {"genre": "Drill", "parent": "Hip Hop", "depth": 1, "children": 1},
    {"genre": "UK Drill", "parent": "Drill", "depth": 2, "children": 0},
    {"genre": "Pop", "parent": None, "depth": 0, "children": 0},
]


def _list(entries=_TREE, etag="EH0"):
    return {"status": 200, "body": {"mapping_id": _H, "count": len(entries), "entries": entries, "etag": etag, "warnings": []}}


def _preview(change="update", changes=(), added=(), removed=(), changed=(), warnings=(), etag="EH0"):
    return {"status": 200, "body": {"mapping_id": _H, "change": change, "added": list(added), "removed": list(removed),
                                    "changed": list(changed), "changes": list(changes), "entries": [], "warnings": list(warnings),
                                    "etag": etag, "comment_warning": None}}


def _saved(message="Gespeichert. Für neue Downloads ist ein Bot-Neustart erforderlich: der Bot lädt genre_hierarchy.yaml beim Start."):
    return {"status": 200, "body": {"written": True, "unchanged": False, "new_etag": "EH1", "bot_reload_required": True, "message": message}}


def _responses(**over):
    r = {f"GET {_URL}": _list(), f"POST {_URL}/preview": _preview("unchanged"), f"PUT {_URL}": _saved()}
    r.update(over)
    return r


def _open():
    return _ev("mappings-root", "click", {"action": "edit-tree", "type": _H})


def _act(action, **data):
    return _ev("mappings-editor", "click", dict({"action": action}, **data))


def _field(name, value):
    return {"op": "field", "field": name, "value": value}


def _drafts(out):
    return [c["body"]["entries"] for c in _previews(out)]


def _as_map(entries):
    return {e["genre"]: e["parent"] for e in entries}


# ── Statik ───────────────────────────────────────────────────────────────


def test_tree_editor_is_loaded_by_the_template_and_checked_by_the_static_rules():
    assert any(f.name == "mappings_editor_tree.js" for f in EDITOR_FILES)
    js = next(f for f in EDITOR_FILES if f.name == "mappings_editor_tree.js").read_text(encoding="utf-8")
    assert "${API}/${TYPE_ID}" in js and "DELETE" not in js and 'ccApi("PUT"' not in js  # Speichern läuft über den Kern


# ── Öffnen ───────────────────────────────────────────────────────────────


@needs_node
def test_open_loads_the_tree_shows_it_and_runs_a_preview_without_writing(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[_open()])
    body = _el(out, "mappings-editor-body")["html"]

    assert "show" in _el(out, "mappings-editor")["cls"] and _el(out, "mappings-editor-title")["text"] == "Bearbeiten"
    assert _calls(out).count(f"GET {_URL}") == 2  # Seite + Editor
    assert "Hip Hop" in body and "Pop" in body and "Genre hinzufügen" in body and "Priorität" in body
    assert len(_previews(out)) == 1 and _drafts(out)[0] == [{"genre": g["genre"], "parent": g["parent"]} for g in _TREE]
    assert not [c for c in _calls(out) if c.startswith(("PUT", "DELETE"))]
    assert _el(out, "mappings-editor-save")["disabled"] is True   # unverändert: nichts zu speichern


@needs_node
def test_open_failure_403_and_5xx_are_shown_in_the_editor(tmp_path):
    for status in (403, 503):
        responses = _responses()
        out = _run(tmp_path, responses=responses, ops=[{"op": "respond", "responses": {f"GET {_URL}": {"status": status, "body": {"error": {"message": "kaputt"}}}}}, _open()])
        body = _el(out, "mappings-editor-body")["html"]
        assert "Hip Hop" not in body and ("kaputt" in body or status == 403)


# ── Draft: Hinzufügen ────────────────────────────────────────────────────


@needs_node
def test_add_genre_puts_it_into_the_draft_and_previews_the_full_tree(tmp_path):
    added = {"genre": "Kabarett Pop", "kind": "added", "old_parent": None, "new_parent": "Pop", "old_depth": None, "new_depth": 1, "affected": [], "affected_count": 0}
    responses = _responses(**{f"POST {_URL}/preview": _preview("update", changes=[added], added=["Kabarett Pop: Pop"])})
    out = _run(tmp_path, responses=responses, ops=[
        _open(), _act("tree-add"), _field("tree-name", "Kabarett Pop"), _field("tree-parent", "Pop"), _act("tree-form-apply"),
    ])

    draft = _as_map(_drafts(out)[-1])
    assert draft["Kabarett Pop"] == "Pop" and len(draft) == 5 and draft["Drill"] == "Hip Hop"
    preview = _el(out, "mappings-editor-preview")["html"]
    assert "Kabarett Pop" in preview and "neu unter" in preview and "Pop" in preview and "Tiefe 1" in preview
    assert _el(out, "mappings-editor-save")["disabled"] is False


@needs_node
def test_add_without_name_asks_for_one_and_sends_nothing_new(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[_open(), _act("tree-add"), _field("tree-name", ""), _act("tree-form-apply")])

    assert "Bitte einen Namen" in _el(out, "mappings-editor-body")["html"]
    assert len(_previews(out)) == 1


@needs_node
def test_a_root_genre_is_added_with_parent_null(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[
        _open(), _act("tree-add"), _field("tree-name", "Jazz"), _field("tree-parent", ""), _act("tree-form-apply"),
    ])

    assert _as_map(_drafts(out)[-1])["Jazz"] is None


# ── Draft: Eltern ändern ─────────────────────────────────────────────────


@needs_node
def test_changing_the_parent_shows_affected_children_and_the_priority_shift(tmp_path):
    change = {"genre": "Drill", "kind": "parent_changed", "old_parent": "Hip Hop", "new_parent": "Pop", "old_depth": 1, "new_depth": 1,
              "affected": ["UK Drill"], "affected_count": 1}
    shifted = {"genre": "UK Drill", "kind": "parent_changed", "old_parent": "Drill", "new_parent": "Pop", "old_depth": 2, "new_depth": 1,
               "affected": [], "affected_count": 0}
    responses = _responses(**{f"POST {_URL}/preview": _preview("update", changes=[change, shifted], changed=["Drill: Hip Hop → Pop"],
                                                                 warnings=["Die Genre-Priorität (Tiefe im Baum) ändert sich für 1 Genre(s)."])})
    out = _run(tmp_path, responses=responses, ops=[_open(), _act("tree-parent", genre="Drill"), _field("tree-parent", "Pop"), _act("tree-form-apply")])

    assert _as_map(_drafts(out)[-1])["Drill"] == "Pop"
    preview = _el(out, "mappings-editor-preview")["html"]
    assert "Eltern-Genre" in preview and "Hip Hop" in preview and "Betrifft 1 untergeordnetes Genre" in preview and "UK Drill" in preview
    assert "Tiefe 2 → 1" in preview
    assert "Genre-Priorität" in _el(out, "mappings-editor-message")["html"]
    body = _el(out, "mappings-editor-body")["html"]
    assert "verschoben (war Hip Hop)" in body


@needs_node
def test_parent_form_offers_all_genres_except_the_genre_itself(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[_open(), _act("tree-parent", genre="Drill")])
    form = _el(out, "mappings-editor-body")["html"]

    assert "Eltern-Genre ändern: Drill" in form and "Wurzel (kein Eltern-Genre)" in form
    assert '<option value="Pop"' in form and '<option value="UK Drill"' in form and '<option value="Drill"' not in form


# ── Draft: Entfernen mit Kinderschutz ────────────────────────────────────


@needs_node
def test_removing_a_genre_with_children_is_blocked_with_an_explanation(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[_open(), _act("tree-remove", genre="Drill")])

    assert "Unterelement" in _el(out, "mappings-tree-notice")["html"] and "UK Drill" in _el(out, "mappings-tree-notice")["html"]
    assert "nichts kaskadierend" in _el(out, "mappings-tree-notice")["html"]
    assert len(_previews(out)) == 1  # der Entwurf hat sich nicht verändert


@needs_node
def test_removing_a_leaf_lists_it_as_removed_and_can_be_undone(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[_open(), _act("tree-remove", genre="UK Drill")])

    body = _el(out, "mappings-editor-body")["html"]
    assert "UK Drill" not in _as_map(_drafts(out)[-1]) and len(_drafts(out)[-1]) == 3
    assert "Entfernt (1)" in body and 'data-action="tree-restore"' in body

    out = _run(tmp_path, responses=_responses(), ops=[_open(), _act("tree-remove", genre="UK Drill"), _act("tree-restore", genre="UK Drill")])
    assert _as_map(_drafts(out)[-1])["UK Drill"] == "Drill" and "Entfernt (" not in _el(out, "mappings-editor-body")["html"]


@needs_node
def test_removing_the_children_first_then_the_parent_is_possible(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[_open(), _act("tree-remove", genre="UK Drill"), _act("tree-remove", genre="Drill")])

    assert set(_as_map(_drafts(out)[-1])) == {"Hip Hop", "Pop"}


@needs_node
def test_a_newly_added_genre_that_is_removed_again_is_not_listed_as_removed(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[
        _open(), _act("tree-add"), _field("tree-name", "Neu"), _field("tree-parent", "Pop"), _act("tree-form-apply"), _act("tree-remove", genre="Neu"),
    ])

    assert "Neu" not in _as_map(_drafts(out)[-1]) and "Entfernt (" not in _el(out, "mappings-editor-body")["html"]


# ── Vorschau-Fehler ──────────────────────────────────────────────────────


@needs_node
def test_validation_error_422_lists_every_message_and_keeps_save_disabled(tmp_path):
    error = {"status": 422, "body": {"error": {"code": "MAPPING_INVALID_INPUT", "message": "Zyklus: A → B → A.\n'x': Eltern-Genre 'Nope' existiert nicht."}}}
    out = _run(tmp_path, responses=_responses(**{f"POST {_URL}/preview": error}), ops=[
        _open(), _act("tree-parent", genre="Drill"), _field("tree-parent", "UK Drill"), _act("tree-form-apply"),
    ])
    preview = _el(out, "mappings-editor-preview")["html"]

    assert preview.count("<li>") == 2 and "Zyklus" in preview and "Nope" in preview
    assert _el(out, "mappings-editor-save")["disabled"] is True


# ── Speichern, Konflikt, ehrlicher Hinweis ───────────────────────────────


def _drill_move_ops():
    return [_open(), _act("tree-parent", genre="Drill"), _field("tree-parent", "Pop"), _act("tree-form-apply")]


@needs_node
def test_save_confirms_sends_the_whole_tree_with_the_preview_etag_and_says_restart_needed(tmp_path):
    change = {"genre": "Drill", "kind": "parent_changed", "old_parent": "Hip Hop", "new_parent": "Pop", "old_depth": 1, "new_depth": 1, "affected": [], "affected_count": 0}
    responses = _responses(**{f"POST {_URL}/preview": _preview("update", changes=[change], changed=["Drill: Hip Hop → Pop"], etag="EH7")})
    out = _run(tmp_path, responses=responses, ops=_drill_move_ops() + [_save()])

    puts = [c for c in out["calls"] if c["call"] == f"PUT {_URL}"]
    assert len(puts) == 1 and puts[0]["body"]["etag"] == "EH7" and _as_map(puts[0]["body"]["entries"])["Drill"] == "Pop"
    assert len(out["confirms"]) == 1 and "1 verschoben" in out["confirms"][0] and "Kommentare bleiben erhalten" in out["confirms"][0]
    assert len(out["toasts"]) == 1 and "Bot-Neustart erforderlich" in out["toasts"][0] and "aktualisiert" not in out["toasts"][0]
    assert _calls(out).count(f"GET {_URL}") == 3          # Seite, Editor, danach Neuladen der Übersicht
    assert "GET /api/v1/admin/mappings/status" in _calls(out)


@needs_node
def test_declined_confirmation_sends_no_put(tmp_path):
    out = _run(tmp_path, responses=_responses(**{f"POST {_URL}/preview": _preview("update", changed=["x"])}), ops=_drill_move_ops() + [_save()], confirms=False)

    assert not [c for c in _calls(out) if c.startswith("PUT")] and not out["toasts"]


@needs_node
def test_conflict_409_offers_reload_and_reopens_with_the_fresh_tree_only_when_confirmed(tmp_path):
    conflict = {"status": 409, "body": {"error": {"code": "MAPPING_CHANGED", "message": "Der Mapping-Stand wurde seit der Vorschau geändert."}}}
    responses = _responses(**{f"PUT {_URL}": conflict, f"POST {_URL}/preview": _preview("update", changed=["x"])})

    out = _run(tmp_path, responses=responses, ops=_drill_move_ops() + [_save()], confirms=[True, True])
    assert len(out["confirms"]) == 2 and "Neu laden verwirft" in out["confirms"][1] and not out["toasts"]
    assert _calls(out).count(f"GET {_URL}") == 4   # Seite, Editor, Neuladen der Übersicht, Editor neu geöffnet

    out = _run(tmp_path, responses=responses, ops=_drill_move_ops() + [_save()], confirms=[True, False])
    assert _calls(out).count(f"GET {_URL}") == 2 and not out["toasts"]


@needs_node
def test_put_422_is_shown_in_the_editor_and_keeps_the_draft(tmp_path):
    error = {"status": 422, "body": {"error": {"message": "Doppeltes Genre: 'Pop'."}}}
    responses = _responses(**{f"PUT {_URL}": error, f"POST {_URL}/preview": _preview("update", changed=["x"])})
    out = _run(tmp_path, responses=responses, ops=_drill_move_ops() + [_save()])

    assert "Doppeltes Genre" in _el(out, "mappings-editor-message")["html"] and not out["toasts"]
    assert _el(out, "mappings-editor-save")["disabled"] is False  # Draft bleibt, erneutes Speichern möglich


# ── Escaping und Suche ───────────────────────────────────────────────────


@needs_node
def test_names_are_escaped_in_tree_form_and_preview(tmp_path):
    evil = "<img src=x onerror=alert(1)>"
    entries = [{"genre": evil, "parent": None, "depth": 0, "children": 0}, {"genre": "Pop", "parent": None, "depth": 0, "children": 0}]
    change = {"genre": evil, "kind": "removed", "old_parent": None, "new_parent": None, "old_depth": 0, "new_depth": None, "affected": [], "affected_count": 0}
    responses = _responses(**{f"GET {_URL}": _list(entries), f"POST {_URL}/preview": _preview("update", changes=[change])})
    out = _run(tmp_path, responses=responses, ops=[_open(), _act("tree-parent", genre=evil), _act("tree-remove", genre=evil)])

    for element in ("mappings-editor-body", "mappings-editor-preview"):
        assert "<img" not in _el(out, element)["html"]
    assert "&lt;img" in _el(out, "mappings-editor-preview")["html"] and "&lt;img" in _el(out, "mappings-editor-body")["html"]


@needs_node
def test_editor_search_filters_the_tree_without_a_request(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[
        _open(), _ev("mappings-editor", "input", {"field": "tree-search"}, "uk"),
    ])
    view = _el(out, "mappings-tree-view")["html"]

    assert "UK Drill" in view and "Hip Hop" in view and "Pop" not in view.replace("Hip Hop", "")
    assert len(_previews(out)) == 1


@needs_node
def test_node_toggle_expands_children_in_the_editor(tmp_path):
    out = _run(tmp_path, responses=_responses(), ops=[_open(), _act("tree-node-toggle", genre="Hip Hop")])
    view = _el(out, "mappings-tree-view")["html"]

    assert "Drill" in view and 'aria-expanded="true"' in view
    assert 'data-action="tree-remove"' in view and 'aria-label="Drill entfernen"' in view


@needs_node
def test_a_cycle_in_the_draft_keeps_the_genres_visible_and_fixable(tmp_path):
    error = {"status": 422, "body": {"error": {"message": "Zyklus: Hip Hop → Drill → UK Drill → Hip Hop."}}}
    responses = _responses(**{f"POST {_URL}/preview": error})
    out = _run(tmp_path, responses=responses, ops=[
        _open(), _act("tree-parent", genre="Hip Hop"), _field("tree-parent", "UK Drill"), _act("tree-form-apply"),
    ])
    body = _el(out, "mappings-editor-body")["html"]

    assert "Nicht mit einer Wurzel verbunden" in body
    for genre in ("Hip Hop", "Drill", "UK Drill"):
        assert f'data-action="tree-parent" data-genre="{genre}"' in body   # weiterhin bearbeitbar
    assert _el(out, "mappings-editor-save")["disabled"] is True
