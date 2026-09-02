/* TR-8S STUDIO — front end.
   No framework, no build step. Talks to the Python server over fetch + SSE. */

const $ = (id) => document.getElementById(id);
const CYCLE = [".", "o", "x", "X"];      // click order: rest, ghost, normal, accent
const CLASS = { ".": "", o: "ghost", x: "on", X: "acc" };

const state = {
  slot: null,
  pattern: null,
  variation: "A",
  kit: null,
  showNotes: true,
  index: [],
  indexState: "idle",
  connected: null,
  view: "panel",
  selected: "BD",
  instruments: [],
  variations: [],
  step: -1,
  playing: false,
  busy: false,
  chatNoticed: false,
  dirty: false,
  cursor: null,        // {inst, i} while a note is being edited
  history: null,
  follow: null,
  followInst: true,        // a knob on strip X selects X; a setting
};

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const PITCH = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

function noteToMidi(n) {
  const m = /^([A-G])(#?)(-?\d+)$/.exec(n);
  if (!m) return null;
  return (Number(m[3]) + 1) * 12 + PITCH[m[1]] + (m[2] ? 1 : 0);
}
function midiToNote(m) {
  return NOTE_NAMES[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1);
}

/* ───────────────────────────── theming ───────────────────────────── */

function setTheme(name) {
  document.documentElement.dataset.theme = name;
  try { localStorage.setItem("tr8s-theme", name); } catch {}
  document.querySelectorAll("[data-set-theme]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.setTheme === name)));
}
document.querySelectorAll("[data-set-theme]").forEach((b) =>
  b.addEventListener("click", () => setTheme(b.dataset.setTheme)));
try { setTheme(localStorage.getItem("tr8s-theme") || "phosphor"); }
catch { setTheme("phosphor"); }

/* ────────────────────────────── net ──────────────────────────────── */

async function api(path, body) {
  const opts = body
    ? { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opts);
  let data;
  try { data = await r.json(); } catch { data = { error: `HTTP ${r.status}` }; }
  if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

async function callTool(name, args) {
  return (await api("/api/tool", { name, args })).result;
}

/* ──────────────────────────── rendering ──────────────────────────── */

function renderRuler() {
  const r = $("ruler");
  r.innerHTML = "";
  r.appendChild(document.createElement("span"));           // corner
  for (let i = 0; i < 16; i++) {
    const s = document.createElement("span");
    s.textContent = i + 1;
    if (i % 4 === 0) s.classList.add("beat");
    if (i === state.step && state.playing) s.classList.add("here");
    r.appendChild(s);
  }
}

function tracksFor(v) {
  return (state.pattern && state.pattern.variations
    && state.pattern.variations[v]) || {};
}

function renderVariations() {
  const box = $("variations");
  box.innerHTML = "";
  for (const v of state.variations) {
    const b = document.createElement("button");
    b.textContent = v;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-pressed", String(v === state.variation));
    if (state.pattern && state.pattern.variations && state.pattern.variations[v])
      b.classList.add("has");
    if (v === state.heardVariation) b.classList.add("heard");
    b.dataset.variation = v;
    box.appendChild(b);
  }
}

function melodyFor(v, inst) {
  const m = state.pattern && state.pattern.melodies
    && state.pattern.melodies[v];
  const e = m && m[inst];
  if (!e) return null;
  return { notes: e.notes.split(/\s+/), mode: e.mode, root: e.root,
           assumed: e.assumed };
}

// Delegated once: the grid and the variation strip are rebuilt constantly, so
// per-element listeners get detached mid-click by an incoming SSE re-render.
$("variations").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-variation]");
  if (!b) return;
  state.variation = b.dataset.variation;
  renderVariations();
  if (state.view === "grid") renderGrid(); else renderPanel();
});

$("grid").addEventListener("click", (e) => {
  const cell = e.target.closest(".cell");
  if (!cell) return;
  const inst = cell.dataset.inst, i = Number(cell.dataset.i);
  // on a melodic row a click picks the note to edit; the whole point of the
  // studio is that changing one note is a keystroke, not a menu dive
  if (melodyFor(state.variation, inst)) {
    setCursor(inst, i);
    return;
  }
  cycle(inst, i);
});

function setCursor(inst, i) {
  state.cursor = inst === null ? null : { inst, i };
  renderGrid();
  showNoteHint();
  // take focus off the chat box, which holds it on load -- otherwise every
  // keystroke meant for the note editor is typed into the prompt
  // preventScroll: focusing must not jump the grid and hide the top rows
  if (inst !== null) $("grid").focus({ preventScroll: true });
}

function showNoteHint() {
  const el = $("note-hint");
  if (!el) return;
  const c = state.cursor;
  if (!c) { el.hidden = true; return; }
  const mel = melodyFor(state.variation, c.inst);
  const cur = mel && mel.notes[c.i];
  el.hidden = false;
  el.innerHTML =
    `<b>${c.inst} step ${c.i + 1}</b> ${cur && cur !== "." ? cur : "rest"} — ` +
    `<kbd>&uarr;</kbd><kbd>&darr;</kbd> semitone, ` +
    `<kbd>shift</kbd>+ octave, <kbd>&larr;</kbd><kbd>&rarr;</kbd> step, ` +
    `<kbd>A</kbd>-<kbd>G</kbd> pitch, <kbd>del</kbd> rest, <kbd>esc</kbd> done`;
}

$("grid").addEventListener("keydown", (e) => {
  const c = state.cursor;
  if (!c) return;
  const mel = melodyFor(state.variation, c.inst);
  if (!mel) return;

  const cur = mel.notes[c.i];
  const midi = cur && cur !== "." ? noteToMidi(cur) : noteToMidi(mel.root);
  let next;

  if (e.key === "Escape") { setCursor(null); e.preventDefault(); return; }
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    const d = e.key === "ArrowLeft" ? -1 : 1;
    setCursor(c.inst, Math.max(0, Math.min(15, c.i + d)));
    e.preventDefault();
    return;
  }
  if (e.key === "ArrowUp" || e.key === "ArrowDown") {
    const step = e.shiftKey ? 12 : 1;
    next = midiToNote(midi + (e.key === "ArrowUp" ? step : -step));
  } else if (e.key === "Delete" || e.key === "Backspace") {
    next = null;
  } else if (/^[a-gA-G]$/.test(e.key)) {
    // keep the octave, change the pitch class -- what a tracker does
    const oct = Math.floor(midi / 12);
    next = midiToNote(oct * 12 + PITCH[e.key.toUpperCase()]);
  } else {
    return;
  }
  e.preventDefault();
  e.stopPropagation();
  setNote(c.inst, c.i, next, mel.root);
});

// clicking away ends the edit, so the arrow keys go back to the page
$("grid").addEventListener("blur", () => {
  if (state.cursor) setCursor(null);
});

async function setNote(inst, index, note, root) {
  if (state.busy) return;
  state.busy = true;
  $("write-state").textContent = " writing…";
  try {
    await api("/api/note", {
      variation: state.variation, instrument: inst, index, note, root });
    state.dirty = true;
    $("write-state").textContent = " written to slot (not yet WRITE-saved)";
    $("commit").disabled = false;
  } catch (err) {
    log("err", err.message);
  } finally {
    state.busy = false;
    showNoteHint();
  }
}

function renderGrid() {
  const grid = $("grid");
  grid.innerHTML = "";
  const tracks = tracksFor(state.variation);
  for (const inst of state.instruments) {
    const steps = (tracks[inst] || "................").padEnd(16, ".");
    const row = document.createElement("div");
    row.className = "row";
    row.dataset.inst = inst;

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = inst;
    row.appendChild(name);

    const mel = state.showNotes ? melodyFor(state.variation, inst) : null;
    const notes = mel && mel.notes;
    if (mel) {
      row.classList.add("melodic");
      // CTRL only holds Coarse Tune if that is what is assigned to the knob,
      // and nothing can read that -- so mark it rather than assert pitch
      if (mel.assumed) row.classList.add("assumed");
      name.title = mel.assumed
        ? `notes assume Coarse Tune is on ${inst}'s CTRL knob (root ${mel.root})`
        : `fine tune motion, root ${mel.root}`;
    }
    for (let i = 0; i < 16; i++) {
      const ch = steps[i];
      const cell = document.createElement("div");
      cell.className = "cell " + (CLASS[ch] || "");
      if (notes && ch !== "." && notes[i] && notes[i] !== ".") {
        cell.textContent = notes[i];
        cell.classList.add("note");
      } else {
        cell.textContent = ch === "." ? "·" : ch;
      }
      cell.dataset.inst = inst;
      cell.dataset.i = i;
      if (state.cursor && state.cursor.inst === inst && state.cursor.i === i)
        cell.classList.add("cursor");
      cell.title = `${inst} step ${i + 1}`;
      row.appendChild(cell);
    }
    grid.appendChild(row);
  }
  renderRuler();
  paintPlayhead();
}

