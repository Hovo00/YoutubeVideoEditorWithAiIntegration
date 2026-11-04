const state = {
  projectId: null,
  duration: 0,
  cuts: [], // {start, end, text, reason, enabled}
  pollTimer: null,
  cues: [], // {start, end, text} — raw Whisper cues, Mode 1
  outlineSections: [], // {level, title, start, end, body}
  chunks: [], // {text, start, end, slot_duration, title}
  ttsVoices: [], // {name, label, provider}
};

function formatTime(seconds) {
  seconds = Math.max(0, seconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = (seconds % 60).toFixed(1);
  return [
    hours.toString().padStart(2, "0"),
    minutes.toString().padStart(2, "0"),
    secs.padStart(4, "0"),
  ].join(":");
}

function showStep(id) {
  document.getElementById(id).style.display = "block";
}

// --- Settings (interface language — cosmetic only, see i18n.js) -----------

document.getElementById("uiLangSelect").value = getUiLanguage();

document.getElementById("settingsBtn").addEventListener("click", () => {
  const panel = document.getElementById("settingsPanel");
  panel.style.display = panel.style.display === "none" ? "block" : "none";
});

document.addEventListener("click", (e) => {
  const wrap = document.querySelector(".settings-wrap");
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById("settingsPanel").style.display = "none";
  }
});

document.getElementById("uiLangSelect").addEventListener("change", (e) => {
  setUiLanguage(e.target.value);
});

// --- Session persistence (survive a page reload without re-ingesting, ----
// which would otherwise wipe workspace/outline.md and cuts.md) -----------

const SESSION_KEY = "videoeditory_session";

function saveSession() {
  localStorage.setItem(
    SESSION_KEY,
    JSON.stringify({ projectId: state.projectId, duration: state.duration })
  );
}

function restoreSession() {
  const raw = localStorage.getItem(SESSION_KEY);
  if (!raw) return;

  let saved;
  try {
    saved = JSON.parse(raw);
  } catch {
    return;
  }
  if (!saved || !saved.projectId) return;

  state.projectId = saved.projectId;

  if (saved.duration) {
    state.duration = saved.duration;
    const preview = document.getElementById("preview");
    preview.src = "/api/workspace/video";
    preview.style.display = "block";
    document.getElementById("videoInfo").textContent =
      t("video_info_restored", { duration: formatTime(saved.duration) });
    showStep("stepEditMode");
    showEditMode(document.getElementById("editModeSelect").value);
  } else {
    // Ingestion was still in progress when the page was last open — resume
    // polling rather than assuming a workspace video already exists.
    document.getElementById("ingestStatus").textContent = t("ingest_status_resuming");
    pollIngestStatus();
  }
}

// --- Step 1: YouTube ingestion ------------------------------------------

document.getElementById("ingestBtn").addEventListener("click", async () => {
  const urlInput = document.getElementById("youtubeUrlInput");
  const url = urlInput.value.trim();
  if (!url) {
    alert(t("alert_need_url"));
    return;
  }

  const language = document.getElementById("languageSelect").value;
  if (!language) {
    alert(t("alert_need_language"));
    return;
  }

  const statusEl = document.getElementById("ingestStatus");
  statusEl.textContent = t("ingest_status_starting");

  const formData = new FormData();
  formData.append("youtube_url", url);
  formData.append("language", language);

  const response = await fetch("/api/ingest", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = t("ingest_status_could_not_start", { detail: err.detail || response.statusText });
    return;
  }

  const data = await response.json();
  state.projectId = data.project_id;
  state.duration = 0;
  saveSession();

  pollIngestStatus();
});

