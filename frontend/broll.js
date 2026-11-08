// --- Step 5 (optional): footage for the new parts ----------------------------
// While a new part is spoken the edited video pauses. Here the user picks what
// is shown during that pause: windows of the main video or of extra YouTube
// videos (picture only). Each part keeps an ordered list of clips
// {source_id, start, end}; the backend lays them back to back over the pause,
// trims the end to the real voice-over and holds the last frame if short.
//
// Loaded after app.js — uses its `state`, `t`, `formatTime`, `showStep`,
// `showAudioStep`.

const broll = {
  sources: [], // {id, title, status, progress, error, duration, has_filmstrip}
  parts: [], // {index, title, text, estimate_seconds, clips}
  openPart: null, // index of the part whose picker is open
  pollTimer: null,
  picker: null, // the open picker's live state (see openPicker)
  lastPosition: {}, // source_id -> where its last window ended
};

const CLIP_COLORS = ["#60a5fa", "#34d399", "#f472b6", "#a78bfa", "#fb923c", "#22d3ee", "#facc15", "#f87171"];
const MIN_CLIP_SECONDS = 0.5;
const RULER_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800];

function brollUrl(path) {
  return `/api/broll${path}`;
}

function sourceById(id) {
  return broll.sources.find((s) => s.id === id);
}

function sourceTitle(source) {
  if (!source) return "?";
  return source.id === "main" ? t("broll_source_main") : source.title;
}

function clipLength(clip) {
  return clip.end - clip.start;
}

function partFilled(part) {
  return part.clips.reduce((sum, c) => sum + clipLength(c), 0);
}

function fmtSeconds(seconds) {
  return seconds.toFixed(1);
}

async function postForm(url, fields) {
  const formData = new FormData();
  for (const [key, value] of Object.entries(fields)) formData.append(key, value);
  const response = await fetch(url, { method: "POST", body: formData });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || response.statusText);
  }
  return response.json();
}

// --- Step visibility ---------------------------------------------------------

async function showBrollStep() {
  document.getElementById("stepAudioMode").style.display = "none";
  showStep("stepBroll");
  document.getElementById("stepBroll").scrollIntoView({ behavior: "smooth" });

  const statusEl = document.getElementById("brollStatus");
  statusEl.textContent = t("broll_loading");
  closePicker();
  document.getElementById("brollParts").innerHTML = "";

  const response = await fetch(brollUrl(`?project_id=${encodeURIComponent(state.projectId)}`));
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = t("broll_load_failed", { detail: err.detail || response.statusText });
    return;
  }
  const data = await response.json();
  statusEl.textContent = "";
  broll.sources = data.sources;
  broll.parts = data.parts;
  renderSources();
  renderParts();
  pollSourcesIfNeeded();
}

function hideBrollStep() {
  closePicker();
  document.getElementById("stepBroll").style.display = "none";
}

document.getElementById("brollContinueBtn").addEventListener("click", () => {
  closePicker();
  showAudioStep();
  document.getElementById("stepAudioMode").scrollIntoView({ behavior: "smooth" });
});

// --- Sources -----------------------------------------------------------------

function renderSources() {
  const list = document.getElementById("brollSourceList");
  list.innerHTML = "";
  for (const source of broll.sources) {
    const chip = document.createElement("span");
    chip.className = "source-chip" + (source.status === "error" ? " error" : "");
    chip.title = source.error || source.url || "";

    const title = document.createElement("span");
    title.className = "chip-title";
    title.textContent = sourceTitle(source);
    chip.append(title);

    if (source.status !== "ready") {
      const stateEl = document.createElement("span");
      stateEl.className = "chip-state";
      stateEl.textContent =
        source.status === "error"
          ? t("broll_source_failed")
          : t("broll_source_downloading", { pct: Math.round((source.progress || 0) * 100) });
      chip.append(stateEl);
    } else if (source.duration) {
      const stateEl = document.createElement("span");
      stateEl.className = "chip-state";
      stateEl.textContent = formatTime(source.duration);
      chip.append(stateEl);
    }

    if (source.id !== "main") {
      const remove = document.createElement("button");
      remove.className = "chip-x";
      remove.textContent = "✕";
      remove.title = t("broll_remove_source_title");
      remove.addEventListener("click", () => removeSource(source.id));
      chip.append(remove);
    }
    list.appendChild(chip);
  }
}