// What the machine is ACTUALLY playing, from the notes it sends. This is not
// the stored pattern -- it is the sound, step by step, so a variation change
// or an edit made on the panel shows up within one bar without any message
// announcing it. Steps light as they are heard and fade as they stop.
// The knobs and faders as the machine reports them, 0..127. Both views have
// a representation of each; a moving control also flashes so the eye finds it.
function moveControl(inst, param, value) {
  const strip = document.querySelector(`.strip[data-inst="${inst}"]`);
  if (!strip) return;
  if (param === "level") {
    const cap = strip.querySelector(".fader .cap");
    const lit = strip.querySelector(".fader .lit-strip");
    if (cap) cap.style.bottom = `${2 + (value / 127) * 20}px`;
    if (lit) lit.style.height = `${4 + (value / 127) * 82}%`;
    return;
  }
  const idx = { tune: 0, decay: 1, ctrl: 2 }[param];
  const knob = strip.querySelectorAll(".knob")[idx];
  if (!knob) return;
  const i = knob.querySelector("i");
  i.style.transform = `rotate(${-140 + (value / 127) * 280}deg)`;
  knob.classList.remove("dead");
  knob.dataset.pos = String(value);
  knob.title = `${param.toUpperCase()} ${value} (from the machine)`;
  flash(knob, value);
}

const MASTER_KNOB = {
  accent: "LEVEL", reverb_level: "LEVEL",
  delay_level: "LEVEL", delay_time: "TIME", delay_feedback: "F.BACK",
  master_fx_ctrl: "CTRL", ext_in_level: "EXT IN",
};
const MASTER_SEC = {
  accent: "ACCENT", reverb_level: "REVERB", delay_level: "DELAY",
  delay_time: "DELAY", delay_feedback: "DELAY", master_fx_ctrl: "MASTER FX",
};

function moveMaster(name, value) {
  // shuffle has no drawn knob; it is a readout beside TEMPO, as on the machine
  if (name === "shuffle") {
    const el = $("p-shuffle");
    if (el) { el.textContent = String(value - 64); flash(el.parentElement, value - 64, "SHUFFLE"); }
    return;
  }
  const sec = MASTER_SEC[name];
  const lbl = MASTER_KNOB[name];
  if (!sec || !lbl) { setStatus(`${name.replace(/_/g, " ")} = ${value}`); return; }
  const box = document.querySelector(`.fxgroup[data-sec="${sec}"]`);
  if (!box) return;
  const knob = [...box.querySelectorAll(".knob")]
    .find((k) => k.querySelector("span").textContent === lbl);
  if (!knob) return;
  knob.querySelector("i").style.transform =
    `rotate(${-140 + (value / 127) * 280}deg)`;
  knob.classList.remove("dead");
  knob.title = `${lbl} ${value} (from the machine)`;
  flash(knob, value);
}

function flash(el, value, label) {
  if (!el) return;
  el.classList.add("moved");
  // the glow is the signal; a value tag over the control was tried and was
  // more clutter than help. The exact value lives in the tooltip.
  clearTimeout(el._flash);
  el._flash = setTimeout(() => el.classList.remove("moved"), 1400);
}

// While the machine plays, what it plays IS the pattern -- the machine
// itself shows its buttons that way, and hearing is exact (every hit lands on
// the first clock of its step, anchored by the beat counter). So an instrument
// that is sounding is drawn from what was heard over the last bar, not from
// the stored bytes, which cannot be re-read until it stops and go stale the
// moment a hand touches the panel. An instrument that has fallen silent
// (muted, or simply empty) falls back to the stored row.
function applyRow(el, ch) {
  el.classList.remove("on", "acc", "ghost", "heard");
  if (ch !== ".") { el.classList.add(CLASS[ch] || "on"); el.classList.add("heard"); }
}

function paintLive() {
  const live = state.live || {};
  if (state.playing) {
    for (const [inst, row] of Object.entries(live)) {
      for (let i = 0; i < 16; i++) {
        const c = document.querySelector(`.cell[data-inst="${inst}"][data-i="${i}"]`);
        if (c) applyRow(c, row[i] || ".");
      }
    }
    const row = live[state.selected];
    if (row) {
      document.querySelectorAll("#pads .pad").forEach((p) => {
        applyRow(p, row[Number(p.dataset.i)] || ".");
      });
    }
    return;
  }
  // stopped: the stored pattern is exact again; drop any heard marks
  document.querySelectorAll(".heard").forEach((c) => c.classList.remove("heard"));
}

function paintPlayhead() {
  const on = state.playing && state.step >= 0;
  document.querySelectorAll(".cell.here").forEach((c) => c.classList.remove("here"));
  document.querySelectorAll(".row.hit").forEach((r) => r.classList.remove("hit"));
  document.querySelectorAll(".ruler span.here").forEach((s) => s.classList.remove("here"));
  if (!on) return;
  document.querySelectorAll(`.cell[data-i="${state.step}"]`)
    .forEach((c) => c.classList.add("here"));
  const marks = $("ruler").children;
  if (marks[state.step + 1]) marks[state.step + 1].classList.add("here");
  const tracks = tracksFor(state.variation);
  for (const [inst, steps] of Object.entries(tracks)) {
    if (steps[state.step] && steps[state.step] !== ".") {
      const row = document.querySelector(`.row[data-inst="${inst}"]`);
      if (row) row.classList.add("hit");
    }
  }
}

const SCALE_LABEL = { "8T": "1/8T", "16T": "1/16T", "16": "1/16", "32": "1/32" };

function renderKit() {
  const box = $("kitstrip");
  box.innerHTML = "";
  box.hidden = state.view === "panel";   // the panel shows tones on the strips
  if (box.hidden) return;
  const k = state.kit;
  if (!k) return;
  const head = document.createElement("span");
  head.className = "kname";
  head.textContent = `KIT ${k.panel} ${k.name}`;
  box.appendChild(head);
  for (const inst of state.instruments) {
    const f = (k.instruments || {})[inst];
    if (!f) continue;
    const el = document.createElement("span");
    el.className = "k" + (f.melodic ? " mel" : "");
    el.innerHTML = "";
    const b = document.createElement("b"); b.textContent = inst;
    el.appendChild(b);
    el.appendChild(document.createTextNode(f.tone_name || `#${f.tone}`));
    if (f.root) {
      const r = document.createElement("span");
      r.className = "root"; r.textContent = f.root;
      el.appendChild(r);
    }
    el.title = `${inst}: tone ${f.tone}` +
      (f.melodic ? " (sample - can play melodies)" : " (ACB - no Coarse Tune)") +
      `  tune ${f.tune}  decay ${f.decay}  pan ${f.pan}`;
    box.appendChild(el);
  }
}

/* ───────────────── the machine itself ───────────────── */

function setView(v) {
  state.view = v;
  document.querySelector(".machine").classList.toggle("on-panel", v === "panel");
  $("view-grid").hidden = v !== "grid";
  $("view-panel").hidden = v !== "panel";
  $("v-grid").setAttribute("aria-pressed", String(v === "grid"));
  $("v-panel").setAttribute("aria-pressed", String(v === "panel"));
  try { localStorage.setItem("tr8s-view", v); } catch {}
  if (v === "grid") renderGrid(); else renderPanel();
  renderKit();
}
$("v-grid").addEventListener("click", () => setView("grid"));
$("v-panel").addEventListener("click", () => setView("panel"));

// The TR-8S palette, indexed by the kit's colour byte. The mapping from index
// to colour is inferred, not confirmed against the panel — see kit.COLOUR_NAMES.
const INST_COLORS = [
  "#ff2d2d", "#ff8c1a", "#ffe01a", "#5ede2b", "#1fd6a8", "#22d3ee",
  "#3b82f6", "#6366f1", "#a855f7", "#ec4899", "#fb7185", "#e8f0ff",
];

function instColor(f) {
  const i = f && typeof f.color === "number" ? f.color : null;
  return i === null ? "var(--accent-2)" : INST_COLORS[i % INST_COLORS.length];
}

function knobEl(label, val, lo, hi, note, tint) {
  const k = document.createElement("div");
  k.className = "knob" + (typeof val === "number" ? "" : " dead");
  const i = document.createElement("i");
  const frac = (typeof val === "number") ? (val - lo) / (hi - lo) : 0.5;
  i.style.transform = `rotate(${-140 + frac * 280}deg)`;
  // remember the 0..127 position so a live CC and a redraw agree
  k.dataset.pos = typeof val === "number" ? String(Math.round(frac * 127)) : "";
  if (tint) i.style.borderColor = tint;
  k.appendChild(i);
  const s = document.createElement("span");
  s.textContent = label;
  k.appendChild(s);
  k.title = `${label} ${val ?? "\u2014"}${note ? " \u2014 " + note : ""}`;
  return k;
}

const COLOR_NAMES = ["red", "orange", "yellow", "green", "teal", "cyan",
                     "blue", "indigo", "violet", "magenta", "pink", "white"];

let colorFor = null;          // instrument whose palette is open

function openSwatches(inst, anchor) {
  colorFor = inst;
  const box = $("swatches"), grid = $("sw-grid");
  const f = ((state.kit && state.kit.instruments) || {})[inst] || {};
  $("sw-label").textContent = inst;
  grid.innerHTML = "";
  INST_COLORS.forEach((c, i) => {
    const b = document.createElement("button");
    b.className = "sw" + (f.color === i ? " on" : "");
    b.style.background = c;
    b.dataset.index = i;
    b.title = `${i} — ${COLOR_NAMES[i]}`;
    grid.appendChild(b);
  });
  box.hidden = false;
  const r = anchor.getBoundingClientRect();
  box.style.left = Math.max(8, Math.min(r.left - 40,
    window.innerWidth - box.offsetWidth - 8)) + "px";
  box.style.top = (r.bottom + 6) + "px";
}

function closeSwatches() { $("swatches").hidden = true; colorFor = null; }