function pollIngestStatus() {
  if (state.pollTimer) clearInterval(state.pollTimer);

  const statusEl = document.getElementById("ingestStatus");
  const startedAt = Date.now();

  state.pollTimer = setInterval(async () => {
    const response = await fetch(`/api/status/${state.projectId}`);
    if (!response.ok) {
      clearInterval(state.pollTimer);
      statusEl.textContent = t("ingest_status_lost_track");
      return;
    }
    const data = await response.json();
    const elapsed = Math.round((Date.now() - startedAt) / 1000);

    if (data.status === "processing") {
      statusEl.textContent = t("ingest_status_elapsed", {
        message: data.phase_message || t("ingest_status_working"),
        elapsed,
      });
    } else if (data.status === "done") {
      clearInterval(state.pollTimer);
      state.duration = data.duration;
      saveSession();

      if (data.video_cached && data.transcript_cached) {
        statusEl.textContent = t("ingest_status_cached_both");
      } else if (data.video_cached) {
        statusEl.textContent = t("ingest_status_cached_video", { elapsed });
      } else {
        statusEl.textContent = t("ingest_status_transcribed", { elapsed });
      }

      const transcriptResponse = await fetch(`/api/project/${state.projectId}/transcript`);
      if (!transcriptResponse.ok) {
        statusEl.textContent = t("ingest_status_transcript_load_failed");
        return;
      }

      const preview = document.getElementById("preview");
      preview.src = "/api/workspace/video";
      preview.style.display = "block";
      document.getElementById("videoInfo").textContent =
        t("video_info_duration", { duration: formatTime(data.duration) });

      showStep("stepEditMode");
      showEditMode(document.getElementById("editModeSelect").value);
    } else if (data.status === "error") {
      clearInterval(state.pollTimer);
      statusEl.textContent = t("ingest_status_failed", { error: data.error });
    }
  }, 1500);
}

// --- Copy-paste prompts for Claude Desktop / claude terminal --------------

async function copyToClipboard(text, button) {
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    window.prompt("Copy this manually (clipboard access was blocked):", text);
    return;
  }
  button.textContent = t("copy_button_copied");
  setTimeout(() => {
    button.textContent = original;
  }, 1500);
}

// These prompts are sent to Claude verbatim, so they stay in English
// regardless of the UI language — the app's own interface language never
// changes what gets asked of Claude or what's expected back.
const MODE2_PROMPT =
  "Read AI_EDITING_INSTRUCTIONS.md in this project folder, then do Mode 2 " +
  "(build the corrected outline) exactly as it describes there.";

document.getElementById("copyOutlineBtn").addEventListener("click", (e) => {
  copyToClipboard(MODE2_PROMPT, e.currentTarget);
});

document.getElementById("copyAutonomousBtn").addEventListener("click", (e) => {
  const instruction = document.getElementById("autonomousInstructionInput").value.trim();
  if (!instruction) {
    alert(t("alert_need_instruction"));
    return;
  }
  const prompt =
    "Read AI_EDITING_INSTRUCTIONS.md in this project folder if you haven't " +
    "already this conversation, then do Mode 3 for this instruction: " +
    instruction;
  copyToClipboard(prompt, e.currentTarget);
});

// --- Edit-mode combobox ---------------------------------------------------

const EDIT_MODE_BLOCKS = {
  manual: "editModeManual",
  outline: "editModeOutline",
  autonomous: "editModeAutonomous",
};

function showEditMode(mode) {
  for (const [key, id] of Object.entries(EDIT_MODE_BLOCKS)) {
    document.getElementById(id).style.display = key === mode ? "block" : "none";
  }
  if (mode === "manual" && state.projectId && state.cues.length === 0) {
    loadCues();
  }
}

document.getElementById("editModeSelect").addEventListener("change", (e) => {
  showEditMode(e.target.value);
});
showEditMode(document.getElementById("editModeSelect").value);

// --- Edit mode 1 (manual): raw cue checkboxes -----------------------------
// The transcript is already sitting in the project the moment ingestion
// finishes (unlike the outline/cuts-file modes, which depend on an external
// Claude step run on your own schedule) — so this loads automatically as
// soon as Manual mode is shown, no "Load" button needed.

async function loadCues() {
  if (!state.projectId) return;

  const statusEl = document.getElementById("cuesStatus");
  const viewEl = document.getElementById("cuesView");
  statusEl.textContent = t("cues_status_loading");
  viewEl.innerHTML = "";

  const response = await fetch(`/api/project/${state.projectId}/cues`);

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = err.detail || response.statusText;
    return;
  }

  const data = await response.json();
  state.cues = data.cues;
  statusEl.textContent = t("cues_status_count", { count: data.cues.length });

  const preview = document.getElementById("preview");

  data.cues.forEach((cue, index) => {
    const row = document.createElement("div");
    row.className = "outline-section";

    const head = document.createElement("div");
    head.className = "outline-head";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "cue-checkbox";
    checkbox.dataset.index = String(index);

    const seekLink = document.createElement("a");
    seekLink.href = "#";
    seekLink.className = "outline-time";
    seekLink.textContent = `${formatTime(cue.start)} - ${formatTime(cue.end)}`;
    seekLink.addEventListener("click", (e) => {
      e.preventDefault();
      preview.currentTime = cue.start;
      preview.play();
    });

    const text = document.createElement("span");
    text.className = "outline-title";
    text.textContent = cue.text;

    head.append(checkbox, seekLink, text);
    row.append(head);
    viewEl.appendChild(row);
  });
}