function pollSourcesIfNeeded() {
  if (broll.pollTimer) return;
  if (!broll.sources.some((s) => s.status === "downloading")) return;

  broll.pollTimer = setInterval(async () => {
    const response = await fetch(brollUrl(`/sources?project_id=${encodeURIComponent(state.projectId)}`));
    if (!response.ok) return;
    const previous = new Map(broll.sources.map((s) => [s.id, s.status]));
    broll.sources = (await response.json()).sources;
    renderSources();

    const justReady = broll.sources.some((s) => s.status === "ready" && previous.get(s.id) === "downloading");
    if (justReady && broll.picker) renderPickerTabs();

    if (!broll.sources.some((s) => s.status === "downloading")) {
      clearInterval(broll.pollTimer);
      broll.pollTimer = null;
    }
  }, 1500);
}

document.getElementById("brollAddSourceBtn").addEventListener("click", addSourceFromInput);
document.getElementById("brollUrlInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") addSourceFromInput();
});

async function addSourceFromInput() {
  const input = document.getElementById("brollUrlInput");
  const url = input.value.trim();
  if (!url) {
    alert(t("alert_need_broll_url"));
    return;
  }
  try {
    const data = await postForm(brollUrl("/sources"), { project_id: state.projectId, url });
    broll.sources.push(data.source);
    input.value = "";
    renderSources();
    if (broll.picker) renderPickerTabs();
    pollSourcesIfNeeded();
  } catch (err) {
    document.getElementById("brollStatus").textContent = t("broll_add_source_failed", { detail: err.message });
  }
}

async function removeSource(sourceId) {
  try {
    const data = await postForm(brollUrl("/sources/remove"), { project_id: state.projectId, source_id: sourceId });
    broll.sources = data.sources;
    broll.parts = data.parts;
    if (broll.picker && broll.picker.sourceId === sourceId) broll.picker.sourceId = "main";
    renderSources();
    renderParts();
  } catch (err) {
    document.getElementById("brollStatus").textContent = t("broll_save_failed", { detail: err.message });
  }
}

// --- Parts and their clip lists ------------------------------------------------

function renderParts() {
  const container = document.getElementById("brollParts");
  // The picker lives inside the open part's card; keep it while re-rendering.
  const pickerEl = broll.picker ? broll.picker.el : null;
  if (pickerEl) pickerEl.remove();
  container.innerHTML = "";

  broll.parts.forEach((part) => {
    const card = document.createElement("div");
    card.className = "broll-part";
    card.dataset.part = String(part.index);

    const head = document.createElement("div");
    head.className = "chunk-head";
    const tag = document.createElement("span");
    tag.className = "added-tag";
    tag.textContent = t("added_tag");
    const title = document.createElement("span");
    title.className = "chunk-index";
    title.textContent = part.title;
    const needs = document.createElement("span");
    needs.className = "chunk-slot";
    needs.textContent = t("broll_needs", { seconds: fmtSeconds(part.estimate_seconds) });
    head.append(tag, title, needs);

    const body = document.createElement("p");
    body.className = "added-body";
    body.textContent = part.text;

    card.append(head, body, renderFillMeter(part), renderClipList(part));

    const row = document.createElement("div");
    row.className = "row";
    if (broll.openPart !== part.index) {
      const chooseBtn = document.createElement("button");
      chooseBtn.textContent = t("broll_choose_button");
      chooseBtn.addEventListener("click", () => openPicker(part.index));
      row.append(chooseBtn);
      card.append(row);
    }

    if (broll.openPart === part.index && pickerEl) card.append(pickerEl);
    container.appendChild(card);
  });
}