$("sw-grid").addEventListener("click", async (e) => {
  const b = e.target.closest(".sw");
  if (!b || !colorFor) return;
  const inst = colorFor, index = Number(b.dataset.index);
  closeSwatches();
  try {
    await callTool("kit.set_color", { slot: state.pattern.kit,
                                      colors: { [inst]: index } });
    // repaint from the device's own read-back rather than assuming
    await load(state.slot);
    log("sys", `${inst} fader set to ${COLOR_NAMES[index]}`);
  } catch (err) { log("err", err.message); }
});

document.addEventListener("click", (e) => {
  if (!$("swatches").hidden && !e.target.closest("#swatches")
      && !e.target.closest(".swatch-chip")) closeSwatches();
}, true);

// One column per instrument, exactly as the machine has it: TUNE, DECAY and
// CTRL stacked above a colour-lit fader, above the instrument's own button.
function renderStrips() {
  const box = $("strips");
  box.innerHTML = "";
  const insts = (state.kit && state.kit.instruments) || {};
  const tracks = tracksFor(state.variation);

  for (const inst of state.instruments) {
    const f = insts[inst] || {};
    const tint = instColor(f);
    const strip = document.createElement("div");
    strip.className = "strip"
      + (inst === state.selected ? " sel" : "")
      + (f.melodic ? " mel" : "");
    strip.dataset.inst = inst;
    strip.style.setProperty("--inst", tint);

    const knobs = document.createElement("div");
    knobs.className = "knobs";
    knobs.appendChild(knobEl("TUNE", f.tune, -128, 127, null, tint));
    knobs.appendChild(knobEl("DECAY", f.decay, 0, 255, null, tint));
    knobs.appendChild(knobEl("CTRL", null, 0, 255,
      "whatever CTRL SELECT assigns; software cannot read it", tint));
    strip.appendChild(knobs);

    // fader position is the REAL one: level is written by the hardware fader
    const fader = document.createElement("div");
    fader.className = "fader";
    const track = document.createElement("div"); track.className = "track";
    const cap = document.createElement("div"); cap.className = "cap";
    const lvl = typeof f.level === "number" ? f.level : 0;
    const lit = document.createElement("div");
    lit.className = "lit-strip";
    lit.style.height = `${4 + (lvl / 255) * 82}%`;
    cap.style.bottom = `${2 + (lvl / 255) * 20}px`;
    cap.title = `level ${lvl} (set by the physical fader; software cannot change it)`;
    fader.appendChild(track); fader.appendChild(lit); fader.appendChild(cap);
    strip.appendChild(fader);

    const b = document.createElement("div");
    b.className = "ibtn"; b.textContent = inst;
    b.title = `${inst}: ${f.tone_name || "?"}`
      + (f.root ? ` (${f.root})` : "")
      + (f.color_name ? ` — fader lit ${f.color_name}` : "");
    strip.appendChild(b);

    const chip = document.createElement("button");
    chip.className = "swatch-chip";
    chip.style.background = tint;
    chip.title = `fader colour: ${f.color_name || "?"} — click to change`;
    chip.dataset.inst = inst;
    strip.appendChild(chip);

    const t = document.createElement("div");
    t.className = "tname";
    t.textContent = f.tone_name || (f.tone != null ? "#" + f.tone : "");
    t.title = (f.tone_name || "") + (f.root ? ` — sounds at ${f.root}` : "")
      + (f.melodic ? " (sample: can play melodies)" : "");
    strip.appendChild(t);

    if ((tracks[inst] || "").replace(/\./g, "")) strip.classList.add("has");
    if (armed) strip.classList.add("target");
    box.appendChild(strip);
  }
}

function renderPads() {
  const box = $("pads");
  box.innerHTML = "";
  const steps = (tracksFor(state.variation)[state.selected]
    || "................").padEnd(16, ".");
  const notes = state.showNotes
    ? melodyFor(state.variation, state.selected) : null;
  for (let i = 0; i < 16; i++) {
    const ch = steps[i];
    const pad = document.createElement("div");
    pad.className = "pad " + (CLASS[ch] || "");
    pad.dataset.i = i;
    pad.textContent = (notes && ch !== "." && notes[i] && notes[i] !== ".")
      ? notes[i] : (i + 1);
    pad.title = `${state.selected} step ${i + 1}`;
    box.appendChild(pad);
  }
  $("p-sel").textContent = state.selected;
}

function renderVarLamps() {
  const box = $("p-vars");
  box.innerHTML = "";
  for (const v of state.variations) {
    const el = document.createElement("div");
    el.className = "v"
      + (v === state.variation ? " on" : "")
      + ((state.pattern && state.pattern.variations
          && state.pattern.variations[v]) ? " has" : "");
    el.textContent = v;
    el.dataset.variation = v;
    box.appendChild(el);
  }
}

function renderPanel() {
  const p = state.pattern;
  $("p-name").textContent = p ? (p.name || "(unnamed)") : "—";
  $("p-sub").textContent = p
    ? `${p.panel}  KIT ${p.kit_panel}  VAR ${state.variation}` : "";
  const t = $("p-tempo");
  if (t) t.textContent = p ? Number(p.tempo).toFixed(1) : "---";
  renderStrips(); renderVarLamps(); renderPads();
  paintPanelLive(); renderSwap();
}

function paintPanelLive() {
  const on = state.playing && state.step >= 0;
  const run = $("p-run");
  run.textContent = on ? "▶" : "■";
  run.className = "lcd-run" + (on ? " on" : "");
  const ss = $("p-startstop");
  if (ss) ss.classList.toggle("lit", !!state.playing);

  document.querySelectorAll(".pad.here").forEach((p) => p.classList.remove("here"));
  document.querySelectorAll(".strip.lit").forEach((s) => s.classList.remove("lit"));
  if (!on) return;
  const pad = document.querySelector(`.pad[data-i="${state.step}"]`);
  if (pad) pad.classList.add("here");
  const tracks = tracksFor(state.variation);
  for (const [inst, steps] of Object.entries(tracks)) {
    if (steps[state.step] && steps[state.step] !== ".") {
      const s = document.querySelector(`.strip[data-inst="${inst}"]`);
      if (s) s.classList.add("lit");
    }
  }
}

/* ─────────────────── pattern browser ─────────────────── */

function openBrowser() {
  $("browser").hidden = false;
  $("br-search").value = "";
  $("br-search").focus();
  renderBrowser();
  if (!state.index.length) scanPatterns();
}
function closeBrowser() { $("browser").hidden = true; }

async function scanPatterns() {
  $("br-scan").disabled = true;
  try { await api("/api/index", {}); }
  catch (e) { log("err", e.message); }
  finally { $("br-scan").disabled = false; }
}

function renderBrowser() {
  const list = $("br-list");
  const q = $("br-search").value.trim().toLowerCase();
  const rows = state.index.filter((e) =>
    !q || e.name.toLowerCase().includes(q) || e.panel.includes(q));
  list.innerHTML = "";
  for (const e of rows) {
    const row = document.createElement("div");
    row.className = "prow" + (e.slot === state.slot ? " cur" : "")
      + (e.name === "----" || !e.name ? " empty" : "");
    row.dataset.slot = e.slot;
    for (const [cls, text] of [["", e.panel], ["nm", e.name || "(blank)"],
                               ["", e.tempo + " BPM"], ["", "kit " + (e.kit + 1)],
                               ["vars", (e.variations || []).join("")]]) {
      const c = document.createElement("span");
      c.className = cls; c.textContent = text;
      row.appendChild(c);
    }
    list.appendChild(row);
  }
  const total = state.index.length;
  $("br-foot").textContent = state.indexState === "building"
    ? `scanning… ${total}/128 read`
    : `${rows.length} shown of ${total} scanned · panel · name · tempo · kit · variations`;
}

$("browse").addEventListener("click", openBrowser);
$("br-close").addEventListener("click", closeBrowser);
$("br-scan").addEventListener("click", scanPatterns);
$("browser").addEventListener("click", (e) => {
  if (e.target.id === "browser") closeBrowser();
});
$("br-search").addEventListener("input", renderBrowser);
$("br-list").addEventListener("click", (e) => {
  const row = e.target.closest(".prow");
  if (!row) return;
  closeBrowser();
  load(Number(row.dataset.slot));
});

/* ───────────────────── tone picker ───────────────────── */

const CATS = ["", "BD", "SD", "TOM", "RS", "HC", "CH/OH", "CC/RC",
              "PERC1", "PERC2", "PERC3", "PERC4", "PERC5", "FX/HIT",
              "VOICE", "SYNTH1", "SYNTH2", "BASS", "SCALED", "CHORD",
              "IMPORT", "OTHERS"];

let pickerFor = null;

function openPicker(inst) {
  pickerFor = inst;
  $("pk-inst").textContent = inst;
  const sel = $("pk-cat");
  if (!sel.options.length) {
    for (const c of CATS) {
      const o = document.createElement("option");
      o.value = c; o.textContent = c || "all categories";
      sel.appendChild(o);
    }
  }
  $("picker").hidden = false;
  $("pk-search").value = "";
  $("pk-search").focus();
  loadTones();
}

function closePicker() { $("picker").hidden = true; pickerFor = null; }