document.getElementById("cutSelectedCuesBtn").addEventListener("click", async () => {
  if (!state.projectId) {
    alert(t("alert_need_video"));
    return;
  }

  const checked = Array.from(document.querySelectorAll(".cue-checkbox:checked"));
  if (checked.length === 0) {
    alert(t("alert_check_one_cue"));
    return;
  }

  const cues = checked.map((cb) => state.cues[Number(cb.dataset.index)]);

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append("cues_json", JSON.stringify(cues));

  const response = await fetch("/api/cues-cut", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    alert(t("alert_could_not_build_cuts", { detail: err.detail || response.statusText }));
    return;
  }

  applyCutsResponse(await response.json());
});

// --- Edit mode 2 (AI outline): load workspace/outline.md ------------------

document.getElementById("loadOutlineBtn").addEventListener("click", async () => {
  const statusEl = document.getElementById("outlineStatus");
  const viewEl = document.getElementById("outlineView");
  statusEl.textContent = t("outline_status_loading");
  viewEl.innerHTML = "";

  const response = await fetch("/api/workspace/outline");

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = err.detail || response.statusText;
    return;
  }

  const data = await response.json();
  state.outlineSections = data.sections;
  statusEl.textContent = data.sections.length
    ? t("outline_status_sections", { count: data.sections.length })
    : t("outline_status_empty");

  const preview = document.getElementById("preview");

  data.sections.forEach((section, index) => {
    const card = document.createElement("div");
    card.className = "outline-section" + (section.level === 3 ? " outline-sub" : "");

    const head = document.createElement("div");
    head.className = "outline-head";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "outline-checkbox";
    checkbox.dataset.index = String(index);

    const seekLink = document.createElement("a");
    seekLink.href = "#";
    seekLink.className = "outline-time";
    seekLink.textContent = `${formatTime(section.start)} - ${formatTime(section.end)}`;
    seekLink.addEventListener("click", (e) => {
      e.preventDefault();
      preview.currentTime = section.start;
      preview.play();
    });

    const title = document.createElement("span");
    title.className = "outline-title";
    title.textContent = section.title;

    head.append(checkbox, seekLink, title);

    const body = document.createElement("p");
    body.className = "outline-body";
    body.textContent = section.body;

    card.append(head, body);
    viewEl.appendChild(card);
  });
});

document.getElementById("cutSelectedSectionsBtn").addEventListener("click", async () => {
  if (!state.projectId) {
    alert(t("alert_need_video"));
    return;
  }

  const checked = Array.from(document.querySelectorAll(".outline-checkbox:checked"));
  if (checked.length === 0) {
    alert(t("alert_check_one_section"));
    return;
  }

  const sections = checked.map((cb) => state.outlineSections[Number(cb.dataset.index)]);

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append("sections_json", JSON.stringify(sections));

  const response = await fetch("/api/outline-cuts", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    alert(t("alert_could_not_build_cuts", { detail: err.detail || response.statusText }));
    return;
  }

  applyCutsResponse(await response.json());
});

// --- Edit mode 3 (AI autonomous): load workspace/cuts.md, or paste --------

document.getElementById("parseBtn").addEventListener("click", async () => {
  if (!state.projectId) {
    alert(t("alert_need_video"));
    return;
  }

  const aiResponse = document.getElementById("aiResponse").value;
  if (!aiResponse.trim()) {
    alert(t("alert_paste_ai_reply"));
    return;
  }

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append("ai_response", aiResponse);

  const response = await fetch("/api/parse", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    alert(t("alert_parsing_failed", { detail: err.detail || response.statusText }));
    return;
  }

  applyCutsResponse(await response.json());
});

document.getElementById("loadCutsFileBtn").addEventListener("click", async () => {
  if (!state.projectId) {
    alert(t("alert_need_video"));
    return;
  }

  const response = await fetch(`/api/workspace/cuts?project_id=${encodeURIComponent(state.projectId)}`);

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    alert(t("alert_could_not_load_cuts", { detail: err.detail || response.statusText }));
    return;
  }

  applyCutsResponse(await response.json());
});