function renderFillMeter(part) {
  const wrap = document.createElement("div");
  const meter = document.createElement("div");
  meter.className = "fill-meter";
  const needed = part.estimate_seconds;
  const filled = partFilled(part);
  const scale = Math.max(needed, filled);
  part.clips.forEach((clip, i) => {
    const seg = document.createElement("span");
    seg.style.width = `${(clipLength(clip) / scale) * 100}%`;
    seg.style.background = CLIP_COLORS[i % CLIP_COLORS.length];
    meter.append(seg);
  });

  const label = document.createElement("div");
  label.className = "muted fill-label";
  if (!part.clips.length) {
    label.textContent = t("broll_no_clips");
  } else if (filled > needed + 0.05) {
    label.textContent = t("broll_filled_over", { filled: fmtSeconds(filled), needed: fmtSeconds(needed) });
  } else {
    label.textContent = t("broll_filled", { filled: fmtSeconds(filled), needed: fmtSeconds(needed) });
  }
  wrap.append(meter, label);
  return wrap;
}

function renderClipList(part) {
  const list = document.createElement("ul");
  list.className = "clip-list";
  part.clips.forEach((clip, i) => {
    const row = document.createElement("li");
    row.className = "clip-row";

    const swatch = document.createElement("span");
    swatch.className = "clip-swatch";
    swatch.style.background = CLIP_COLORS[i % CLIP_COLORS.length];

    const source = document.createElement("span");
    source.className = "clip-source";
    source.textContent = sourceTitle(sourceById(clip.source_id));

    const range = document.createElement("span");
    range.className = "clip-range";
    range.textContent = `${formatTime(clip.start)} → ${formatTime(clip.end)}  (${fmtSeconds(clipLength(clip))}s)`;

    const preview = iconButton("▶", t("broll_clip_preview_title"), () => {
      openPicker(part.index, { sourceId: clip.source_id, start: clip.start, end: clip.end, play: true });
    });
    const up = iconButton("↑", t("broll_clip_up_title"), () => moveClip(part, i, -1));
    up.disabled = i === 0;
    const down = iconButton("↓", t("broll_clip_down_title"), () => moveClip(part, i, 1));
    down.disabled = i === part.clips.length - 1;
    const remove = iconButton("✕", t("broll_clip_remove_title"), () => {
      saveClips(part, part.clips.filter((_, j) => j !== i));
    });

    row.append(swatch, source, range, preview, up, down, remove);
    list.append(row);
  });
  return list;
}

function iconButton(text, title, onClick) {
  const button = document.createElement("button");
  button.className = "icon-btn";
  button.textContent = text;
  button.title = title;
  button.addEventListener("click", onClick);
  return button;
}

function moveClip(part, index, delta) {
  const clips = part.clips.slice();
  const [clip] = clips.splice(index, 1);
  clips.splice(index + delta, 0, clip);
  saveClips(part, clips);
}

async function saveClips(part, clips) {
  try {
    const data = await postForm(brollUrl("/clips"), {
      project_id: state.projectId,
      part_index: String(part.index),
      clips_json: JSON.stringify(clips),
    });
    part.clips = data.clips;
    renderParts();
    if (broll.picker) drawPicker();
  } catch (err) {
    document.getElementById("brollStatus").textContent = t("broll_save_failed", { detail: err.message });
  }
}

// --- The picker ----------------------------------------------------------------
// A muted player over a zoomable timeline of the chosen source. The yellow
// window is the clip being picked: drag it to move, drag its edges to trim,
// click the strip to jump there. The player always shows the frame under
// whatever is being dragged, so picking works by eye.

function remainingSeconds(part) {
  return Math.max(MIN_CLIP_SECONDS, part.estimate_seconds - partFilled(part));
}