async function loadTones() {
  const list = $("pk-list");
  list.textContent = "loading…";
  const q = { limit: 300 };
  const cat = $("pk-cat").value;
  const name = $("pk-search").value.trim();
  if (cat) q.category = cat;
  if (name) q.name_contains = name;
  let tones;
  try {
    tones = await callTool("tones.search", q);
  } catch (e) {
    list.textContent = "";
    const p = document.createElement("div");
    p.className = "msg err";
    p.textContent = e.message;
    list.appendChild(p);
    return;
  }
  const cur = ((state.kit && state.kit.instruments) || {})[pickerFor] || {};
  list.innerHTML = "";
  for (const t of tones) {
    const row = document.createElement("div");
    row.className = "trow" + (t.melodic || t.type === 2 ? " mel" : "")
      + (t.id === cur.tone ? " cur" : "");
    row.dataset.tone = t.id;
    const cells = [
      String(t.id),
      t.name,
      t.cat || "",
      t.root || "",
      t.sustained ? "sustain" : (t.decay_ms ? t.decay_ms + "ms" : ""),
      t.centroid ? t.centroid + "Hz" : "",
    ];
    cells.forEach((text, i) => {
      const c = document.createElement("span");
      c.className = ["", "nm", "", "r", "", ""][i];
      c.textContent = text;
      row.appendChild(c);
    });
    list.appendChild(row);
  }
  $("pk-foot").textContent =
    `${tones.length} tones · id · name · category · root · decay · brightness`
    + " — coloured names are sample tones, the only ones that can play melodies";
}

$("pk-close").addEventListener("click", closePicker);
$("picker").addEventListener("click", (e) => {
  if (e.target.id === "picker") closePicker();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("picker").hidden) closePicker();
  else if (!$("browser").hidden) closeBrowser();
});
$("pk-cat").addEventListener("change", loadTones);
let searchTimer = null;
$("pk-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadTones, 220);
});

$("pk-list").addEventListener("click", async (e) => {
  const row = e.target.closest(".trow");
  if (!row || !pickerFor) return;
  const tone = Number(row.dataset.tone);
  const inst = pickerFor;
  closePicker();
  setStatus(`assigning tone ${tone} to ${inst}…`);
  try {
    const r = await callTool("kit.set_instrument",
      { slot: state.pattern.kit, instrument: inst, tone });
    (r.warnings || []).forEach((w) => log("sys", w));
    setStatus(`${inst} -> tone ${tone}`);
    await load(state.slot);          // re-read so the strip shows the new tone
  } catch (err) {
    log("err", err.message);
    setStatus("assign failed");
  }
});

$("strips").addEventListener("click", (e) => {
  if (e.target.closest(".tname")) {
    const strip = e.target.closest(".strip[data-inst]");
    if (strip) { openPicker(strip.dataset.inst); return; }
  }
  const chip = e.target.closest(".swatch-chip");
  if (chip) { openSwatches(chip.dataset.inst, chip); return; }
  const strip = e.target.closest(".strip[data-inst]");
  if (!strip) return;
  if (armed) { placeArmed(strip.dataset.inst); return; }
  if (swapRestore && swapRestore.inst !== strip.dataset.inst) restoreAudition();
  state.selected = strip.dataset.inst;
  renderStrips(); renderPads(); paintPanelLive(); renderSwap();
});

$("p-vars").addEventListener("click", (e) => {
  const v = e.target.closest("[data-variation]");
  if (!v) return;
  state.variation = v.dataset.variation;
  renderPanel();
});

$("pads").addEventListener("click", (e) => {
  const pad = e.target.closest(".pad");
  if (!pad) return;
  cycle(state.selected, Number(pad.dataset.i));
});

function renderMeta() {
  const p = state.pattern;
  $("m-name").textContent = p ? p.name || "(unnamed)" : "—";
  // a view served from the fingerprint index (while the machine plays and
  // cannot be read) has steps but no header; say so instead of "null BPM"
  $("m-detail").textContent = !p ? ""
    : p.from_index ? `${p.panel || ""}  showing what the studio remembers — ` +
                     `tempo and kit arrive the next time the machine stops`
    : `${p.panel || ""}  ${p.tempo} BPM  kit ${p.kit_panel}  ` +
      `${SCALE_LABEL[p.scale] || p.scale}` +
      (p.shuffle ? `  shuffle ${p.shuffle > 0 ? "+" : ""}${p.shuffle}` : "");
}

/* ──────────────────────────── editing ───────────────────────────── */

async function cycle(inst, index) {
  if (!state.pattern || state.busy) return;
  if (state.followInst && inst !== state.selected) {
    state.selected = inst;
    if (state.view === "panel") { renderStrips(); renderPads(); }
  }
  const tracks = tracksFor(state.variation);
  const cur = (tracks[inst] || "................").padEnd(16, ".");
  const next = CYCLE[(CYCLE.indexOf(cur[index]) + 1) % CYCLE.length];
  const steps = cur.slice(0, index) + next + cur.slice(index + 1);

  // optimistic paint, then confirm from the device's own read-back
  if (!state.pattern.variations[state.variation])
    state.pattern.variations[state.variation] = {};
  state.pattern.variations[state.variation][inst] = steps;
  if (state.view === "grid") renderGrid(); else renderPads();
  const cell = document.querySelector(
    `.cell[data-inst="${inst}"][data-i="${index}"]`);
  if (cell) cell.classList.add("pending");

  state.busy = true;
  $("grid").classList.add("busy"); $("pads").classList.add("busy");
  $("write-state").textContent = " writing…";
  try {
    await api("/api/step", {
      variation: state.variation, instrument: inst, index, value: next,
    });
    state.dirty = true;
    $("write-state").textContent = " written to slot (not yet WRITE-saved)";
    $("commit").disabled = false;
  } catch (e) {
    $("write-state").textContent = "";
    log("err", e.message);
    await load(state.slot);            // resync from the device
  } finally {
    state.busy = false;
    $("grid").classList.remove("busy"); $("pads").classList.remove("busy");
    if (cell) cell.classList.remove("pending");
  }
}

async function load(slot) {
  try {
    const { pattern } = await api("/api/select", { slot });
    state.slot = pattern.slot;
    state.pattern = pattern;
    const withSteps = Object.keys(pattern.variations || {});
    if (!withSteps.includes(state.variation) && withSteps.length)
      state.variation = withSteps[0];
    renderMeta(); renderVariations(); renderKit();
    if (state.view === "grid") renderGrid(); else renderPanel();
    $("slot").value = pattern.panel || slot;
    state.dirty = false;
    $("commit").disabled = true;
    $("write-state").textContent = "";
    setStatus(`loaded ${pattern.name} (${pattern.panel})`);
  } catch (e) {
    log("err", `could not load ${slot}: ${e.message}`);
    setStatus("load failed");
  }
}

/* ───────────────────────────── chat ─────────────────────────────── */

function log(kind, text) {
  const el = document.createElement("div");
  el.className = kind === "tool" ? "tool" : `msg ${kind}`;
  el.textContent = text;
  $("log").appendChild(el);
  $("log").scrollTop = $("log").scrollHeight;
  return el;
}

let working = null;
let streaming = null;          // the bot line being streamed into
let thought = null;            // the reasoning line being streamed into
let turnTools = 0, turnStart = 0;

let turnSaid = false;          // did any prose reach the transcript this turn

function chatEvent(ev) {
  if (ev.type === "reset") { log("sys", "new conversation"); return; }
  if (ev.type === "status") { renderAI(ev.status); return; }
  if (ev.type === "text" || ev.type === "delta") turnSaid = true;
  if (ev.type === "thinking") {
    if (!working && !streaming && !thought) { working = log("sys", "thinking"); working.classList.add("working"); }
  } else if (ev.type === "thought_delta") {
    if (working) { working.remove(); working = null; }
    if (!thought) { thought = log("thought", ""); }
    thought.textContent += ev.text;
    $("log").scrollTop = $("log").scrollHeight;
  } else if (ev.type === "thought") {
    if (working) { working.remove(); working = null; }
    if (thought) { thought.textContent = ev.text; thought = null; }
    else log("thought", ev.text);
  } else if (ev.type === "delta") {
    if (thought) thought = null;
    if (working) { working.remove(); working = null; }
    if (!streaming) { streaming = log("bot", ""); streaming.classList.add("streaming"); }
    streaming.textContent += ev.text;
    $("log").scrollTop = $("log").scrollHeight;
  } else if (ev.type === "text") {
    if (working) { working.remove(); working = null; }
    if (streaming) { streaming.textContent = ev.text; streaming.classList.remove("streaming"); streaming = null; }
    else log("bot", ev.text);
  } else if (ev.type === "tool") {
    if (streaming) { streaming.classList.remove("streaming"); streaming = null; }
    turnTools++;
    const args = JSON.stringify(ev.input || {});
    const el = log("tool", "");
    el.innerHTML = `<b>${ev.name}</b> ${escapeHtml(args.length > 140 ? args.slice(0, 137) + "…" : args)}`;
    if (!working) { working = log("sys", "working"); working.classList.add("working"); }
  } else if (ev.type === "result") {
    const el = log("tool", `  ${ev.ok ? "ok" : "FAILED"} ${ev.summary || ""}`);
    if (!ev.ok) el.classList.add("bad");
  } else if (ev.type === "ratelimit") {
    const i = ev.info || {};
    if (i.status && i.status !== "allowed")
      log("sys", `rate limit: ${i.status}${i.resetsAt ? " until " + new Date(i.resetsAt * 1000).toLocaleTimeString() : ""}`);
  } else if (ev.type === "error") {
    if (working) { working.remove(); working = null; }
    if (streaming) { streaming.classList.remove("streaming"); streaming = null; }
    log("err", ev.message);
    if (/not signed in|could not start|api key|401|authentication/i.test(ev.message || "")) openConnect(true);
  } else if (ev.type === "done") {
    if (working) { working.remove(); working = null; }
    if (streaming) { streaming.classList.remove("streaming"); streaming = null; }
    const secs = ev.duration_ms ? (ev.duration_ms / 1000).toFixed(1) + "s" : "";
    const bits = [secs, turnTools ? `${turnTools} tool${turnTools === 1 ? "" : "s"}` : ""].filter(Boolean);
    if (bits.length) log("meta", bits.join(" · "));
    turnTools = 0;
  }
}