// --- Cuts review (shared by all 3 edit modes) -----------------------------

function applyCutsResponse(data) {
  state.cuts = data.cuts.map((c) => ({ ...c, enabled: true }));
  renderWarnings(data.warnings);
  renderSummary(data);
  renderCutsTable();
  showStep("step3");
  showStep("stepAudioMode");

  document.getElementById("renderStatus").textContent = "";
  document.getElementById("downloadLink").style.display = "none";
  document.getElementById("resultPreview").style.display = "none";

  showAudioMode(document.getElementById("audioModeSelect").value);
}

function renderWarnings(warnings) {
  const el = document.getElementById("warnings");
  el.innerHTML = "";
  for (const warning of warnings || []) {
    const div = document.createElement("div");
    div.textContent = warning;
    el.appendChild(div);
  }
}

function renderSummary(data) {
  const el = document.getElementById("summary");
  el.innerHTML = t("summary_html", {
    original: formatTime(data.original_duration),
    count: state.cuts.length,
    removed: formatTime(data.removed_seconds),
    newDuration: formatTime(data.new_duration),
  });
}

function recalcNewDuration() {
  const removed = state.cuts
    .filter((c) => c.enabled)
    .reduce((sum, c) => sum + (c.end - c.start), 0);
  const el = document.getElementById("newDuration");
  if (el) {
    el.textContent = formatTime(state.duration - removed);
  }
}

function renderCutsTable() {
  const tbody = document.querySelector("#cutsTable tbody");
  tbody.innerHTML = "";

  state.cuts.forEach((cut, index) => {
    const tr = document.createElement("tr");

    const checkboxTd = document.createElement("td");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = cut.enabled;
    checkbox.addEventListener("change", () => {
      state.cuts[index].enabled = checkbox.checked;
      recalcNewDuration();
    });
    checkboxTd.appendChild(checkbox);

    const startTd = document.createElement("td");
    startTd.className = "time";
    startTd.textContent = formatTime(cut.start);

    const endTd = document.createElement("td");
    endTd.className = "time";
    endTd.textContent = formatTime(cut.end);

    const durTd = document.createElement("td");
    durTd.className = "time";
    durTd.textContent = (cut.end - cut.start).toFixed(1) + "s";

    const textTd = document.createElement("td");
    textTd.textContent = [cut.text, cut.reason].filter(Boolean).join(" — ");

    tr.append(checkboxTd, startTd, endTd, durTd, textTd);
    tbody.appendChild(tr);
  });
}

// --- Audio-mode combobox ---------------------------------------------------

const AUDIO_MODE_BLOCKS = {
  original: "audioModeOriginal",
  "auto-tts": "audioModeAuto",
  "manual-tts": "audioModeManual",
};

function showAudioMode(mode) {
  for (const [key, id] of Object.entries(AUDIO_MODE_BLOCKS)) {
    document.getElementById(id).style.display = key === mode ? "block" : "none";
  }
  if (mode === "auto-tts") {
    ensureTtsVoicesLoaded().then(populateAutoTtsVoiceSelect);
  }
}

document.getElementById("audioModeSelect").addEventListener("change", (e) => {
  showAudioMode(e.target.value);
});

document.getElementById("autoTtsRateRange").addEventListener("input", (e) => {
  document.getElementById("autoTtsRateValue").textContent = `${Number(e.target.value).toFixed(2)}x`;
});

async function ensureTtsVoicesLoaded() {
  if (state.ttsVoices.length === 0) {
    const response = await fetch("/api/tts/voices");
    if (response.ok) {
      state.ttsVoices = (await response.json()).voices;
    }
  }
  if (state.ttsVoices.some((v) => v.provider === "azure")) {
    refreshAzureUsage();
  }
  return state.ttsVoices;
}

function updateAutoTtsRateVisibility() {
  const select = document.getElementById("autoTtsVoiceSelect");
  const provider = select.selectedOptions[0]?.dataset.provider;
  const show = provider === "azure" ? "" : "none";
  document.getElementById("autoTtsRateRange").style.display = show;
  document.getElementById("autoTtsRateValue").style.display = show;
  document.querySelector('label[for="autoTtsRateRange"]').style.display = show;
}