function openPicker(partIndex, focus) {
  const part = broll.parts.find((p) => p.index === partIndex);
  if (!part) return;
  closePicker();
  broll.openPart = partIndex;

  const el = buildPickerElement();
  broll.picker = {
    el,
    video: el.video,
    part,
    sourceId: (focus && focus.sourceId) || lastUsedSource(part) || "main",
    sel: null, // {start, end}
    view: null, // {start, end} visible part of the timeline
    drag: null,
    playing: false,
    seekPending: null,
    rafId: null,
  };
  renderParts();
  renderPickerTabs();
  loadPickerSource(broll.picker.sourceId, focus);
  el.focus({ preventScroll: true });
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function lastUsedSource(part) {
  const last = part.clips[part.clips.length - 1];
  return last && sourceById(last.source_id)?.status === "ready" ? last.source_id : null;
}

function closePicker() {
  const picker = broll.picker;
  if (!picker) return;
  cancelAnimationFrame(picker.rafId);
  picker.video.pause();
  picker.video.removeAttribute("src");
  picker.video.load();
  picker.el.remove();
  broll.picker = null;
  broll.openPart = null;
  renderParts();
}

function buildPickerElement() {
  const el = document.createElement("div");
  el.className = "picker";
  el.tabIndex = 0;
  el.innerHTML = `
    <div class="picker-tabs"></div>
    <video class="picker-video" muted playsinline preload="auto"></video>
    <div class="picker-transport">
      <button class="secondary-btn picker-play"></button>
      <span class="picker-readout"></span>
      <span class="spacer"></span>
      <label class="picker-length"><span></span><input type="number" min="${MIN_CLIP_SECONDS}" step="0.1" /> s</label>
      <button class="secondary-btn picker-fill"></button>
    </div>
    <div class="tl">
      <div class="tl-strip">
        <div class="tl-used-layer"></div>
        <div class="tl-sel"><span class="tl-sel-label"></span><div class="tl-handle left"></div><div class="tl-handle right"></div></div>
        <div class="tl-playhead"></div>
      </div>
      <div class="tl-ruler"></div>
      <div class="tl-overview"><div class="tl-overview-used-layer"></div><div class="tl-overview-sel"></div><div class="tl-overview-view"></div></div>
    </div>
    <div class="picker-tools">
      <button class="icon-btn zoom-out">−</button>
      <button class="icon-btn zoom-in">+</button>
      <button class="icon-btn zoom-fit">⤢</button>
      <span class="picker-hint"></span>
      <span class="spacer"></span>
      <button class="secondary-btn picker-close"></button>
      <button class="picker-add"></button>
    </div>`;

  const q = (selector) => el.querySelector(selector);
  q(".picker-play").textContent = t("broll_play_selection");
  q(".picker-length span").textContent = t("broll_length_label");
  q(".picker-fill").textContent = t("broll_fill_rest_button");
  q(".zoom-in").title = t("broll_zoom_in_title");
  q(".zoom-out").title = t("broll_zoom_out_title");
  q(".zoom-fit").title = t("broll_zoom_fit_title");
  q(".picker-hint").textContent = t("broll_keys_hint");
  q(".picker-close").textContent = t("broll_close_button");
  q(".picker-add").textContent = t("broll_add_clip_button");

  const video = q(".picker-video");
  // Stored on the element so the picker state can grab it.
  el.video = video;

  q(".picker-play").addEventListener("click", togglePlaySelection);
  video.addEventListener("click", togglePlaySelection);
  q(".picker-close").addEventListener("click", closePicker);
  q(".picker-add").addEventListener("click", addCurrentClip);
  q(".picker-fill").addEventListener("click", () => {
    const picker = broll.picker;
    setSelectionLength(remainingSeconds(picker.part));
  });
  q(".picker-length input").addEventListener("change", (e) => {
    const value = parseFloat(e.target.value);
    if (Number.isFinite(value)) setSelectionLength(value);
  });
  q(".zoom-in").addEventListener("click", () => zoomBy(0.5));
  q(".zoom-out").addEventListener("click", () => zoomBy(2));
  q(".zoom-fit").addEventListener("click", () => {
    const picker = broll.picker;
    picker.view = { start: 0, end: pickerDuration() };
    drawPicker();
  });

  const strip = q(".tl-strip");
  strip.addEventListener("pointerdown", onStripPointerDown);
  strip.addEventListener("wheel", onStripWheel, { passive: false });
  q(".tl-overview").addEventListener("pointerdown", onOverviewPointerDown);
  el.addEventListener("keydown", onPickerKey);
  window.addEventListener("resize", () => broll.picker && drawPicker());
  return el;
}

function renderPickerTabs() {
  const picker = broll.picker;
  if (!picker) return;
  const tabs = picker.el.querySelector(".picker-tabs");
  tabs.innerHTML = "";
  for (const source of broll.sources) {
    const tab = document.createElement("button");
    tab.className = "picker-tab" + (source.id === picker.sourceId ? " active" : "");
    tab.textContent = sourceTitle(source);
    tab.disabled = source.status !== "ready";
    tab.title = source.status === "ready" ? "" : t("broll_source_not_ready");
    tab.addEventListener("click", () => {
      if (source.id !== picker.sourceId) loadPickerSource(source.id);
    });
    tabs.append(tab);
  }
}

function pickerSource() {
  return sourceById(broll.picker.sourceId);
}

function pickerDuration() {
  const source = pickerSource();
  return (source && source.duration) || broll.picker.video.duration || 1;
}

function loadPickerSource(sourceId, focus) {
  const picker = broll.picker;
  const source = sourceById(sourceId);
  if (!source || source.status !== "ready") return;
  picker.sourceId = sourceId;
  renderPickerTabs();

  const base = brollUrl(`/sources/${encodeURIComponent(state.projectId)}/${encodeURIComponent(sourceId)}`);
  picker.video.pause();
  picker.playing = false;
  picker.video.src = `${base}/video`;

  const strip = picker.el.querySelector(".tl-strip");
  strip.style.backgroundImage = source.has_filmstrip ? `url("${base}/filmstrip")` : "none";

  const duration = source.duration;
  if (focus && focus.start != null) {
    picker.sel = { start: focus.start, end: focus.end };
  } else {
    const length = Math.min(remainingSeconds(picker.part), duration);
    const start = Math.min(broll.lastPosition[sourceId] || 0, Math.max(0, duration - length));
    picker.sel = { start, end: start + length };
  }
  // Open zoomed so the window is comfortably wide: ~6x its length, at
  // least a minute, never more than the whole video.
  const span = Math.min(duration, Math.max(60, (picker.sel.end - picker.sel.start) * 6));
  const center = (picker.sel.start + picker.sel.end) / 2;
  const viewStart = Math.min(Math.max(0, center - span / 2), duration - span);
  picker.view = { start: Math.max(0, viewStart), end: Math.max(0, viewStart) + span };

  const seekWhenReady = () => {
    seekVideo(picker.sel.start);
    if (focus && focus.play) playSelection();
  };
  if (picker.video.readyState >= 1) seekWhenReady();
  else picker.video.addEventListener("loadedmetadata", seekWhenReady, { once: true });

  drawPicker();
}

// --- Picker drawing --------------------------------------------------------------

function timeToX(time, width) {
  const view = broll.picker.view;
  return ((time - view.start) / (view.end - view.start)) * width;
}

function xToTime(x, width) {
  const view = broll.picker.view;
  return view.start + (x / width) * (view.end - view.start);
}

function drawPicker() {
  const picker = broll.picker;
  if (!picker || !picker.sel) return;
  const el = picker.el;
  const strip = el.querySelector(".tl-strip");
  const width = strip.clientWidth || 1;
  const duration = pickerDuration();
  const view = picker.view;
  const viewLength = view.end - view.start;

  // Filmstrip: the whole video's strip, scaled so the visible slice fills
  // the strip.
  const fullWidth = (width * duration) / viewLength;
  strip.style.backgroundSize = `${fullWidth}px 100%`;
  strip.style.backgroundPosition = `${-(view.start / duration) * fullWidth}px 0`;

  // Selection window.
  const selEl = el.querySelector(".tl-sel");
  const left = timeToX(picker.sel.start, width);
  const right = timeToX(picker.sel.end, width);
  selEl.style.left = `${left}px`;
  selEl.style.width = `${Math.max(0, right - left)}px`;
  const length = picker.sel.end - picker.sel.start;
  el.querySelector(".tl-sel-label").textContent = `${fmtSeconds(length)}s`;

  // Clips this part already uses from this source.
  const usedLayer = el.querySelector(".tl-used-layer");
  const overviewUsed = el.querySelector(".tl-overview-used-layer");
  usedLayer.innerHTML = "";
  overviewUsed.innerHTML = "";
  const overviewWidth = el.querySelector(".tl-overview").clientWidth || 1;
  picker.part.clips.forEach((clip, i) => {
    if (clip.source_id !== picker.sourceId) return;
    const color = CLIP_COLORS[i % CLIP_COLORS.length];
    const used = document.createElement("div");
    used.className = "tl-used";
    used.style.left = `${timeToX(clip.start, width)}px`;
    used.style.width = `${Math.max(2, timeToX(clip.end, width) - timeToX(clip.start, width))}px`;
    used.style.background = color;
    usedLayer.append(used);

    const mini = document.createElement("div");
    mini.className = "tl-overview-used";
    mini.style.left = `${(clip.start / duration) * overviewWidth}px`;
    mini.style.width = `${Math.max(2, (clipLength(clip) / duration) * overviewWidth)}px`;
    mini.style.background = color;
    overviewUsed.append(mini);
  });

  // Overview bar: where the zoomed view and the window are in the whole video.
  const viewEl = el.querySelector(".tl-overview-view");
  viewEl.style.left = `${(view.start / duration) * overviewWidth}px`;
  viewEl.style.width = `${(viewLength / duration) * overviewWidth}px`;
  const miniSel = el.querySelector(".tl-overview-sel");
  miniSel.style.left = `${(picker.sel.start / duration) * overviewWidth}px`;
  miniSel.style.width = `${(length / duration) * overviewWidth}px`;

  drawRuler(width);
  drawPlayhead();

  const input = el.querySelector(".picker-length input");
  if (document.activeElement !== input) input.value = length.toFixed(1);
  el.querySelector(".picker-readout").innerHTML =
    `<b>${formatTime(picker.sel.start)} → ${formatTime(picker.sel.end)}</b>`;
  el.querySelector(".picker-play").textContent = picker.playing ? t("broll_pause") : t("broll_play_selection");
}

function drawRuler(width) {
  const view = broll.picker.view;
  const ruler = broll.picker.el.querySelector(".tl-ruler");
  ruler.innerHTML = "";
  const viewLength = view.end - view.start;
  const step = RULER_STEPS.find((s) => (s / viewLength) * width >= 70) || RULER_STEPS[RULER_STEPS.length - 1];
  for (let time = Math.ceil(view.start / step) * step; time <= view.end; time += step) {
    const tick = document.createElement("div");
    tick.className = "tl-tick";
    tick.style.left = `${timeToX(time, width)}px`;
    const label = document.createElement("span");
    label.textContent = rulerLabel(time, step);
    tick.append(label);
    ruler.append(tick);
  }
}

function rulerLabel(time, step) {
  const minutes = Math.floor(time / 60);
  const seconds = time - minutes * 60;
  const secText = step < 1 ? seconds.toFixed(1).padStart(4, "0") : String(Math.round(seconds)).padStart(2, "0");
  return `${minutes}:${secText}`;
}

function drawPlayhead() {
  const picker = broll.picker;
  if (!picker) return;
  const strip = picker.el.querySelector(".tl-strip");
  const head = picker.el.querySelector(".tl-playhead");
  const time = picker.video.currentTime || 0;
  const view = picker.view;
  head.style.display = time >= view.start && time <= view.end ? "" : "none";
  head.style.left = `${timeToX(time, strip.clientWidth || 1)}px`;
}

// --- Picker interaction --------------------------------------------------------

function clampSelection(start, end) {
  const duration = pickerDuration();
  let length = Math.max(MIN_CLIP_SECONDS, end - start);
  length = Math.min(length, duration);
  start = Math.min(Math.max(0, start), duration - length);
  return { start, end: start + length };
}

// Seeking on every pointer move would flood the decoder; keep only the
// latest target and seek again once the previous seek lands.
function seekVideo(time) {
  const picker = broll.picker;
  if (!picker) return;
  const video = picker.video;
  if (video.seeking) {
    picker.seekPending = time;
    return;
  }
  video.currentTime = time;
  video.addEventListener(
    "seeked",
    () => {
      drawPlayhead();
      if (picker.seekPending != null) {
        const next = picker.seekPending;
        picker.seekPending = null;
        seekVideo(next);
      }
    },
    { once: true }
  );
}

function keepSelectionInView() {
  const picker = broll.picker;
  const view = picker.view;
  const viewLength = view.end - view.start;
  const duration = pickerDuration();
  let start = view.start;
  if (picker.sel.start < view.start) start = picker.sel.start - viewLength * 0.05;
  else if (picker.sel.end > view.end) start = picker.sel.end - viewLength * 0.95;
  start = Math.min(Math.max(0, start), Math.max(0, duration - viewLength));
  picker.view = { start, end: start + viewLength };
}

function onStripPointerDown(e) {
  const picker = broll.picker;
  if (!picker || !picker.sel) return;
  e.preventDefault();
  picker.el.focus({ preventScroll: true });
  stopPlayback();

  const strip = e.currentTarget;
  const rect = strip.getBoundingClientRect();
  const time = xToTime(e.clientX - rect.left, rect.width);
  const target = e.target;
  let mode;
  if (target.classList.contains("tl-handle")) {
    mode = target.classList.contains("left") ? "left" : "right";
  } else if (target.closest(".tl-sel")) {
    mode = "move";
  } else {
    // Clicked outside the window: centre the window there, then drag it.
    const length = picker.sel.end - picker.sel.start;
    picker.sel = clampSelection(time - length / 2, time + length / 2);
    seekVideo(picker.sel.start);
    drawPicker();
    mode = "move";
  }

  picker.drag = { mode, startTime: time, sel: { ...picker.sel }, rect };
  picker.el.querySelector(".tl-sel").classList.add("dragging");
  strip.setPointerCapture(e.pointerId);
  strip.addEventListener("pointermove", onStripPointerMove);
  strip.addEventListener("pointerup", onStripPointerUp, { once: true });
  strip.addEventListener("pointercancel", onStripPointerUp, { once: true });
}

function onStripPointerMove(e) {
  const picker = broll.picker;
  if (!picker || !picker.drag) return;
  const { mode, startTime, sel, rect } = picker.drag;
  const time = xToTime(e.clientX - rect.left, rect.width);
  const delta = time - startTime;
  const duration = pickerDuration();

  if (mode === "move") {
    picker.sel = clampSelection(sel.start + delta, sel.end + delta);
    seekVideo(picker.sel.start);
  } else if (mode === "left") {
    const start = Math.min(Math.max(0, sel.start + delta), sel.end - MIN_CLIP_SECONDS);
    picker.sel = { start, end: sel.end };
    seekVideo(start);
  } else {
    const end = Math.max(Math.min(duration, sel.end + delta), sel.start + MIN_CLIP_SECONDS);
    picker.sel = { start: sel.start, end };
    seekVideo(Math.max(sel.start, end - 0.04));
  }
  drawPicker();
}

function onStripPointerUp(e) {
  const picker = broll.picker;
  const strip = e.currentTarget;
  strip.removeEventListener("pointermove", onStripPointerMove);
  if (!picker) return;
  picker.drag = null;
  picker.el.querySelector(".tl-sel").classList.remove("dragging");
  keepSelectionInView();
  drawPicker();
}

function onStripWheel(e) {
  const picker = broll.picker;
  if (!picker) return;
  e.preventDefault();
  const rect = e.currentTarget.getBoundingClientRect();
  const anchor = xToTime(e.clientX - rect.left, rect.width);
  if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
    const viewLength = picker.view.end - picker.view.start;
    panView(((e.shiftKey ? e.deltaY : e.deltaX) / rect.width) * viewLength);
  } else {
    zoomBy(e.deltaY > 0 ? 1.25 : 0.8, anchor);
  }
}

