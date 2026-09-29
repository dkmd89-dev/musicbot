# tests/test_control_center_navidrome_player.py
# -*- coding: utf-8 -*-
"""
CC-UI Navidrome N4 — Player (static/pages/navidrome_player.js).

Die echte navidrome_player.js läuft zusammen mit der echten common.js und
navidrome.js in node gegen einen Fake-DOM, ein Fake-Audio-Element (Play/Pause/
Ereignisse), eine Fake-Media-Session und einen In-Memory-localStorage.
Gestreamt wird über den in N3 getesteten Endpunkt /api/v1/navidrome/stream/{id};
der Browser kennt dabei nur sein Session-Cookie.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

CC_DIR = Path(__file__).resolve().parent.parent / "control_center"
COMMON_JS = CC_DIR / "static" / "common.js"
PLAYER_JS = CC_DIR / "static" / "pages" / "navidrome_player.js"
PAGE_JS = CC_DIR / "static" / "pages" / "navidrome.js"
PAGE_HTML = CC_DIR / "templates" / "navidrome.html"
ICONS = CC_DIR / "templates" / "_icons.html"
_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node nicht verfuegbar")

_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
_BASE = "/api/v1/navidrome"
_STORAGE_KEY = "cc-nav-player-v1"


# ─────────────────────────────────────────────────────────────────────────
# Statische Eigenschaften
# ─────────────────────────────────────────────────────────────────────────


def test_player_js_has_no_emoji_and_no_browser_dialogs():
    js = PLAYER_JS.read_text(encoding="utf-8")
    assert not _EMOJI.search(js)
    assert "alert(" not in js.replace('"alert"', "") and "confirm(" not in js and "prompt(" not in js


def test_player_template_parts_and_script_order():
    html = PAGE_HTML.read_text(encoding="utf-8")
    for element_id in ("nav-player-bar", "nav-queue-offcanvas", "nav-queue-body", "nav-queue-summary",
                       "nav-queue-clear", "nav-fullplayer", "nav-fullplayer-body"):
        assert f'id="{element_id}"' in html, element_id
    player = html.index('/static/pages/navidrome_player.js"')
    assert player < html.index('/static/pages/navidrome.js"')                              # Player zuerst


def test_player_icons_exist_in_sprite():
    used = set(re.findall(r'ccIcon\("([a-z0-9-]+)"', PLAYER_JS.read_text(encoding="utf-8")))
    used |= set(re.findall(r'_npBtn\("[a-z]+", "([a-z0-9-]+)"', PLAYER_JS.read_text(encoding="utf-8")))
    used |= set(re.findall(r'"(player-[a-z]+|skip-[a-z]+|repeat-once)"', PLAYER_JS.read_text(encoding="utf-8")))
    used |= set(re.findall(r'ccIcon\("([a-z0-9-]+)"', PAGE_JS.read_text(encoding="utf-8")))
    used.add("star-filled")                                   # dynamisch gewählt (Favorit an/aus)
    sprite = ICONS.read_text(encoding="utf-8")
    missing = sorted(i for i in used if f'id="i-{i}"' not in sprite)
    assert not missing, f"Icons fehlen im Sprite: {missing}"


# ─────────────────────────────────────────────────────────────────────────
# Harness
# ─────────────────────────────────────────────────────────────────────────

_HARNESS = r"""
const fs = require("fs");
const [commonPath, playerPath, pagePath, scenarioJson] = process.argv.slice(2);
const scenario = JSON.parse(scenarioJson);
const steps = scenario.__steps || [];
const els = {};
const bodyCls = new Set();
const mkEl = (id) => {
  const cls = new Set(); const attrs = {}; const handlers = {}; let inner = "";
  const btn = { handlers: {}, addEventListener: (ev, fn) => { (btn.handlers[ev] = btn.handlers[ev] || []).push(fn); } };
  const el = {
    id, hidden: false, textContent: "", className: "", style: {}, dataset: {}, value: "", disabled: false, title: "",
    get innerHTML() { return inner; }, set innerHTML(v) { inner = v; },
    classList: {
      add: (...c) => c.forEach((x) => cls.add(x)), remove: (...c) => c.forEach((x) => cls.delete(x)),
      contains: (c) => cls.has(c),
      toggle: (c, f) => { const on = f === undefined ? !cls.has(c) : !!f; if (on) cls.add(c); else cls.delete(c); return on; },
    },
    setAttribute: (k, v) => { attrs[k] = v; }, getAttribute: (k) => attrs[k], removeAttribute: (k) => { delete attrs[k]; },
    querySelector: () => (/<button/.test(inner) ? btn : null), querySelectorAll: () => [],
    addEventListener: (ev, fn) => { (handlers[ev] = handlers[ev] || []).push(fn); },
    appendChild: (c) => { (el._children = el._children || []).push(c); }, remove: () => {},
    _cls: cls, _attrs: attrs, _h: handlers, _btn: btn,
  };
  return el;
};
const tabNames = ["start", "artists", "albums", "genres", "playlists", "favorites"];
const tabs = tabNames.map((t) => { const e = mkEl("tab-" + t); e.dataset.navtab = t; els["tab-" + t] = e; return e; });
const rows = (scenario.__rows || []).map((id) => { const e = mkEl("row-" + id); e.dataset.songId = id; els["row-" + id] = e; return e; });
global.document = {
  querySelector: () => null,
  getElementById: (id) => (els[id] = els[id] || mkEl(id)),
  querySelectorAll: (sel) => (sel === "[data-navtab]" ? tabs : (sel === ".nav-song-row" ? rows : [])),
  createElement: () => mkEl("created"),
  addEventListener: () => {},
  documentElement: { getAttribute: () => "dark", setAttribute: () => {} },
  body: { classList: { toggle: (c, f) => { if (f) bodyCls.add(c); else bodyCls.delete(c); }, remove: (c) => bodyCls.delete(c),
                       contains: (c) => bodyCls.has(c) }, appendChild() {}, style: { removeProperty() {} } },
};
const hashHandlers = [];
global.window = {
  prompt: () => (scenario.__prompts ? (scenario.__prompts.shift() ?? null) : null), confirm: () => false,
  location: { hash: scenario.__hash || "", pathname: "/navidrome", search: "" },
  history: { pushState: () => { global.window.location.hash = ""; } },
  addEventListener: (ev, fn) => { if (ev === "hashchange") hashHandlers.push(fn); },
  scrollTo: () => {},
};
const store = Object.assign({}, scenario.__storage || {});
global.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
                        removeItem: (k) => { delete store[k]; } };