function escapeHtml(t) {
  return t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------------------------------------------------- the assistant */

state.ai = null;

function renderAI(c) {
  state.ai = c;
  const chip = $("ai-chip");
  const auth = c.auth || {};
  const signedIn = !!auth.loggedIn;
  const mode = c.auth_mode || "claude";
  const usingKey = mode === "apikey" && c.has_key;
  chip.classList.toggle("on", !!c.available);
  chip.classList.toggle("bad", !c.available && !!(c.reason && c.sdk === false));
  chip.classList.toggle("busy", !!c.busy);
  const model = (c.model || "opus").toUpperCase();
  if (c.available && c.backend === "claude-code") {
    const who = usingKey ? "API KEY" : (auth.subscriptionType || "claude").toUpperCase();
    chip.querySelector("i").textContent = "●";
    chip.querySelector("b").textContent = `CLAUDE · ${who} · ${model}`;
    chip.title = (usingKey ? `key ${c.key_hint || ""}` : (auth.email || "signed in"))
      + " — click to change";
  } else if (c.available) {
    chip.querySelector("i").textContent = "●";
    chip.querySelector("b").textContent = "CLAUDE · API";
    chip.title = "the Claude API, with a key from the environment";
  } else {
    chip.querySelector("i").textContent = "○";
    chip.querySelector("b").textContent = "NO ASSISTANT";
    chip.title = (c.reason || "nothing connected") + " — click to connect";
  }
  $("ai-model").hidden = !(c.available && c.backend === "claude-code");
  $("ai-model").value = c.model || "opus";
  $("ai-new").hidden = !c.available;
  $("send").disabled = !c.available || !!c.busy;
  $("stop").hidden = !c.busy;
  $("msg").placeholder = c.available
    ? "ask for a pattern, a kit, a melody…" : "connect an assistant to chat";
  if (!c.available && !state.connectDismissed) openConnect(true);
  renderProviders(c);
}

function openConnect(open) {
  $("connect").hidden = !open;
  if (open) renderProviders(state.ai || {});
}

function renderProviders(c) {
  const auth = c.auth || {};
  const mode = c.auth_mode || "claude";
  const cb = $("claude-body");
  $("prov-claude").classList.toggle("on", mode === "claude" && !!auth.loggedIn);
  $("prov-key").classList.toggle("on", mode === "apikey" && !!c.has_key);
  if (c.sdk === false) {
    cb.innerHTML = `<div class="dim">${escapeHtml(c.reason || "Claude Code is not installed")}</div>`;
  } else if (c.login_in_progress) {
    cb.innerHTML = `<div class="row"><span class="working">signing in — finish it in your browser</span>
        <button type="button" id="login-cancel">CANCEL</button></div>
      <div class="login-lines" id="login-lines">${c.login_url
        ? `no browser? open <a href="${escapeHtml(c.login_url)}" target="_blank" rel="noopener">${escapeHtml(c.login_url)}</a>` : ""}</div>`;
    $("login-cancel").addEventListener("click", () => api("/api/auth/cancel", {}).then(renderAI));
  } else if (auth.loggedIn) {
    cb.innerHTML = `<div class="row"><span class="who">${escapeHtml(auth.email || "signed in")}</span>
        <span class="sub">${escapeHtml((auth.subscriptionType || "claude").toUpperCase())}</span>
        ${mode !== "claude" ? '<button type="button" id="use-claude">USE THIS</button>' : '<span class="dim">in use</span>'}
        <button type="button" id="signout">SIGN OUT</button></div>`;
    const u = $("use-claude");
    if (u) u.addEventListener("click", () => api("/api/auth/mode", { mode: "claude" }).then(renderAI));
    $("signout").addEventListener("click", () => api("/api/auth/logout", {}).then(renderAI));
  } else {
    cb.innerHTML = `<div class="row"><button type="button" id="signin">SIGN IN WITH CLAUDE</button>
        <span class="dim">opens your browser; sign in with the account that has your subscription</span></div>
        <div class="login-lines" id="login-lines"></div>`;
    $("signin").addEventListener("click", async () => {
      try { renderAI(await api("/api/auth/login", {})); }
      catch (e) { log("err", e.message); }
    });
  }
  const km = $("key-msg");
  if (c.has_key) {
    km.className = "dim";
    km.innerHTML = `key saved (${escapeHtml(c.key_hint || "…")}) ${mode === "apikey" ? "— in use" : ""}
      ${mode !== "apikey" ? '<button type="button" id="use-key">USE THIS</button>' : ""}
      <button type="button" id="key-remove">REMOVE</button>`;
    const u = $("use-key");
    if (u) u.addEventListener("click", () => api("/api/auth/mode", { mode: "apikey" }).then(renderAI));
    $("key-remove").addEventListener("click", () => api("/api/auth/key", { key: "" }).then(renderAI));
  } else if (!km.dataset.live) {
    km.className = "dim"; km.textContent = "";
  }
}

$("ai-chip").addEventListener("click", () => {
  state.connectDismissed = !$("connect").hidden;
  openConnect($("connect").hidden);
});
$("ai-model").addEventListener("change", async (e) => {
  try { renderAI(await api("/api/chat/model", { model: e.target.value })); }
  catch (err) { log("err", err.message); }
});
$("ai-new").addEventListener("click", async () => {
  try { renderAI(await api("/api/chat/reset", {})); } catch (err) { log("err", err.message); }
});
$("stop").addEventListener("click", async () => {
  try { await api("/api/chat/stop", {}); log("sys", "stopping…"); } catch (err) { log("err", err.message); }
});
$("key-test").addEventListener("click", async () => {
  const km = $("key-msg"); km.dataset.live = "1";
  km.className = "dim"; km.textContent = "testing…";
  try {
    const r = await api("/api/auth/key/test", { key: $("key-in").value.trim() });
    km.className = r.ok ? "ok" : "bad";
    km.textContent = r.ok ? `works — ${r.model} answered in ${r.ms} ms` : `did not work: ${r.error}`;
  } catch (e) { km.className = "bad"; km.textContent = e.message; }
});
$("key-save").addEventListener("click", async () => {
  const km = $("key-msg"); km.dataset.live = "";
  try {
    const c = await api("/api/auth/key", { key: $("key-in").value.trim() });
    if (c.error) { km.className = "bad"; km.textContent = c.error; km.dataset.live = "1"; return; }
    $("key-in").value = "";
    renderAI(c);
    if (c.available) { openConnect(false); log("sys", "connected with your API key"); }
  } catch (e) { km.className = "bad"; km.textContent = e.message; km.dataset.live = "1"; }
});

function authEvent(ev) {
  if (ev.stage === "started") { openConnect(true); }
  else if (ev.stage === "line") {
    const box = $("login-lines");
    if (box) {
      if (ev.url && !box.querySelector("a"))
        box.innerHTML = `no browser? open <a href="${escapeHtml(ev.url)}" target="_blank" rel="noopener">${escapeHtml(ev.url)}</a>`;
    }
  } else if (ev.stage === "done") {
    const st = ev.status || {};
    if (st.loggedIn) {
      log("sys", `signed in as ${st.email || "you"} (${(st.subscriptionType || "claude").toUpperCase()})`);
      state.connectDismissed = true;
      openConnect(false);
    } else log("err", "sign-in did not complete");
    api("/api/chat/status", {}).then(renderAI).catch(() => {});
  }
}

$("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("msg");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  log("you", text);
  $("send").disabled = true; $("stop").hidden = false; $("ai-chip").classList.add("busy");
  turnTools = 0; turnStart = Date.now(); turnSaid = false;
  try {
    const r = await api("/api/chat", { message: text });
    if (r.error) { log("err", r.error); if (/no assistant|not signed in|no API key/i.test(r.error)) openConnect(true); }
    else if (r.reply && !turnSaid) log("bot", r.reply);   // the stream missed it
  } catch (err) {
    log("err", err.message);
  } finally {
    $("send").disabled = false; $("stop").hidden = true; $("ai-chip").classList.remove("busy");
    if (working) { working.remove(); working = null; }
    if (streaming) { streaming.classList.remove("streaming"); streaming = null; }
    input.focus();
  }
});

$("clear").addEventListener("click", () => { $("log").innerHTML = ""; });
$("notes").addEventListener("click", () => {
  state.showNotes = !state.showNotes;
  $("notes").setAttribute("aria-pressed", String(state.showNotes));
  renderGrid();
});
function renderHeard() {
  document.querySelectorAll("[data-variation]").forEach((b) => {
    b.classList.toggle("heard", b.dataset.variation === state.heardVariation);
  });
}