function zoomBy(factor, anchor) {
  const picker = broll.picker;
  const duration = pickerDuration();
  const view = picker.view;
  const pivot = anchor != null ? anchor : (picker.sel.start + picker.sel.end) / 2;
  const viewLength = Math.min(duration, Math.max(2, (view.end - view.start) * factor));
  const ratio = (pivot - view.start) / (view.end - view.start);
  let start = pivot - ratio * viewLength;
  start = Math.min(Math.max(0, start), duration - viewLength);
  picker.view = { start, end: start + viewLength };
  drawPicker();
}

function panView(seconds) {
  const picker = broll.picker;
  const duration = pickerDuration();
  const viewLength = picker.view.end - picker.view.start;
  const start = Math.min(Math.max(0, picker.view.start + seconds), duration - viewLength);
  picker.view = { start, end: start + viewLength };
  drawPicker();
}

function onOverviewPointerDown(e) {
  const picker = broll.picker;
  if (!picker) return;
  e.preventDefault();
  const bar = e.currentTarget;
  const rect = bar.getBoundingClientRect();
  const duration = pickerDuration();
  const viewLength = picker.view.end - picker.view.start;

  const centreAt = (clientX) => {
    const time = ((clientX - rect.left) / rect.width) * duration;
    const start = Math.min(Math.max(0, time - viewLength / 2), duration - viewLength);
    picker.view = { start, end: start + viewLength };
    drawPicker();
  };
  centreAt(e.clientX);
  bar.setPointerCapture(e.pointerId);
  const move = (ev) => centreAt(ev.clientX);
  bar.addEventListener("pointermove", move);
  bar.addEventListener("pointerup", () => bar.removeEventListener("pointermove", move), { once: true });
}