global.console = { ...console, error: () => {} };
const audios = [];
const fakes = {};
class FakeAudio {
  constructor() { this.src = ""; this.paused = true; this.currentTime = 0; this.duration = NaN; this.volume = 1;
                  this.preload = ""; this._h = {}; this.playCalls = 0; audios.push(this); }
  addEventListener(ev, fn) { (this._h[ev] = this._h[ev] || []).push(fn); }
  _fire(ev) { (this._h[ev] || []).forEach((f) => f()); }
  play() { this.playCalls += 1; this.paused = false; this._fire("play"); return Promise.resolve(); }
  pause() { if (!this.paused) { this.paused = true; this._fire("pause"); } }
  load() {}
  removeAttribute(a) { if (a === "src") this.src = ""; }
}
global.Audio = FakeAudio;
global.MediaMetadata = class { constructor(o) { Object.assign(this, o); } };
const session = { metadata: null, handlers: {}, setActionHandler(n, f) { this.handlers[n] = f; } };
// Node >= 21 hat ein schreibgeschütztes globales navigator -> per defineProperty ersetzen.
Object.defineProperty(globalThis, "navigator", { value: { mediaSession: session }, configurable: true, writable: true });
const calls = [];
global.fetch = async (url, options) => {
  calls.push({ url, method: (options || {}).method || "GET", body: (options || {}).body || null });
  const path = url.split("?")[0];
  const r = scenario[url] || scenario[path] || { status: 500, body: { error: { message: "boom" } } };
  return { status: r.status, ok: r.status >= 200 && r.status < 300,
           text: async () => (r.body === undefined ? "" : JSON.stringify(r.body)), json: async () => r.body };
};
const names = ["NavPlayer", "_navLists", "_navShowTab", "_navState"];
const src = fs.readFileSync(commonPath, "utf-8") + "\n" + fs.readFileSync(playerPath, "utf-8") + "\n"
  + fs.readFileSync(pagePath, "utf-8") + "\nglobalThis.__t = { " + names.join(", ") + " };";