$("p-startstop").addEventListener("click", async () => {
  const action = state.playing ? "stop" : "start";
  try { await callTool("device.transport", { action }); }
  catch (e) { log("err", e.message); }
});

/* ───────────────── the sound of the selected instrument ───────────────── */

let swapAuditioned = null;       // tone id currently previewed, if any

function briefMeta(t) {
  const bits = [];
  if (t.root) bits.push(t.root);
  bits.push(t.sustained ? "sustain" : (t.decay_ms ? t.decay_ms + "ms" : ""));
  if (t.centroid) bits.push(t.centroid + "Hz");
  return bits.filter(Boolean).join(" · ");
}

async function renderSwap() {
  const inst = state.selected;
  const f = ((state.kit && state.kit.instruments) || {})[inst] || {};
  $("sw-inst").textContent = inst;
  const dzi = $("dz-inst"); if (dzi) dzi.textContent = inst;
  $("sw-name").textContent = f.tone_name || (f.tone != null ? "#" + f.tone : "—");
  $("sw-meta").textContent = briefMeta(f);
  const list = $("sw-list");
  list.innerHTML = "";
  if (!state.pattern || f.tone == null) return;
  let r;
  try {
    r = await callTool("kit.neighbours", { slot: state.pattern.kit, instrument: inst, limit: 6 });
  } catch (e) { return; }
  if (state.selected !== inst) return;          // the user moved on
  for (const t of r.neighbours) {
    const el = document.createElement("button");
    el.className = "swap-cand" + (t.melodic ? " mel" : "");
    el.dataset.tone = t.tone;
    el.innerHTML = `<b>${t.name}</b><i>${briefMeta(t)}</i>`;
    el.title = "click to hear it on " + inst + "; click again to keep it";
    list.appendChild(el);
  }
}

// Audition = assign for real, then play. There is no preview path on the
// machine: the only way to hear a tone on an instrument is to put it there.
// The previous tone is remembered so a second click keeps, and moving on
// restores -- so browsing sounds costs nothing.
let swapRestore = null;          // {inst, tone} to put back if not kept

async function audition(tone) {
  const inst = state.selected;
  const f = ((state.kit && state.kit.instruments) || {})[inst] || {};
  if (swapRestore === null) swapRestore = { inst, tone: f.tone };
  try {
    await callTool("kit.set_instrument", { slot: state.pattern.kit, instrument: inst, tone });
    await callTool("device.trigger", { instrument: inst, velocity: 110 });
    swapAuditioned = tone;
    document.querySelectorAll(".swap-cand").forEach((c) =>
      c.classList.toggle("trying", Number(c.dataset.tone) === tone));
    setStatus(`${inst}: trying tone ${tone} — click again to keep`);
  } catch (e) { log("err", e.message); }
}

async function keepAudition() {
  swapRestore = null; swapAuditioned = null;
  setStatus(`${state.selected}: kept`);
  await load(state.slot);
}

async function restoreAudition() {
  if (!swapRestore) return;
  const { inst, tone } = swapRestore;
  swapRestore = null; swapAuditioned = null;
  try { await callTool("kit.set_instrument", { slot: state.pattern.kit, instrument: inst, tone }); }
  catch (e) { /* best effort */ }
}

// Click-click: pick a sound, then click the instrument lane it belongs on.
// Armed state is visible on the strips (they become drop targets) and in a
// banner on the SOUND bar, so it never silently lingers. Clicking the same
// card again auditions it on the selected instrument instead.
let armed = null;                 // {tone, name}

function setArmed(a) {
  armed = a;
  $("sw-armed").hidden = !a;
  if (a) $("sw-armed-name").textContent = a.name;
  document.querySelectorAll(".swap-cand").forEach((c) =>
    c.classList.toggle("armed", !!a && Number(c.dataset.tone) === a.tone));
  document.querySelectorAll(".strip").forEach((s) => s.classList.toggle("target", !!a));
}

$("sw-list").addEventListener("click", async (e) => {
  const c = e.target.closest(".swap-cand");
  if (!c) return;
  const tone = Number(c.dataset.tone);
  const name = c.querySelector("b").textContent;
  if (armed && armed.tone === tone) {          // second click: hear it here
    await audition(tone);
    return;
  }
  if (swapAuditioned === tone) { await keepAudition(); return; }
  setArmed({ tone, name });
  setStatus(`holding ${name} — click an instrument lane`);
});
$("sw-disarm").addEventListener("click", () => { setArmed(null); setStatus("dropped"); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && armed) setArmed(null); });

async function placeArmed(inst) {
  const { tone, name } = armed;
  setArmed(null);
  try {
    await callTool("kit.set_instrument", { slot: state.pattern.kit, instrument: inst, tone });
    await callTool("device.trigger", { instrument: inst, velocity: 110 });
    setStatus(`${inst} -> ${name}`);
    await load(state.slot);
  } catch (err) { log("err", err.message); }
}
$("sw-audition").addEventListener("click", () =>
  callTool("device.trigger", { instrument: state.selected, velocity: 110 }).catch((e) => log("err", e.message)));
$("sw-browse").addEventListener("click", () => openPicker(state.selected));
$("sw-go").addEventListener("click", swapByWords);
$("sw-ask").addEventListener("keydown", (e) => { if (e.key === "Enter") swapByWords(); });

async function swapByWords() {
  const words = $("sw-ask").value.trim();
  if (!words || !state.pattern) return;
  const inst = state.selected;
  try {
    const r = await callTool("kit.swap", { slot: state.pattern.kit, instrument: inst, description: words, apply: false });
    const list = $("sw-list");
    list.innerHTML = "";
    if (!r.candidates.length) { log("sys", r.note || "nothing moves that way"); return; }
    for (const t of r.candidates) {
      const el = document.createElement("button");
      el.className = "swap-cand" + (t.melodic ? " mel" : "");
      el.dataset.tone = t.tone;
      el.innerHTML = `<b>${t.name}</b><i>${briefMeta(t)}</i>`;
      list.appendChild(el);
    }
    setStatus(`${inst}: ${r.candidates.length} tones that are ${words}`);
  } catch (e) { log("err", e.message); }
}

/* ───────────── a sample from disk: drop it, or pick it ───────────── */

async function uploadWav(file, inst) {
  if (!file || !state.pattern) return;
  if (!/\.wav$/i.test(file.name)) { log("err", `${file.name}: only .wav can go on the machine`); return; }
  setStatus(`sending ${file.name} to the machine as ${inst}…`);
  // reuse the slot the instrument already has if it is a user tone: sample
  // memory cannot be freed on this firmware, so recycling is the default
  const f = ((state.kit && state.kit.instruments) || {})[inst] || {};
  const reuse = f.tone >= 624 ? `&reuse_tone=${f.tone}` : "";
  const name = encodeURIComponent(file.name.replace(/\.wav$/i, "").slice(0, 16));
  try {
    const res = await fetch(`/api/upload?name=${name}&assign_to=${inst}${reuse}`,
      { method: "POST", body: await file.arrayBuffer() });
    const j = await res.json();
    if (j.error) throw new Error(j.error);
    setStatus(`${inst} <- ${j.result.name} (tone ${j.result.tone}${j.result.reused ? ", slot reused" : ""})`);
    (j.result.warnings || []).forEach((w) => log("sys", w));
    await callTool("device.trigger", { instrument: inst, velocity: 110 });
    await load(state.slot);
  } catch (e) { log("err", e.message); setStatus("upload failed"); }
}

const dz = $("dropzone");
dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
dz.addEventListener("dragleave", () => dz.classList.remove("over"));
dz.addEventListener("drop", (e) => {
  e.preventDefault(); dz.classList.remove("over");
  uploadWav(e.dataTransfer.files[0], state.selected);
});
$("sw-file").addEventListener("change", (e) => { uploadWav(e.target.files[0], state.selected); e.target.value = ""; });
// dropping straight onto an instrument lane puts it THERE
$("strips").addEventListener("dragover", (e) => {
  const strip = e.target.closest(".strip[data-inst]");
  if (!strip) return;
  e.preventDefault(); strip.classList.add("over");
});
$("strips").addEventListener("dragleave", (e) => {
  const strip = e.target.closest(".strip[data-inst]");
  if (strip) strip.classList.remove("over");
});
$("strips").addEventListener("drop", (e) => {
  const strip = e.target.closest(".strip[data-inst]");
  if (!strip) return;
  e.preventDefault(); strip.classList.remove("over");
  uploadWav(e.dataTransfer.files[0], strip.dataset.inst);
});

function renderFollowInst() {
  const el = $("r-finst");
  if (!el) return;
  el.className = "readout follow " + (state.followInst ? "ok" : "off");
  el.querySelector("b").textContent = state.followInst ? "ON" : "OFF";
  el.title = state.followInst
    ? "turning a knob selects that instrument — click to turn off"
    : "the selected instrument stays put when knobs move — click to turn on";
}

$("r-finst").addEventListener("click", () => {
  state.followInst = !state.followInst;
  try { localStorage.setItem("tr8s.followInst", state.followInst ? "1" : "0"); }
  catch (e) { /* storage may be unavailable; the toggle still works */ }
  renderFollowInst();
});
try { state.followInst = localStorage.getItem("tr8s.followInst") !== "0"; }
catch (e) { /* default on */ }
renderFollowInst();