function populateAutoTtsVoiceSelect() {
  const select = document.getElementById("autoTtsVoiceSelect");
  if (select.options.length === 0) {
    for (const voice of state.ttsVoices) {
      const option = document.createElement("option");
      option.value = voice.name;
      option.textContent = voice.label;
      option.dataset.provider = voice.provider;
      select.appendChild(option);
    }
    select.addEventListener("change", updateAutoTtsRateVisibility);
  }
  updateAutoTtsRateVisibility();
}

// --- Audio option 1: original audio (plain render) ------------------------

document.getElementById("renderBtn").addEventListener("click", async () => {
  const enabledCuts = state.cuts.filter((c) => c.enabled);

  if (enabledCuts.length === 0) {
    alert(t("alert_no_cuts_enabled"));
    return;
  }

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append(
    "cuts_json",
    JSON.stringify(enabledCuts.map((c) => ({ start: c.start, end: c.end })))
  );

  const statusEl = document.getElementById("renderStatus");
  statusEl.textContent = t("render_status_starting");

  const response = await fetch("/api/render", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = t("render_status_failed_start", { detail: err.detail || response.statusText });
    return;
  }

  pollRenderStatus();
});

// --- Audio option 2: automatic TTS ----------------------------------------

document.getElementById("autoTtsBtn").addEventListener("click", async () => {
  const enabledCuts = state.cuts.filter((c) => c.enabled);

  if (enabledCuts.length === 0) {
    alert(t("alert_no_cuts_enabled"));
    return;
  }

  const voice = document.getElementById("autoTtsVoiceSelect").value;
  if (!voice) {
    alert(t("alert_no_voices"));
    return;
  }

  const rate = document.getElementById("autoTtsRateRange").value;

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append(
    "cuts_json",
    JSON.stringify(enabledCuts.map((c) => ({ start: c.start, end: c.end })))
  );
  formData.append("voice", voice);
  formData.append("rate", rate);

  const statusEl = document.getElementById("renderStatus");
  statusEl.textContent = t("auto_tts_status_starting");

  const response = await fetch("/api/auto-tts", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = t("auto_tts_status_failed", { detail: err.detail || response.statusText });
    return;
  }

  pollRenderStatus();
});

// --- Audio option 3: manual TTS (voice-over text chunks) -------------------

document.getElementById("generateChunksBtn").addEventListener("click", async () => {
  if (!state.projectId) {
    alert(t("alert_need_video"));
    return;
  }

  const statusEl = document.getElementById("chunksStatus");
  statusEl.textContent = t("chunks_status_building");

  const enabledCuts = state.cuts.filter((c) => c.enabled);
  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append(
    "cuts_json",
    JSON.stringify(enabledCuts.map((c) => ({ start: c.start, end: c.end })))
  );

  const response = await fetch("/api/transcript-chunks", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = err.detail || response.statusText;
    return;
  }

  const data = await response.json();
  state.chunks = data.chunks;
  const modeNote = data.chunking_mode === "outline" ? t("mode_note_outline") : t("mode_note_fallback");
  statusEl.textContent = t("chunks_status_result", {
    count: data.chunks.length,
    kept: data.kept_cue_count,
    total: data.total_cue_count,
    modeNote,
  });

  await ensureTtsVoicesLoaded();
  renderChunks();
});

async function refreshAzureUsage() {
  const el = document.getElementById("azureUsageStatus");
  if (!el) return;

  const response = await fetch("/api/tts/azure-usage");
  if (!response.ok) return;

  const data = await response.json();
  const pct = ((data.characters_used / data.free_tier_limit) * 100).toFixed(2);
  el.textContent = t("azure_usage_text", {
    month: data.month,
    used: data.characters_used.toLocaleString(),
    limit: data.free_tier_limit.toLocaleString(),
    pct,
  });
  el.style.display = "block";
}

function showAudioFitResult(statusEl, result) {
  if (result.fits) {
    statusEl.textContent = t("audio_fit_ok", {
      audio: result.audio_duration.toFixed(1),
      slot: result.slot_duration.toFixed(1),
    });
    statusEl.classList.remove("warning");
  } else {
    statusEl.textContent = t("audio_fit_overflow", {
      audio: result.audio_duration.toFixed(1),
      slot: result.slot_duration.toFixed(1),
      overflow: result.overflow_seconds.toFixed(1),
    });
    statusEl.classList.add("warning");
  }
}