new Function(src)();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fire = async (container, ev, evt) => { for (const fn of (els[container]._h[ev] || [])) await fn(evt); };
(async () => {
  await sleep(60);
  const P = globalThis.__t.NavPlayer;
  const audio = () => audios[0];
  for (const s of steps) {
    if (s.np) await P[s.np.method](...(s.np.args || []));
    else if (s.audio) {
      const a = audio();
      if (s.audio.duration !== undefined) a.duration = s.audio.duration;
      if (s.audio.time !== undefined) a.currentTime = s.audio.time;
      if (s.audio.times) { for (const t of s.audio.times) { a.currentTime = t; a._fire("timeupdate"); } }
      else a._fire(s.audio.event);
    }
    else if (s.npClick) {
      const c = s.npClick;
      await fire(c.container, "click", { target: { closest: (sel) => (sel === "[data-np-act]" ? { dataset: { npAct: c.act, uid: String(c.uid) } } : null) } });
    }
    else if (s.npInput) {
      const c = s.npInput;
      await fire(c.container, "input", { target: { dataset: { npRange: c.range }, value: c.value } });
    }
    else if (s.pageClick) {
      const c = s.pageClick;
      const sels = {};
      for (const [sel, spec] of Object.entries(c.sels)) {
        if (spec && spec._name) {                       // Fake mit Zustandsprotokoll (Klassen/Attribute/Titel)
          const rec = { cls: {}, attrs: {}, title: "", textContent: "" };
          fakes[spec._name] = rec;
          sels[sel] = { dataset: Object.assign({}, spec.dataset), classList: { toggle: (k, f) => { rec.cls[k] = f; } },
                        setAttribute: (k, v) => { rec.attrs[k] = v; }, set title(v) { rec.title = v; }, get title() { return rec.title; },
                        set textContent(v) { rec.textContent = v; }, get textContent() { return rec.textContent; },
                        _rec: rec, closest: () => null };
          rec.dataset = sels[sel].dataset;
        } else sels[sel] = spec;
      }
      await fire(c.container, "click", { preventDefault() {}, target: { closest: (sel) => (sels[sel] || null) } });
    }
    else if (s.rowKey) {
      const c = s.rowKey;
      await fire(c.container, "keydown", { key: c.key, preventDefault() {},
        target: { classList: { contains: () => true }, dataset: c.dataset } });
    }
    else if (s.hash !== undefined) { global.window.location.hash = s.hash; for (const fn of hashHandlers) await fn(); }
    else if (s.set) els[s.set.id].value = s.set.value;
    await sleep(25);
  }
  const a = audio() || {};
  const out = {};
  for (const [id, e] of Object.entries(els)) out[id] = { html: e.innerHTML, text: e.textContent, hidden: e.hidden, cls: [...e._cls], value: e.value, style: e.style };
  const toasts = ((els["cc-toast-container"] || {})._children || []).map((t) => t.innerHTML);
  const payload = JSON.stringify({
    els: out, calls, toasts, bodyCls: [...bodyCls], store,
    audio: { src: a.src, paused: a.paused, currentTime: a.currentTime, volume: a.volume, playCalls: a.playCalls, count: audios.length },
    np: { ids: P.queue.map((i) => i.id), original: P.original.map((i) => i.id), index: P.index, shuffle: P.shuffle, repeat: P.repeat,
          playing: P.playing, uids: P.queue.map((i) => i.uid), covers: P.queue.map((i) => i.cover), resumeAt: P.resumeAt },
    session: { metadata: session.metadata, handlers: Object.keys(session.handlers) },
    rowCls: Object.fromEntries(rows.map((r) => [r.dataset.songId, [...r._cls]])),
    fakes: Object.fromEntries(Object.entries(fakes).map(([k, v]) => [k, { cls: v.cls, attrs: v.attrs, title: v.title, text: v.textContent, dataset: v.dataset }])),
    lists: JSON.parse(JSON.stringify(globalThis.__t._navLists)), loaded: globalThis.__t._navState.loaded,
    _handlers: null,
  });
  process.stdout.write(payload + "\n", () => process.exit(0));
})();
"""


def _song(i: int, **kw) -> dict:
    d = {"id": f"s{i}", "title": f"Titel {i}", "artist": "Artist", "artist_id": "ar1", "album": "Album",
         "album_id": "a1", "duration": 200 + i, "track": i}
    d.update(kw)
    return d


_WHOAMI = {"status": 200, "body": {"user_id": 1, "access_level": "USER"}}


def _scenario(**extra) -> dict:
    scenario = {
        "/api/v1/auth/whoami": _WHOAMI,
        f"{_BASE}/status": {"status": 200, "body": {"connected": True, "artist_count": 1}},
        f"{_BASE}/newest?page=0&page_size=12": {"status": 200, "body": {"items": [], "page": 0, "page_size": 12, "has_next": False}},
        f"{_BASE}/random?size=40": {"status": 200, "body": {"songs": []}},
        f"{_BASE}/artists?page=0&page_size=12": {"status": 200, "body": {"items": [], "page": 0, "page_size": 12, "total": 0, "has_next": False}},
        f"{_BASE}/favorites": {"status": 200, "body": {"artists": [], "albums": [], "songs": []}},
    }
    scenario.update(extra)
    return scenario


def _run(tmp_path, steps=None, **extra) -> dict:
    scenario = _scenario()
    scenario["__steps"] = steps or []
    scenario.update(extra)
    script = tmp_path / "player_harness.js"
    script.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        [_NODE, str(script), str(COMMON_JS), str(PLAYER_JS), str(PAGE_JS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _play(songs, start=0, ctx=None, opts=None) -> dict:
    return {"np": {"method": "playList", "args": [songs, start, ctx, opts]}}


def _act(act, uid=0) -> dict:
    return {"npClick": {"container": "nav-player-bar", "act": act, "uid": uid}}


SONGS3 = [_song(1), _song(2), _song(3)]


# ─────────────────────────────────────────────────────────────────────────
# Wiedergabe
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_play_list_streams_first_track_and_renders_bar_and_queue(tmp_path):
    out = _run(tmp_path, [_play(SONGS3)])

    assert out["audio"]["src"] == f"{_BASE}/stream/s1" and out["audio"]["playCalls"] == 1
    assert out["audio"]["count"] == 1                                    # genau ein Audio-Element
    assert out["np"]["ids"] == ["s1", "s2", "s3"] and out["np"]["index"] == 0 and out["np"]["playing"] is True
    bar = out["els"]["nav-player-bar"]
    assert bar["hidden"] is False and "nav-has-player" in out["bodyCls"]
    assert "Titel 1" in bar["html"] and 'href="#/artist/ar1"' in bar["html"] and 'href="#/album/a1"' in bar["html"]
    assert "#i-player-pause" in bar["html"]                             # läuft -> Pause-Symbol
    assert f"{_BASE}/cover/a1?size=120" in bar["html"]                  # ohne Cover-ID: Album-ID
    queue = out["els"]["nav-queue-body"]["html"]
    assert queue.count('data-np-act="jump"') == 3 and queue.count('data-np-act="remove"') == 3
    assert out["els"]["nav-queue-summary"]["text"].startswith("3 Titel")
    assert "zugangsdaten" not in out["audio"]["src"].lower() and "p=" not in out["audio"]["src"]


@needs_node
def test_play_list_uses_context_cover_and_rejects_invalid_ids(tmp_path):
    songs = SONGS3 + [_song(4, id="../evil"), _song(5, id="a b")]
    out = _run(tmp_path, [_play(songs, 0, {"cover_art": "al-9"})])

    assert out["np"]["ids"] == ["s1", "s2", "s3"]                        # ungültige IDs kommen nie in die Warteschlange
    assert out["np"]["covers"] == ["al-9"] * 3
    assert f"{_BASE}/cover/al-9?size=120" in out["els"]["nav-player-bar"]["html"]


@needs_node
def test_toggle_pauses_and_resumes(tmp_path):
    paused = _run(tmp_path, [_play(SONGS3), _act("toggle")])
    assert paused["audio"]["paused"] is True and paused["np"]["playing"] is False
    assert "#i-player-play" in paused["els"]["nav-player-bar"]["html"]

    resumed = _run(tmp_path, [_play(SONGS3), _act("toggle"), _act("toggle")])
    assert resumed["audio"]["paused"] is False and resumed["audio"]["playCalls"] == 2


@needs_node
def test_next_prev_and_end_of_queue_rules(tmp_path):
    nxt = _run(tmp_path, [_play(SONGS3), _act("next")])
    assert nxt["np"]["index"] == 1 and nxt["audio"]["src"] == f"{_BASE}/stream/s2"

    back = _run(tmp_path, [_play(SONGS3), _act("next"), _act("prev")])
    assert back["np"]["index"] == 0                                      # am Titelanfang: vorheriger Titel

    restart = _run(tmp_path, [_play(SONGS3), _act("next"), {"audio": {"event": "timeupdate", "time": 10}}, _act("prev")])
    assert restart["np"]["index"] == 1 and restart["audio"]["currentTime"] == 0   # nach 3 s: Titel neu starten

    last_manual = _run(tmp_path, [_play(SONGS3, 2), _act("next")])
    assert last_manual["np"]["index"] == 2                               # manuell "weiter" am Ende: nichts

    ended = _run(tmp_path, [_play(SONGS3, 2), {"audio": {"event": "ended"}}])
    assert ended["np"]["index"] == 2 and ended["audio"]["paused"] is True and ended["np"]["playing"] is False


@needs_node
def test_ended_advances_and_repeat_modes(tmp_path):
    advance = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "ended"}}])
    assert advance["np"]["index"] == 1 and advance["audio"]["playCalls"] == 2

    repeat_all = _run(tmp_path, [_play(SONGS3, 2), _act("repeat"), {"audio": {"event": "ended"}}])
    assert repeat_all["np"]["repeat"] == "all" and repeat_all["np"]["index"] == 0
    assert repeat_all["audio"]["src"] == f"{_BASE}/stream/s1"

    repeat_one = _run(tmp_path, [_play(SONGS3, 1), _act("repeat"), _act("repeat"),
                                 {"audio": {"event": "timeupdate", "time": 99}}, {"audio": {"event": "ended"}}])
    assert repeat_one["np"]["repeat"] == "one" and repeat_one["np"]["index"] == 1
    assert repeat_one["audio"]["currentTime"] == 0 and repeat_one["audio"]["playCalls"] == 2
    assert "#i-repeat-once" in repeat_one["els"]["nav-player-bar"]["html"]

    cycled = _run(tmp_path, [_play(SONGS3), _act("repeat"), _act("repeat"), _act("repeat")])
    assert cycled["np"]["repeat"] == "off"


@needs_node
def test_shuffle_keeps_current_first_and_restores_original_order(tmp_path):
    songs = [_song(i) for i in range(1, 9)]
    on = _run(tmp_path, [_play(songs, 3), _act("shuffle")])
    assert on["np"]["shuffle"] is True and on["np"]["ids"][0] == "s4" and on["np"]["index"] == 0
    assert sorted(on["np"]["ids"]) == sorted(s["id"] for s in songs)
    assert on["np"]["original"] == [s["id"] for s in songs]

    off = _run(tmp_path, [_play(songs, 3), _act("shuffle"), _act("shuffle")])
    assert off["np"]["ids"] == [s["id"] for s in songs] and off["np"]["index"] == 3 and off["np"]["shuffle"] is False

    started = _run(tmp_path, [_play(songs, 0, None, {"shuffle": True})])
    assert started["np"]["shuffle"] is True and started["np"]["index"] == 0 and len(started["np"]["ids"]) == 8


# ─────────────────────────────────────────────────────────────────────────
# Warteschlange
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_add_next_and_add_end_and_empty_queue_starts_playback(tmp_path):
    out = _run(tmp_path, [_play(SONGS3), {"np": {"method": "addNext", "args": [[_song(4)], None]}},
                          {"np": {"method": "addEnd", "args": [[_song(5)], None]}}])
    assert out["np"]["ids"] == ["s1", "s4", "s2", "s3", "s5"] and out["np"]["index"] == 0
    assert out["np"]["original"] == ["s1", "s4", "s2", "s3", "s5"]
    assert any("Als Nächstes eingereiht" in t for t in out["toasts"])
    assert any("Zur Warteschlange hinzugefügt" in t for t in out["toasts"])

    empty = _run(tmp_path, [{"np": {"method": "addNext", "args": [[_song(7)], None]}}])
    assert empty["np"]["ids"] == ["s7"] and empty["audio"]["playCalls"] == 1


@needs_node
def test_add_next_keeps_original_order_consistent_with_shuffle(tmp_path):
    out = _run(tmp_path, [_play([_song(i) for i in range(1, 6)], 1), _act("shuffle"),
                          {"np": {"method": "addNext", "args": [[_song(9)], None]}}, _act("shuffle")])
    # nach dem Zurückschalten steht der neue Titel direkt hinter dem laufenden (s2)
    assert out["np"]["ids"] == ["s1", "s2", "s9", "s3", "s4", "s5"] and out["np"]["index"] == 1


@needs_node
def test_jump_remove_and_clear(tmp_path):
    def uids(steps):
        return _run(tmp_path, steps)["np"]["uids"]

    u = uids([_play(SONGS3)])
    jumped = _run(tmp_path, [_play(SONGS3), {"npClick": {"container": "nav-queue-body", "act": "jump", "uid": u[2]}}])
    assert jumped["np"]["index"] == 2 and jumped["audio"]["src"] == f"{_BASE}/stream/s3"

    before = _run(tmp_path, [_play(SONGS3, 2), {"npClick": {"container": "nav-queue-body", "act": "remove", "uid": u[0]}}])
    assert before["np"]["ids"] == ["s2", "s3"] and before["np"]["index"] == 1     # laufender Titel bleibt derselbe
    assert before["audio"]["src"] == f"{_BASE}/stream/s3" and before["audio"]["playCalls"] == 1

    current = _run(tmp_path, [_play(SONGS3), {"npClick": {"container": "nav-queue-body", "act": "remove", "uid": u[0]}}])
    assert current["np"]["ids"] == ["s2", "s3"] and current["np"]["index"] == 0
    assert current["audio"]["src"] == f"{_BASE}/stream/s2" and current["np"]["playing"] is True

    only = _run(tmp_path, [_play([_song(1)]), {"npClick": {"container": "nav-queue-body", "act": "remove", "uid": u[0]}}])
    assert only["np"]["ids"] == [] and only["els"]["nav-player-bar"]["hidden"] is True
    assert only["audio"]["src"] == "" and only["store"] == {} and "nav-has-player" not in only["bodyCls"]

    cleared = _run(tmp_path, [_play(SONGS3), {"np": {"method": "clear"}}])
    assert cleared["np"]["ids"] == [] and cleared["store"] == {} and cleared["audio"]["paused"] is True
    assert "Warteschlange leer" in cleared["els"]["nav-queue-body"]["html"]


# ─────────────────────────────────────────────────────────────────────────
# Persistenz (Entscheidung: bleibt über Neuladen erhalten, kein Autoplay)
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_state_is_saved_to_local_storage(tmp_path):
    out = _run(tmp_path, [_play(SONGS3), _act("next"), _act("repeat"), {"npInput": {"container": "nav-player-bar", "range": "volume", "value": "30"}}])
    saved = json.loads(out["store"][_STORAGE_KEY])

    assert saved["v"] == 1 and [i["id"] for i in saved["queue"]] == ["s1", "s2", "s3"]
    assert saved["index"] == 1 and saved["repeat"] == "all" and saved["shuffle"] is False
    assert saved["volume"] == 0.3 and len(saved["original"]) == 3
    assert "stream" not in out["store"][_STORAGE_KEY]                     # keine URLs/Zugangsdaten gespeichert


def _stored(index=1, position=42.5, **over) -> dict:
    queue = [{"uid": i + 1, "id": f"s{i + 1}", "title": f"Titel {i + 1}", "artist": "Artist", "artist_id": "ar1",
              "album": "Album", "album_id": "a1", "duration": 200, "cover": "a1"} for i in range(3)]
    data = {"v": 1, "queue": queue, "original": [1, 2, 3], "index": index, "position": position,
            "shuffle": False, "repeat": "all", "volume": 0.5}
    data.update(over)
    return {_STORAGE_KEY: json.dumps(data)}


@needs_node
def test_restore_shows_player_paused_without_autoplay_and_resumes_position(tmp_path):
    restored = _run(tmp_path, __storage=_stored())

    assert restored["np"]["ids"] == ["s1", "s2", "s3"] and restored["np"]["index"] == 1
    assert restored["np"]["repeat"] == "all" and restored["audio"]["volume"] == 0.5
    assert restored["audio"]["playCalls"] == 0 and restored["audio"]["src"] == ""          # nichts startet, nichts wird geladen
    bar = restored["els"]["nav-player-bar"]
    assert bar["hidden"] is False and "Titel 2" in bar["html"] and "#i-player-play" in bar["html"]
    assert restored["els"]["nav-np-cur"]["text"] == "0:42" and restored["els"]["nav-np-dur"]["text"] == "3:20"

    resumed = _run(tmp_path, [_act("toggle"), {"audio": {"event": "loadedmetadata", "duration": 200}}], __storage=_stored())
    assert resumed["audio"]["src"] == f"{_BASE}/stream/s2" and resumed["audio"]["playCalls"] == 1
    assert resumed["audio"]["currentTime"] == 42.5                                          # Position wiederhergestellt


@needs_node
@pytest.mark.parametrize("storage", [
    {_STORAGE_KEY: "{not json"},
    {_STORAGE_KEY: json.dumps({"v": 2, "queue": []})},
    {_STORAGE_KEY: json.dumps({"v": 1, "queue": [{"uid": 1, "id": "../evil"}, {"uid": 2, "id": "a b"}]})},
    {_STORAGE_KEY: json.dumps({"v": 1, "queue": "kaputt"})},
])
def test_restore_ignores_garbage(tmp_path, storage):
    out = _run(tmp_path, __storage=storage)

    assert out["np"]["ids"] == [] and out["els"]["nav-player-bar"]["hidden"] is True       # Leiste bleibt unsichtbar
    assert out["audio"]["playCalls"] == 0 and out["audio"]["src"] == ""


@needs_node
def test_restore_sanitizes_out_of_range_values(tmp_path):
    out = _run(tmp_path, __storage=_stored(index=99, repeat="bogus", volume=7))

    assert out["np"]["index"] == 0 and out["np"]["repeat"] == "off" and out["audio"]["volume"] == 0.8


# ─────────────────────────────────────────────────────────────────────────
# Fehler, Spulen, Lautstärke, Media Session
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_playback_error_skips_to_next_and_stops_when_everything_fails(tmp_path):
    one = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "error"}}])
    assert one["np"]["index"] == 1 and any("Wiedergabe fehlgeschlagen" in t and "Titel 1" in t for t in one["toasts"])

    every = _run(tmp_path, [_play(SONGS3)] + [{"audio": {"event": "error"}}] * 5)
    assert every["np"]["index"] == 2 and every["np"]["playing"] is False        # bleibt stehen, keine Endlosschleife
    assert every["audio"]["playCalls"] == 3

    recovered = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "error"}}, {"audio": {"event": "timeupdate", "time": 1}},
                                {"audio": {"event": "error"}}])
    assert recovered["np"]["index"] == 2                                          # zwischendurch erfolgreiche Wiedergabe setzt zurück


@needs_node
def test_seek_and_volume_controls(tmp_path):
    out = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "loadedmetadata", "duration": 200}},
                          {"npInput": {"container": "nav-player-bar", "range": "seek", "value": "500"}},
                          {"npInput": {"container": "nav-player-bar", "range": "volume", "value": "30"}}])
    assert out["audio"]["currentTime"] == 100 and out["audio"]["volume"] == 0.3

    clamped = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "loadedmetadata", "duration": 200}},
                              {"npInput": {"container": "nav-player-bar", "range": "seek", "value": "9999"}},
                              {"npInput": {"container": "nav-player-bar", "range": "volume", "value": "500"}}])
    assert clamped["audio"]["currentTime"] == 200 and clamped["audio"]["volume"] == 1


@needs_node
def test_seek_before_first_play_after_restore_is_applied_on_load(tmp_path):
    out = _run(tmp_path, [{"npInput": {"container": "nav-player-bar", "range": "seek", "value": "500"}}, _act("toggle"),
                          {"audio": {"event": "loadedmetadata", "duration": 200}}], __storage=_stored())

    assert out["audio"]["currentTime"] == 100                                     # 50 % von 200 s


@needs_node
def test_media_session_metadata_and_actions(tmp_path):
    out = _run(tmp_path, [_play(SONGS3, 0, {"cover_art": "al-1"})])

    meta = out["session"]["metadata"]
    assert meta["title"] == "Titel 1" and meta["artist"] == "Artist" and meta["album"] == "Album"
    assert meta["artwork"][0]["src"] == f"{_BASE}/cover/al-1?size=512"
    assert set(out["session"]["handlers"]) == {"play", "pause", "previoustrack", "nexttrack", "seekto"}


# ─────────────────────────────────────────────────────────────────────────
# Zusammenspiel mit der Seite (navidrome.js)
# ─────────────────────────────────────────────────────────────────────────

_ALBUM = {"id": "a1", "name": "Album 1", "artist": "Artist", "artist_id": "ar1", "cover_art": "al-1",
          "year": 2021, "song_count": 3, "duration": 600, "songs": SONGS3}


def _album_scenario(**kw) -> dict:
    return {f"{_BASE}/albums/a1": {"status": 200, "body": _ALBUM}, **kw}


def _page_click(**sels) -> dict:
    return {"pageClick": {"container": "nav-detail-content", "sels": sels}}


@needs_node
def test_album_page_has_play_buttons_and_playable_rows(tmp_path):
    out = _run(tmp_path, __hash="#/album/a1", **_album_scenario())

    html = out["els"]["nav-detail-content"]["html"]
    for kind in ("all", "shuffle", "next"):
        assert f'data-np-play="{kind}" data-np-list="detail"' in html
    assert html.count('class="list-group-item list-group-item-action nav-song-row"') == 3
    assert 'data-song-id="s2" data-np-list="detail" data-np-index="1"' in html
    assert html.count("data-np-add") == 3 and html.count('href="#/song/') == 3            # "+" und Details je Zeile


@needs_node
def test_album_buttons_play_shuffle_and_enqueue(tmp_path):
    play_all = _run(tmp_path, [_page_click(**{"[data-np-play]": {"dataset": {"npPlay": "all", "npList": "detail"}}})],
                    __hash="#/album/a1", **_album_scenario())
    assert play_all["np"]["ids"] == ["s1", "s2", "s3"] and play_all["audio"]["src"] == f"{_BASE}/stream/s1"
    assert play_all["np"]["covers"] == ["al-1"] * 3                                        # Album-Cover für alle Titel

    shuffled = _run(tmp_path, [_page_click(**{"[data-np-play]": {"dataset": {"npPlay": "shuffle", "npList": "detail"}}})],
                    __hash="#/album/a1", **_album_scenario())
    assert shuffled["np"]["shuffle"] is True and sorted(shuffled["np"]["ids"]) == ["s1", "s2", "s3"]

    queued = _run(tmp_path, [_play([_song(9)]),
                             _page_click(**{"[data-np-play]": {"dataset": {"npPlay": "next", "npList": "detail"}}})],
                  __hash="#/album/a1", **_album_scenario())
    assert queued["np"]["ids"] == ["s9", "s1", "s2", "s3"] and any("Als Nächstes eingereiht" in t for t in queued["toasts"])


@needs_node
def test_row_click_plays_from_that_row_add_button_appends_and_links_navigate(tmp_path):
    row = {"dataset": {"npList": "detail", "npIndex": "1"}}
    played = _run(tmp_path, [_page_click(**{".nav-song-row": row})], __hash="#/album/a1", **_album_scenario())
    assert played["np"]["ids"] == ["s1", "s2", "s3"] and played["np"]["index"] == 1
    assert played["audio"]["src"] == f"{_BASE}/stream/s2"

    added = _run(tmp_path, [_play([_song(9)]), _page_click(**{".nav-song-row": row, "[data-np-add]": {}})],
                 __hash="#/album/a1", **_album_scenario())
    assert added["np"]["ids"] == ["s9", "s2"] and any("Zur Warteschlange hinzugefügt" in t for t in added["toasts"])

    link = _run(tmp_path, [_page_click(**{".nav-song-row": row, "a": {}})], __hash="#/album/a1", **_album_scenario())
    assert link["np"]["ids"] == [] and link["audio"]["playCalls"] == 0                    # Details-Link startet nichts

    keyed = _run(tmp_path, [{"rowKey": {"container": "nav-detail-content", "key": "Enter", "dataset": row["dataset"]}}],
                 __hash="#/album/a1", **_album_scenario())
    assert keyed["np"]["index"] == 1 and keyed["audio"]["playCalls"] == 1

    other_key = _run(tmp_path, [{"rowKey": {"container": "nav-detail-content", "key": "a", "dataset": row["dataset"]}}],
                     __hash="#/album/a1", **_album_scenario())
    assert other_key["audio"]["playCalls"] == 0


@needs_node
def test_playing_row_is_highlighted_and_playback_survives_navigation(tmp_path):
    out = _run(tmp_path, [_play(SONGS3), _act("next"), {"hash": "#/album/a1"}, {"hash": ""}],
               __rows=["s1", "s2", "s3"], **_album_scenario())

    assert "nav-song-current" in out["rowCls"]["s2"] and "nav-song-current" not in out["rowCls"]["s1"]
    assert out["np"]["index"] == 1 and out["audio"]["count"] == 1                        # Hash-Navigation berührt den Player nicht
    assert out["audio"]["paused"] is False


@needs_node
def test_song_page_offers_play_and_enqueue_only(tmp_path):
    song = {**_song(1), "genre": "Rap", "genres": ["Rap"], "play_count": 3, "cover_art": "al-1", "year": 2021}
    out = _run(tmp_path, [_page_click(**{"[data-np-play]": {"dataset": {"npPlay": "all", "npList": "detail"}}})],
               __hash="#/song/s1", **{f"{_BASE}/songs/s1": {"status": 200, "body": song}})

    html = out["els"]["nav-detail-content"]["html"]
    assert 'data-np-play="all"' in html and 'data-np-play="next"' in html and 'data-np-play="shuffle"' not in html
    assert out["np"]["ids"] == ["s1"] and out["np"]["covers"] == ["al-1"]


# ─────────────────────────────────────────────────────────────────────────
# N5: Scrobble
# ─────────────────────────────────────────────────────────────────────────


def _scrobbles(out) -> list:
    return [json.loads(c["body"])["submission"] for c in out["calls"]
            if c["method"] == "POST" and c["url"] == f"{_BASE}/scrobble/s1"]


_OK = {"status": 200, "body": {"success": True}}


def _times(start: float, stop: float, step: float) -> list:
    n = int((stop - start) / step) + 1
    return [round(start + i * step, 3) for i in range(n)]


@needs_node
def test_scrobble_now_playing_is_sent_once_per_play_start(tmp_path):
    scenario = {f"{_BASE}/scrobble/s1": _OK}
    out = _run(tmp_path, [_play(SONGS3), _act("toggle"), _act("toggle")], **scenario)   # Pause + Fortsetzen

    assert _scrobbles(out) == [False]                          # genau eine "läuft gerade"-Meldung, keine Wertung


@needs_node
def test_scrobble_counts_after_half_of_the_track_but_not_before(tmp_path):
    scenario = {f"{_BASE}/scrobble/s1": _OK}
    below = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "loadedmetadata", "duration": 200}},
                            {"audio": {"event": "timeupdate", "times": _times(1, 99, 1)}}], **scenario)
    assert _scrobbles(below) == [False]                        # 99 s von 200 s: noch keine Wertung

    above = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "loadedmetadata", "duration": 200}},
                            {"audio": {"event": "timeupdate", "times": _times(1, 130, 1)}}], **scenario)
    assert _scrobbles(above) == [False, True]                  # ab 100 s genau einmal, auch bei weiterem Hören


@needs_node
def test_scrobble_ignores_seeking_and_short_tracks_and_caps_at_four_minutes(tmp_path):
    scenario = {f"{_BASE}/scrobble/s1": _OK}
    seeked = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "loadedmetadata", "duration": 200}},
                             {"audio": {"event": "timeupdate", "times": [1, 2, 150, 151, 152]}}], **scenario)
    assert _scrobbles(seeked) == [False]                       # Position > 50 %, aber nur ~4 s wirklich gehört

    short = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "loadedmetadata", "duration": 20}},
                            {"audio": {"event": "timeupdate", "times": _times(1, 20, 1)}}], **scenario)
    assert _scrobbles(short) == [False]                        # unter 30 s zählt nie

    long_track = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "loadedmetadata", "duration": 1000}},
                                 {"audio": {"event": "timeupdate", "times": _times(1, 239, 1)}}], **scenario)
    assert _scrobbles(long_track) == [False]
    long_done = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "loadedmetadata", "duration": 1000}},
                                {"audio": {"event": "timeupdate", "times": _times(1, 241, 1)}}], **scenario)
    assert _scrobbles(long_done) == [False, True]              # nach 4 min, nicht erst bei 50 % von 1000 s


@needs_node
def test_scrobble_repeat_one_counts_every_repetition_and_failures_stay_silent(tmp_path):
    scenario = {f"{_BASE}/scrobble/s1": _OK}
    out = _run(tmp_path, [_play(SONGS3), _act("repeat"), _act("repeat"), {"audio": {"event": "ended"}}], **scenario)
    assert _scrobbles(out) == [False, False]                   # jede Wiederholung meldet "läuft gerade" neu

    failing = _run(tmp_path, [_play(SONGS3), {"audio": {"event": "loadedmetadata", "duration": 200}},
                              {"audio": {"event": "timeupdate", "times": _times(1, 120, 1)}}],
                   **{f"{_BASE}/scrobble/s1": {"status": 500, "body": {"error": {"message": "boom"}}}})
    assert failing["toasts"] == [] and failing["audio"]["playCalls"] == 1          # kein Toast, Wiedergabe läuft weiter


@needs_node
def test_next_track_scrobbles_the_new_track_separately(tmp_path):
    out = _run(tmp_path, [_play(SONGS3), _act("next")], **{f"{_BASE}/scrobble/s1": _OK, f"{_BASE}/scrobble/s2": _OK})
    urls = [c["url"] for c in out["calls"] if "/scrobble/" in c["url"]]

    assert urls == [f"{_BASE}/scrobble/s1", f"{_BASE}/scrobble/s2"]


# ─────────────────────────────────────────────────────────────────────────
# N5: Favoriten (Player-Leiste)
# ─────────────────────────────────────────────────────────────────────────


def _fav_calls(out) -> list:
    return [(c["method"], c["url"]) for c in out["calls"] if "/favorites/" in c["url"]]


@needs_node
def test_player_favorite_toggle_stars_and_unstars_the_current_song(tmp_path):
    ok = {f"{_BASE}/favorites/song/s1": {"status": 200, "body": {"success": True, "kind": "song", "id": "s1", "starred": True}}}
    on = _run(tmp_path, [_play(SONGS3), _act("fav")], **ok)

    assert _fav_calls(on) == [("PUT", f"{_BASE}/favorites/song/s1")]
    assert "nav-fav-on" in on["els"]["nav-player-bar"]["html"] and 'aria-pressed="true"' in on["els"]["nav-player-bar"]["html"]
    assert any("Zu Favoriten hinzugefügt" in t for t in on["toasts"])
    assert json.loads(on["store"][_STORAGE_KEY])["queue"][0]["starred"] is True          # Zustand bleibt gespeichert

    off = _run(tmp_path, [_play([_song(1, starred=True)] + SONGS3[1:]), _act("fav")], **ok)
    assert _fav_calls(off) == [("DELETE", f"{_BASE}/favorites/song/s1")]
    assert "nav-fav-on" not in off["els"]["nav-player-bar"]["html"]
    assert any("Aus Favoriten entfernt" in t for t in off["toasts"])


@needs_node
def test_player_favorite_failure_keeps_state_and_shows_error(tmp_path):
    out = _run(tmp_path, [_play(SONGS3), _act("fav")],
               **{f"{_BASE}/favorites/song/s1": {"status": 403, "body": {"error": {"message": "Keine Berechtigung"}}}})

    assert "nav-fav-on" not in out["els"]["nav-player-bar"]["html"]
    assert any("Favorit nicht geändert" in t and "Keine Berechtigung" in t for t in out["toasts"])


@needs_node
def test_starred_state_is_shared_by_all_queue_entries_of_the_same_song(tmp_path):
    out = _run(tmp_path, [_play([_song(1), _song(2), _song(1)]), {"np": {"method": "setStarred", "args": ["s1", True]}}])
    saved = json.loads(out["store"][_STORAGE_KEY])

    assert [i["starred"] for i in saved["queue"]] == [True, False, True]


# ─────────────────────────────────────────────────────────────────────────
# N5: Favoriten und Playlists auf den Seiten
# ─────────────────────────────────────────────────────────────────────────


@needs_node
def test_pages_show_favorite_buttons_with_current_state(tmp_path):
    def page_html(hash_, **scenario):
        out = _run(tmp_path, __hash=hash_, **scenario)
        return re.sub(r"\s+", " ", out["els"]["nav-detail-content"]["html"])     # Leerraum normalisieren

    album = {**_ALBUM, "starred": True}
    html = page_html("#/album/a1", **{f"{_BASE}/albums/a1": {"status": 200, "body": album}})
    assert 'data-fav-kind="album" data-fav-id="a1" data-fav-on="1"' in html and "nav-fav-on" in html
    assert 'data-starred="0"' in html                                                     # Zeilen: Standard nicht favorisiert

    artist = {"id": "ar1", "name": "Artist", "album_count": 0, "albums": [], "starred": False}
    html = page_html("#/artist/ar1", **{f"{_BASE}/artists/ar1": {"status": 200, "body": artist}})
    assert 'data-fav-kind="artist" data-fav-id="ar1" data-fav-on="0"' in html

    song = {**_song(1), "starred": True, "genres": [], "cover_art": "al-1"}
    html = page_html("#/song/s1", **{f"{_BASE}/songs/s1": {"status": 200, "body": song}})
    assert 'data-fav-kind="song" data-fav-id="s1" data-fav-on="1"' in html

    rows = page_html("#/album/a1", **{f"{_BASE}/albums/a1": {"status": 200, "body": {
        **_ALBUM, "songs": [_song(1, starred=True), _song(2)]}}})
    assert 'data-song-id="s1" data-np-list="detail" data-np-index="0" data-starred="1"' in rows
    assert 'data-song-id="s2" data-np-list="detail" data-np-index="1" data-starred="0"' in rows
    assert "Aus Favoriten entfernen" in rows and "Zu Favoriten hinzufügen" in rows        # Menütext je Zustand


@needs_node
def test_favorite_button_click_toggles_state_and_syncs_the_player(tmp_path):
    fav_ok = {"status": 200, "body": {"success": True, "kind": "album", "id": "a1", "starred": True}}
    click = _page_click(**{"[data-fav-kind]": {"_name": "fav", "dataset": {"favKind": "album", "favId": "a1", "favOn": "0"}}})
    out = _run(tmp_path, [click], __hash="#/album/a1", **_album_scenario(**{f"{_BASE}/favorites/album/a1": fav_ok}))

    assert _fav_calls(out) == [("PUT", f"{_BASE}/favorites/album/a1")]
    fav = out["fakes"]["fav"]
    assert fav["dataset"]["favOn"] == "1" and fav["cls"]["nav-fav-on"] is True
    assert fav["attrs"]["aria-pressed"] == "true" and fav["title"] == "Aus Favoriten entfernen"
    assert any("Zu Favoriten hinzugefügt" in t for t in out["toasts"])

    song_ok = {f"{_BASE}/favorites/song/s2": {"status": 200, "body": {"success": True, "kind": "song", "id": "s2", "starred": True}}}
    song_click = _page_click(**{"[data-fav-kind]": {"_name": "fav", "dataset": {"favKind": "song", "favId": "s2", "favOn": "0"}}})
    synced = _run(tmp_path, [_play(SONGS3), song_click], __hash="#/album/a1", **_album_scenario(**song_ok))
    assert json.loads(synced["store"][_STORAGE_KEY])["queue"][1]["starred"] is True    # Player kennt den neuen Zustand


@needs_node
def test_favorite_button_failure_leaves_button_unchanged(tmp_path):
    click = _page_click(**{"[data-fav-kind]": {"_name": "fav", "dataset": {"favKind": "album", "favId": "a1", "favOn": "0"}}})
    out = _run(tmp_path, [click], __hash="#/album/a1", **_album_scenario(**{
        f"{_BASE}/favorites/album/a1": {"status": 502, "body": {"error": {"message": "Navidrome-Anfrage fehlgeschlagen"}}}}))

    fav = out["fakes"]["fav"]
    assert fav["dataset"]["favOn"] == "0" and fav["cls"] == {} and fav["attrs"] == {}
    assert any("Favorit nicht geändert" in t for t in out["toasts"])


@needs_node
def test_row_menu_favorite_next_and_playlist(tmp_path):
    row = {"dataset": {"npList": "detail", "npIndex": "1"}}
    fav_ok = {f"{_BASE}/favorites/song/s2": {"status": 200, "body": {"success": True, "kind": "song", "id": "s2", "starred": True}}}
    menu = {"_name": "menu", "dataset": {"npMenu": "fav"}}
    out = _run(tmp_path, [_page_click(**{".nav-song-row": {"_name": "row", "dataset": row["dataset"]}, "[data-np-menu]": menu})],
               __hash="#/album/a1", **_album_scenario(**fav_ok))

    assert _fav_calls(out) == [("PUT", f"{_BASE}/favorites/song/s2")]
    assert out["fakes"]["menu"]["text"] == "Aus Favoriten entfernen"
    assert out["lists"]["detail"]["songs"][1]["starred"] is True                       # Liste im Speicher aktuell

    nxt = _run(tmp_path, [_play([_song(9)]), _page_click(**{".nav-song-row": row, "[data-np-menu]": {"dataset": {"npMenu": "next"}}})],
               __hash="#/album/a1", **_album_scenario())
    assert nxt["np"]["ids"] == ["s9", "s2"]

    dropdown_toggle = _run(tmp_path, [_page_click(**{".nav-song-row": row, "[data-bs-toggle='dropdown']": {}})],
                           __hash="#/album/a1", **_album_scenario())
    assert dropdown_toggle["np"]["ids"] == []                                          # Menü öffnen spielt nichts ab


_PLAYLISTS = {"status": 200, "body": {"items": [
    {"id": "p1", "name": "Mix", "song_count": 3}, {"id": "p2", "name": "Rock", "song_count": 0}],
    "page": 0, "page_size": 100, "total": 2, "has_next": False}}


def _pl_scenario(**kw) -> dict:
    return _album_scenario(**{f"{_BASE}/playlists?page=0&page_size=100": _PLAYLISTS}, **kw)


def _posts(out) -> list:
    return [(c["url"], json.loads(c["body"])) for c in out["calls"] if c["method"] == "POST" and "/scrobble/" not in c["url"]]


_ADD_ALL = {"[data-np-play]": {"dataset": {"npPlay": "playlist", "npList": "detail"}}}


@needs_node
def test_add_album_to_existing_playlist(tmp_path):
    ok = {f"{_BASE}/playlists/p2/songs": {"status": 200, "body": {"success": True, "playlist_id": "p2", "added": 3}}}
    out = _run(tmp_path, [_page_click(**_ADD_ALL)], __hash="#/album/a1", __prompts=["2"], **_pl_scenario(**ok))

    assert _posts(out) == [(f"{_BASE}/playlists/p2/songs", {"song_ids": ["s1", "s2", "s3"]})]
    assert any("3 Titel zu „Rock“ hinzugefügt" in t for t in out["toasts"])
    assert out["loaded"].get("playlists") is False                                    # Playlist-Liste wird neu geladen


@needs_node
def test_add_to_playlist_cancelled_or_invalid_choice_sends_nothing(tmp_path):
    for prompts in ([], ["9"], ["abc"]):
        out = _run(tmp_path, [_page_click(**_ADD_ALL)], __hash="#/album/a1", __prompts=prompts, **_pl_scenario())
        assert _posts(out) == [], prompts


@needs_node
def test_add_to_new_playlist_creates_it_first(tmp_path):
    scenario = _pl_scenario(**{
        f"{_BASE}/playlists": {"status": 200, "body": {"success": True, "playlist_id": "p9", "name": "Neu"}},
        f"{_BASE}/playlists/p9/songs": {"status": 200, "body": {"success": True, "playlist_id": "p9", "added": 3}},
    })
    out = _run(tmp_path, [_page_click(**_ADD_ALL)], __hash="#/album/a1", __prompts=["0", "Neu"], **scenario)

    assert _posts(out) == [(f"{_BASE}/playlists", {"name": "Neu"}),
                           (f"{_BASE}/playlists/p9/songs", {"song_ids": ["s1", "s2", "s3"]})]
    assert any("zu „Neu“ hinzugefügt" in t for t in out["toasts"])


@needs_node
def test_add_to_playlist_errors_are_reported(tmp_path):
    failed = _run(tmp_path, [_page_click(**_ADD_ALL)], __hash="#/album/a1", __prompts=["1"], **_pl_scenario(**{
        f"{_BASE}/playlists/p1/songs": {"status": 404, "body": {"error": {"message": "Eintrag nicht gefunden"}}}}))
    assert any("Nicht zur Playlist hinzugefügt" in t and "Eintrag nicht gefunden" in t for t in failed["toasts"])
    assert failed["loaded"].get("playlists") is not False

    no_list = _run(tmp_path, [_page_click(**_ADD_ALL)], __hash="#/album/a1", __prompts=["1"], **_album_scenario())
    assert any("Playlists nicht geladen" in t for t in no_list["toasts"]) and _posts(no_list) == []


@needs_node
def test_add_more_than_500_songs_is_truncated_with_hint(tmp_path):
    many = [_song(i) for i in range(1, 502)]
    album = {**_ALBUM, "songs": many, "song_count": 501}
    scenario = _pl_scenario(**{f"{_BASE}/albums/a1": {"status": 200, "body": album},
                               f"{_BASE}/playlists/p1/songs": {"status": 200, "body": {"success": True, "playlist_id": "p1", "added": 500}}})
    out = _run(tmp_path, [_page_click(**_ADD_ALL)], __hash="#/album/a1", __prompts=["1"], **scenario)

    posted = _posts(out)[0][1]["song_ids"]
    assert len(posted) == 500 and posted[0] == "s1"
    assert any("Nur die ersten 500 von 501" in t for t in out["toasts"])


def test_n5_template_has_playlist_picker_and_row_menu_markup():
    html = PAGE_HTML.read_text(encoding="utf-8")
    for element_id in ("nav-playlist-picker", "nav-playlist-picker-list", "nav-playlist-picker-new"):
        assert f'id="{element_id}"' in html, element_id
    js = PAGE_JS.read_text(encoding="utf-8")
    for menu in ("next", "fav", "playlist"):
        assert f'data-np-menu="{menu}"' in js
    assert not _EMOJI.search(js) and not _EMOJI.search(PLAYER_JS.read_text(encoding="utf-8"))