function renderFollow(f) {
  if (f) state.follow = f;
  const el = $("r-follow");
  if (!el || !state.follow) return;
  const on = state.follow.on;
  const seen = state.follow.seen_program_change;
  el.className = "readout follow" + (on ? (seen ? " ok" : " waiting") : " off");
  el.querySelector("b").textContent = on ? (seen ? "ON" : "WAITING") : "OFF";
  const ch = state.follow.channel;
  const kc = state.follow.kit_channel;
  el.title = !on
    ? "not following the machine — click to turn on"
    : seen
      ? "following: selecting a pattern on the TR-8S loads it here"
        + (ch === null || ch === undefined ? ""
           : ` (pattern on channel ${ch + 1}`
             + (kc === null || kc === undefined ? ")" : `, kit on ${kc + 1})`))
      : "the TR-8S has not said which pattern it is on — click for the four "
        + "presses that fix it";
}

// Clicking the readout shows what to switch on when the machine has never
// spoken; once it has, it is a plain on/off toggle.
$("r-follow").addEventListener("click", async () => {
  if (state.follow && state.follow.on && !state.follow.seen_program_change) {
    openFollowHelp();
    return;
  }
  if (window.event && window.event.shiftKey) { openFollowHelp(); return; }
  try {
    const r = await api("/api/follow", { on: !(state.follow && state.follow.on) });
    renderFollow(r);
    log("sys", r.on ? "following the machine's pattern selection"
                    : "no longer following the machine");
  } catch (e) { log("err", e.message); }
});

/* ─────────────────── what the machine is sending ─────────────────── */

let midiTimer = null;

async function refreshMidi() {
  try {
    const r = await api("/api/midilog", { limit: 200 });
    state.midi = r;
    const sum = $("midi-summary");
    sum.innerHTML = "";
    if (!r.summary.length) {
      sum.innerHTML = '<span class="none">nothing has arrived yet</span>';
    } else {
      for (const s of r.summary) {
        const el = document.createElement("div");
        el.className = "msum";
        el.innerHTML = `<b>${s.kind}</b><span class="n">&times;${s.count}</span>`
          + `<span class="use">${s.used_for || ""}</span>`;
        sum.appendChild(el);
      }
    }
    $("midi-log").textContent = r.entries.map(
      (e) => `${String(e.at).padStart(9)}  ${e.kind.padEnd(11)}`
             + `${(e.detail || "").padEnd(26)} ${e.hex}`).join("\n")
      || "(nothing yet — press something on the machine)";
    $("midi-log").scrollTop = $("midi-log").scrollHeight;

    // say what is NOT arriving; that is usually the actual question
    const kinds = new Set(r.summary.map((s) => s.kind));
    const missing = [];
    if (!kinds.has("program"))
      missing.push("no <b>program change</b> — pattern following is off. "
        + "UTILITY &rarr; MIDI &rarr; Tx Prog Chg = ON, then [WRITE]");
    if (!kinds.has("control"))
      missing.push("no <b>control change</b> — knob and fader moves are not "
        + "being sent. UTILITY &rarr; MIDI &rarr; Tx EditData = ON");
    if (!kinds.has("note on"))
      missing.push("no <b>notes</b> — nothing is playing, so the variation "
        + "cannot be recognised");
    $("midi-hint").innerHTML = missing.length
      ? "Not seen: " + missing.join(" &middot; ")
      : "everything the studio can use is arriving.";
    const b = $("r-midi").querySelector("b");
    const total = r.summary.reduce((a, s) => a + s.count, 0);
    b.textContent = total ? String(total) : "—";
  } catch (e) { /* the panel is a diagnostic; never let it shout */ }
}

function openMidi() {
  $("midi").hidden = false;
  refreshMidi();
  if (midiTimer) clearInterval(midiTimer);
  midiTimer = setInterval(refreshMidi, 1000);
}

function closeMidi() {
  $("midi").hidden = true;
  if (midiTimer) { clearInterval(midiTimer); midiTimer = null; }
}

$("r-midi").addEventListener("click", openMidi);

/* ─────────────────── the tagged change log ─────────────────── */
let clTimer = null;
async function refreshLog() {
  try {
    const r = await api("/api/changelog", { limit: 200 });
    $("cl-on").checked = r.enabled;
    const b = $("r-log").querySelector("b"); if (b) b.textContent = String(r.count);
    const list = $("cl-list");
    if (!r.entries.length) { list.innerHTML = '<div class="cl-none">nothing yet</div>'; return; }
    const LABEL = { user: "you · panel", studio: "you · studio", ai: "AI", system: "system" };
    list.innerHTML = r.entries.map((e) => {
      const t = String(e.at).padStart(8);
      return `<div class="cl-row ${e.source}"><span class="cl-t">${t}</span>`
        + `<span class="cl-src">${LABEL[e.source] || e.source}</span>`
        + `<span class="cl-act">${e.action}${e.instrument ? " " + e.instrument : ""}</span>`
        + `<span class="cl-det">${e.detail || ""}</span></div>`;
    }).join("");
  } catch (e) { /* diagnostic; stay quiet */ }
}
function openLog() {
  $("changelog").hidden = false; refreshLog();
  if (clTimer) clearInterval(clTimer);
  clTimer = setInterval(refreshLog, 1500);
}
function closeLog() { $("changelog").hidden = true; if (clTimer) { clearInterval(clTimer); clTimer = null; } }
$("r-log").addEventListener("click", openLog);
$("cl-close").addEventListener("click", closeLog);
$("changelog").addEventListener("click", (e) => { if (e.target.id === "changelog") closeLog(); });
$("cl-clear").addEventListener("click", async () => { await api("/api/changelog", { clear: true }); refreshLog(); });
$("cl-on").addEventListener("change", async (e) => { await api("/api/changelog", { enabled: e.target.checked }); });
$("cl-copy").addEventListener("click", async () => {
  const r = await api("/api/changelog", { limit: 500 });
  try { await navigator.clipboard.writeText(r.text); setStatus("change log copied"); }
  catch (e) { setStatus("copy failed — clipboard blocked"); }
});
$("midi-close").addEventListener("click", closeMidi);
$("midi").addEventListener("click", (e) => {
  if (e.target.id === "midi") closeMidi();
});
$("midi-clear").addEventListener("click", async () => {
  await api("/api/midilog", { clear: true });
  refreshMidi();
});
$("midi-clock").addEventListener("change", async (e) => {
  await api("/api/midilog", { clock: e.target.checked });
  refreshMidi();
});
$("midi-copy").addEventListener("click", async () => {
  const r = await api("/api/midilog", { limit: 400 });
  try {
    await navigator.clipboard.writeText(r.text);
    setStatus("MIDI log copied");
  } catch (e) {
    // clipboard needs a secure context; select it instead so ctrl-C works
    const pre = $("midi-log");
    pre.textContent = r.text;
    const range = document.createRange();
    range.selectNodeContents(pre);
    const sel = window.getSelection();
    sel.removeAllRanges(); sel.addRange(range);
    setStatus("selected — press ctrl-C to copy");
  }
});

function setChk(id, ok, text) {
  const el = $(id);
  if (!el) return;
  el.className = "chk " + (ok === null ? "unknown" : ok ? "ok" : "todo");
  if (text !== undefined) el.querySelector(".state").textContent = text;
}

async function openFollowHelp() {
  try { await refreshMidi(); } catch (e) { /* diagnostics only */ }
  const f = state.follow || {};
  const seen = f.channels_seen || [];

  setChk("chk-progchg", !!f.seen_program_change,
    f.seen_program_change
      ? (f.channel === null || f.channel === undefined
          ? "working — program changes are arriving"
          : `working — pattern on channel ${f.channel + 1}`
            + (f.kit_channel === null || f.kit_channel === undefined ? ""
               : `, kit on ${f.kit_channel + 1}`))
      : "nothing has arrived yet — not switched on, or not touched since "
        + "the studio started");

  const heard = state.heardVariation;
  const playing = state.playing;
  setChk("chk-notes", heard ? true : (playing ? null : false),
    heard ? `working — currently hearing ${heard}`
          : playing ? "listening — needs a bar or so of a pattern it knows"
                    : "the pattern is not running, so there is nothing to hear");

  const sawCC = (state.midi && state.midi.summary || [])
    .some((x) => x.kind === "control");
  setChk("chk-edit", sawCC, sawCC
    ? "working — control changes are arriving"
    : "no control change has arrived; turn it on and move a knob");

  setChk("chk-motion", null);
  setChk("chk-ptn", null);
  setChk("chk-save", null);

  $("setup-channels").textContent = !seen.length
    ? "No Program Change has arrived yet."
    : (f.channel !== null && f.channel !== undefined
        ? `Pattern changes arrive on channel ${f.channel + 1}`
          + (f.kit_channel !== null && f.kit_channel !== undefined
             ? `, kit changes on ${f.kit_channel + 1}. Worked out by checking `
               + "which number named a pattern whose kit matched the other."
             : ".")
        : `Program Change has arrived on channel${seen.length > 1 ? "s" : ""} `
          + seen.map((c) => c + 1).join(", ")
          + (seen.length > 1 ? " — which is the pattern is still being worked "
                             + "out." : "."));
  const sel = $("fh-channel");
  sel.innerHTML = '<option value="">any</option>';
  for (let c = 0; c < 16; c++) {
    const o = document.createElement("option");
    o.value = String(c);
    o.textContent = String(c + 1) + (seen.includes(c) ? "  (seen)" : "");
    sel.appendChild(o);
  }
  sel.value = f.channel === null || f.channel === undefined ? "" : String(f.channel);
  $("setup").hidden = false;
}