function renderChunks() {
  const viewEl = document.getElementById("chunksView");
  viewEl.innerHTML = "";

  state.chunks.forEach((chunk, index) => {
    const card = document.createElement("div");
    card.className = "chunk-card";

    const head = document.createElement("div");
    head.className = "chunk-head";

    const indexEl = document.createElement("span");
    indexEl.className = "chunk-index";
    indexEl.textContent = chunk.title || t("chunk_label", { n: index + 1 });

    const timeEl = document.createElement("span");
    timeEl.className = "chunk-time";
    timeEl.textContent = `${formatTime(chunk.start)} - ${formatTime(chunk.end)}`;

    const slotEl = document.createElement("span");
    slotEl.className = "chunk-slot";
    slotEl.textContent = t("slot_label", { duration: chunk.slot_duration.toFixed(1) });

    head.append(indexEl, timeEl, slotEl);

    const textEl = document.createElement("textarea");
    textEl.className = "chunk-text-input";
    textEl.value = chunk.text;
    textEl.rows = Math.min(10, Math.max(3, Math.ceil(chunk.text.length / 80)));

    const row = document.createElement("div");
    row.className = "row";

    const copyBtn = document.createElement("button");
    copyBtn.textContent = t("copy_text_button");
    copyBtn.addEventListener("click", () => copyToClipboard(textEl.value, copyBtn));

    const audioInput = document.createElement("input");
    audioInput.type = "file";
    audioInput.accept = "audio/*";

    const uploadBtn = document.createElement("button");
    uploadBtn.textContent = t("upload_voiceover_button");

    const audioStatus = document.createElement("div");
    audioStatus.className = "muted chunk-audio-status";

    const audioPlayer = document.createElement("audio");
    audioPlayer.controls = true;
    audioPlayer.className = "chunk-audio-player";
    audioPlayer.style.display = "none";

    function refreshAudioPlayer() {
      audioPlayer.src = `/api/transcript-chunks/audio/${index}?t=${Date.now()}`;
      audioPlayer.style.display = "block";
    }

    uploadBtn.addEventListener("click", async () => {
      const file = audioInput.files[0];
      if (!file) {
        alert(t("alert_choose_audio_file"));
        return;
      }

      audioStatus.textContent = t("audio_status_uploading");
      audioStatus.classList.remove("warning");

      const formData = new FormData();
      formData.append("project_id", state.projectId);
      formData.append("chunk_index", String(index));
      formData.append("slot_duration", String(chunk.slot_duration));
      formData.append("audio", file);

      const response = await fetch("/api/transcript-chunks/audio", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        audioStatus.textContent = t("audio_status_upload_failed", { detail: err.detail || response.statusText });
        audioStatus.classList.add("warning");
        return;
      }

      showAudioFitResult(audioStatus, await response.json());
      refreshAudioPlayer();
    });

    row.append(copyBtn, audioInput, uploadBtn);
    card.append(head, textEl, row, audioStatus, audioPlayer);

    if (state.ttsVoices.length > 0) {
      const ttsRow = document.createElement("div");
      ttsRow.className = "row";

      const voiceSelect = document.createElement("select");
      for (const voice of state.ttsVoices) {
        const option = document.createElement("option");
        option.value = voice.name;
        option.textContent = voice.label;
        option.dataset.provider = voice.provider;
        voiceSelect.appendChild(option);
      }

      const rateLabel = document.createElement("label");
      rateLabel.textContent = t("tts_speed_label");
      rateLabel.htmlFor = `chunkRate${index}`;

      const rateRange = document.createElement("input");
      rateRange.type = "range";
      rateRange.id = `chunkRate${index}`;
      rateRange.min = "0.5";
      rateRange.max = "1.5";
      rateRange.step = "0.05";
      rateRange.value = "1.0";

      const rateValue = document.createElement("span");
      rateValue.textContent = "1.00x";
      rateRange.addEventListener("input", () => {
        rateValue.textContent = `${Number(rateRange.value).toFixed(2)}x`;
      });

      function updateRateControlVisibility() {
        const provider = voiceSelect.selectedOptions[0]?.dataset.provider;
        const show = provider === "azure" ? "" : "none";
        rateLabel.style.display = show;
        rateRange.style.display = show;
        rateValue.style.display = show;
      }

      const generateBtn = document.createElement("button");

      function updateGenerateBtnLabel() {
        const provider = voiceSelect.selectedOptions[0]?.dataset.provider;
        generateBtn.textContent =
          provider === "azure" ? t("generate_with_azure_button") : t("generate_with_piper_button");
        updateRateControlVisibility();
      }
      updateGenerateBtnLabel();
      voiceSelect.addEventListener("change", updateGenerateBtnLabel);

      generateBtn.addEventListener("click", async () => {
        const provider = voiceSelect.selectedOptions[0]?.dataset.provider;
        generateBtn.disabled = true;
        audioStatus.textContent =
          provider === "azure" ? t("audio_status_generating_azure") : t("audio_status_generating_local");
        audioStatus.classList.remove("warning");

        const formData = new FormData();
        formData.append("project_id", state.projectId);
        formData.append("chunk_index", String(index));
        formData.append("text", textEl.value);
        formData.append("slot_duration", String(chunk.slot_duration));
        formData.append("voice", voiceSelect.value);
        formData.append("rate", rateRange.value);

        try {
          const response = await fetch("/api/transcript-chunks/tts", {
            method: "POST",
            body: formData,
          });

          if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            audioStatus.textContent = t("audio_status_generation_failed", { detail: err.detail || response.statusText });
            audioStatus.classList.add("warning");
            return;
          }

          showAudioFitResult(audioStatus, await response.json());
          refreshAudioPlayer();
          if (provider === "azure") refreshAzureUsage();
        } finally {
          generateBtn.disabled = false;
        }
      });

      ttsRow.append(voiceSelect, rateLabel, rateRange, rateValue, generateBtn);
      card.append(ttsRow);
    }

    viewEl.appendChild(card);
  });
}