function setSelectionLength(length) {
  const picker = broll.picker;
  picker.sel = clampSelection(picker.sel.start, picker.sel.start + length);
  keepSelectionInView();
  drawPicker();
}

function onPickerKey(e) {
  const picker = broll.picker;
  if (!picker || e.target.tagName === "INPUT") return;
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    e.preventDefault();
    const step = (e.shiftKey ? 1 : 0.1) * (e.key === "ArrowLeft" ? -1 : 1);
    picker.sel = clampSelection(picker.sel.start + step, picker.sel.end + step);
    seekVideo(picker.sel.start);
    keepSelectionInView();
    drawPicker();
  } else if (e.key === " ") {
    e.preventDefault();
    togglePlaySelection();
  } else if (e.key === "Enter") {
    e.preventDefault();
    addCurrentClip();
  } else if (e.key === "Escape") {
    closePicker();
  }
}

// --- Playback of the window --------------------------------------------------------

function togglePlaySelection() {
  if (!broll.picker) return;
  if (broll.picker.playing) stopPlayback();
  else playSelection();
}

function playSelection() {
  const picker = broll.picker;
  const video = picker.video;
  picker.playing = true;
  video.currentTime = picker.sel.start;
  video.play().catch(() => {
    picker.playing = false;
    drawPicker();
  });
  const tick = () => {
    if (!broll.picker || !picker.playing) return;
    if (video.currentTime >= picker.sel.end || video.ended) {
      stopPlayback();
      seekVideo(picker.sel.start);
      return;
    }
    drawPlayhead();
    picker.rafId = requestAnimationFrame(tick);
  };
  picker.rafId = requestAnimationFrame(tick);
  drawPicker();
}

function stopPlayback() {
  const picker = broll.picker;
  if (!picker) return;
  picker.playing = false;
  cancelAnimationFrame(picker.rafId);
  picker.video.pause();
  drawPicker();
}

async function addCurrentClip() {
  const picker = broll.picker;
  if (!picker || !picker.sel) return;
  stopPlayback();
  const clip = { source_id: picker.sourceId, start: picker.sel.start, end: picker.sel.end };
  broll.lastPosition[picker.sourceId] = clip.end;
  await saveClips(picker.part, [...picker.part.clips, clip]);

  // Ready for the next clip: continue right after this one, sized to what
  // is still missing.
  const current = broll.picker;
  if (!current) return;
  const length = Math.min(remainingSeconds(current.part), pickerDuration());
  current.sel = clampSelection(clip.end, clip.end + length);
  keepSelectionInView();
  seekVideo(current.sel.start);
  drawPicker();
}