$("setup-close").addEventListener("click", () => { $("setup").hidden = true; });
$("r-setup").addEventListener("click", () => { openFollowHelp(); });
$("setup").addEventListener("click", (e) => {
  if (e.target.id === "setup") $("setup").hidden = true;
});
$("fh-channel").addEventListener("change", async (e) => {
  const v = e.target.value;
  try {
    const r = await api("/api/follow", { channel: v === "" ? null : Number(v) });
    renderFollow(r);
    log("sys", v === "" ? "following program change on any channel"
                        : `following program change on channel ${Number(v) + 1}`);
  } catch (err) { log("err", err.message); }
});

function renderHistory(h) {
  if (h) state.history = h;
  const n = (state.history && state.history.undo) || 0;
  const b = $("undo");
  b.disabled = n === 0;
  b.title = n ? `put back what the last of ${n} edits overwrote`
              : "nothing to undo yet";
}

$("undo").addEventListener("click", async () => {
  $("undo").disabled = true;
  try {
    // shift-click redoes, so one button covers both directions
    const r = await api("/api/undo", { redo: window.event && window.event.shiftKey });
    setStatus((r.undone ? "undid " : "redid ") + (r.undone || r.redone));
    await load(state.slot);
  } catch (e) {
    log("err", e.message);
  } finally {
    renderHistory();
  }
});

$("commit").addEventListener("click", async () => {
  $("commit").disabled = true;
  try {
    const r = await api("/api/commit", {});
    state.dirty = false;
    $("write-state").textContent = " WRITE-saved to " + r.panel;
    setStatus("committed " + r.panel);
  } catch (e) {
    log("err", e.message);
    $("commit").disabled = false;
  }
});
$("load").addEventListener("click", () => load($("slot").value.trim()));
$("slot").addEventListener("keydown", (e) => {
  if (e.key === "Enter") load($("slot").value.trim());
});

/* ────────────────────────── live updates ────────────────────────── */

function setStatus(t) { $("status").textContent = t; }

function applyState(s) {
  state.instruments = s.instruments || [];
  state.variations = s.variations || [];
  renderHistory(s.history);
  renderFollow(s.follow);
  if (s.variation) {
    const was = state.heardVariation;
    state.heardVariation = s.variation.heard;
    // on first sight, show what the machine is actually playing rather than
    // leaving the view on A while the marker says otherwise
    if (state.heardVariation && was === undefined
        && state.heardVariation !== state.variation) {
      state.variation = state.heardVariation;
      renderVariations();
      if (state.view === "grid") renderGrid(); else renderPanel();
    }
    renderHeard();
  }
  const conn = $("r-conn");
  const was = state.connected;
  state.connected = !!s.connected;
  conn.className = "readout " + (s.connected ? "ok" : "bad");
  conn.querySelector("b").textContent = s.connected ? "UP" : "DOWN";
  if (was === true && !s.connected) {
    log("err", "device disconnected — " + ((s.info && s.info.error) || "")
      + " (retrying automatically)");
    setStatus("device lost — retrying");
  } else if (was === false && s.connected) {
    log("sys", "device reconnected");
    setStatus("reconnected");
  }
  $("r-fw").textContent = (s.info && s.info.firmware) || "—";
  $("hostinfo").textContent = (s.info && s.info.port) || "";
  if (s.kit) state.kit = s.kit;
  if (s.index && s.index.length) { state.index = s.index; }
  if (s.index_state) state.indexState = s.index_state;
  if (s.pattern) {
    state.pattern = s.pattern;
    state.slot = s.pattern.slot;
    if (s.pattern.panel) $("slot").value = s.pattern.panel;
    const withSteps = Object.keys(s.pattern.variations || {});
    if (!withSteps.includes(state.variation) && withSteps.length)
      state.variation = withSteps[0];
    renderMeta();
  }
  renderVariations(); renderKit();
  if (state.view === "grid") renderGrid(); else renderPanel();
  // applyState runs twice at boot (initial fetch, then the SSE hello); only
  if (s.chat) renderAI(s.chat);
  applyTransport(s.transport || {});
}

function applyTransport(t) {
  state.live = t.live || {};
  const was = state.playing;
  state.playing = !!t.playing;
  // on stop the stored pattern is the truth again: redraw from it once
  if (was && !state.playing) {
    if (state.view === "grid") renderGrid(); else renderPads();
  }
  paintLive();
  state.step = typeof t.step === "number" ? t.step : -1;
  $("r-bpm").textContent = t.bpm ? t.bpm.toFixed(1) : "—";
  $("r-pos").textContent = t.playing
    ? `${(t.bar ?? 0) + 1}.${(t.step ?? 0) + 1}` : "—";
  const run = $("r-run");
  run.className = "readout " + (t.playing ? "on" : "");
  run.querySelector("b").textContent = t.playing ? "PLAY" : "STOP";
  if (state.view === "grid") paintPlayhead(); else paintPanelLive();
}

function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => {
    let ev;
    try { ev = JSON.parse(e.data); } catch { return; }
    if (ev.type === "hello") { applyState(ev); setStatus("connected"); }
    else if (ev.type === "transport") applyTransport(ev);
    else if (ev.type === "variation") {
      // heard, not told: the machine never announces A-H
      if (ev.variation !== state.variation) {
        state.variation = ev.variation;
        renderVariations();
        if (state.view === "grid") renderGrid(); else renderPanel();
        setStatus(`heard variation ${ev.variation}`);
      }
      state.heardVariation = ev.variation;
      renderHeard();
    }
    else if (ev.type === "control") {
      // a knob or fader moved on the machine: move it here, and remember the
      // value so a redraw does not snap it back
      let touched = null;
      for (const c of ev.changes) {
        if (c.instrument) {
          const f = state.kit && state.kit.instruments
            && state.kit.instruments[c.instrument];
          if (f) f[c.param] = c.kit_value;
          // The fader always follows the physical fader, playing or not.
          // (Some patterns stream LEVEL as per-step accent automation, which
          // makes it jitter during playback; that is the real per-step level
          // and most patterns don't send it.) But LEVEL is the fader, which
          // players ride constantly, so it never moves the TRACK selection --
          // only the sound knobs (tune/decay/ctrl) do.
          moveControl(c.instrument, c.param, c.value);
          if (c.param !== "level") touched = c.instrument;
        } else {
          moveMaster(c.name, c.value);
        }
      }
      if (touched && state.followInst && touched !== state.selected) {
        state.selected = touched;
        renderStrips(); renderPads(); paintPanelLive();
      }
    }
    else if (ev.type === "focus") {
      // an instrument's part audibly changed while playing: a hand on that
      // row. Bring TRACK to it; the exact steps arrive with the read on stop.
      if (state.followInst && ev.instrument !== state.selected) {
        state.selected = ev.instrument;
        if (state.view === "grid") renderGrid();
        else { renderStrips(); renderPads(); paintPanelLive(); }
      }
      setStatus(`${ev.instrument} changed on the machine`);
    }
    else if (ev.type === "followed") {
      setStatus(`followed the machine to ${ev.panel}`);
      log("sys", ev.placeholder
        ? `the machine moved to ${ev.panel} (nothing known about it yet; it is read when the machine stops)`
        : `the machine moved to ${ev.panel}`);
    }
    else if (ev.type === "log") {
      log(ev.level === "err" ? "err" : "sys", ev.message);
    }
    else if (ev.type === "pattern") {
      state.pattern = ev.pattern; state.slot = ev.pattern.slot;
      if (ev.kit) state.kit = ev.kit;
      if (ev.pattern.panel) $("slot").value = ev.pattern.panel;
      // a step edit names its instrument — from the read-back diff (panel),
      // or the studio/AI edit that made it. Bring TRACK to it, wherever it
      // came from, when TRACK-follow is on.
      if (state.followInst && ev.changed && ev.changed.length
          && ev.changed[ev.changed.length - 1] !== state.selected) {
        state.selected = ev.changed[ev.changed.length - 1];
      }
      renderMeta(); renderVariations(); renderKit();
      renderHistory(ev.history);
      if (state.view === "grid") renderGrid(); else renderPanel();
      if (ev.from_machine) {
        setStatus(ev.changed && ev.changed.length
          ? `picked up an edit on ${ev.changed.join(", ")}`
          : "picked up an edit from the machine");
      }
    }
    else if (ev.type === "chat") chatEvent(ev.event || ev);
    else if (ev.type === "auth") authEvent(ev);
    else if (ev.type === "index") {
      for (const entry of ev.entries || []) {
        const i = state.index.findIndex((x) => x.slot === entry.slot);
        if (i >= 0) state.index[i] = entry; else state.index.push(entry);
      }
      state.index.sort((a, b) => a.slot - b.slot);
      if (ev.state) state.indexState = ev.state;
      else if (ev.done) state.indexState = "building";
      if (!$("browser").hidden) renderBrowser();
    }
  };
  es.onerror = () => setStatus("stream lost — retrying…");
}

(async function boot() {
  try {
    applyState(await api("/api/state"));
    setStatus("ready");
  } catch (e) {
    setStatus("server unreachable: " + e.message);
  }
  try { setView(localStorage.getItem("tr8s-view") || "panel"); }
  catch { setView("panel"); }
  connect();
  if (state.slot === null) load($("slot").value.trim());
  $("msg").focus();
})();