document.getElementById("renderWithAudioBtn").addEventListener("click", async () => {
  const enabledCuts = state.cuts.filter((c) => c.enabled);

  if (enabledCuts.length === 0) {
    alert(t("alert_no_cuts_enabled"));
    return;
  }

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append(
    "cuts_json",
    JSON.stringify(enabledCuts.map((c) => ({ start: c.start, end: c.end })))
  );
  formData.append(
    "keep_original_audio",
    document.getElementById("cutOriginalAudioCheck").checked ? "false" : "true"
  );
  formData.append("music_db", document.getElementById("musicDbInput").value || "-5");

  if (document.getElementById("addMusicCheck").checked) {
    const musicFile = document.getElementById("musicInput").files[0];
    if (!musicFile) {
      alert(t("alert_add_music_check"));
      return;
    }
    formData.append("music", musicFile);
  }

  const statusEl = document.getElementById("renderStatus");
  statusEl.textContent = t("render_status_starting");

  const response = await fetch("/api/render-with-audio", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = t("render_status_failed_start", { detail: err.detail || response.statusText });
    return;
  }

  pollRenderStatus();
});

// --- Shared render/voice-over status polling -------------------------------

function pollRenderStatus() {
  if (state.pollTimer) clearInterval(state.pollTimer);

  const statusEl = document.getElementById("renderStatus");
  const startedAt = Date.now();

  state.pollTimer = setInterval(async () => {
    const response = await fetch(`/api/status/${state.projectId}`);
    const data = await response.json();

    const elapsed = Math.round((Date.now() - startedAt) / 1000);

    if (data.status === "done") {
      clearInterval(state.pollTimer);
      statusEl.textContent = t("render_status_done", { elapsed });

      const link = document.getElementById("downloadLink");
      link.href = data.download_url;
      link.style.display = "inline-block";

      const preview = document.getElementById("resultPreview");
      preview.src = data.download_url;
      preview.style.display = "block";

      // Automatic TTS can burn through Azure quota in one batch with no
      // per-chunk checkpoint to refresh it at — catch up once the render
      // (and any voice-over generation before it) has actually finished.
      if (state.ttsVoices.some((v) => v.provider === "azure")) {
        refreshAzureUsage();
      }
    } else if (data.status === "error") {
      clearInterval(state.pollTimer);
      statusEl.textContent = t("render_status_failed", { error: data.error });
    } else {
      statusEl.textContent = t("render_status_progress", {
        message: data.phase_message || t("render_status_rendering_fallback"),
        elapsed,
      });
    }
  }, 1500);
}

restoreSession();
