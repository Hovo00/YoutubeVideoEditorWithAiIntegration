const state = {
  projectId: null,
  duration: 0,
  cuts: [], // {start, end, text, reason, enabled}
  pollTimer: null,
  outlineSections: [], // {level, title, start, end, body}
  chunks: [], // {text, start, end, slot_duration}
  ttsVoices: [], // {name, label}
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

// --- Session persistence (survive a page reload without re-uploading, ----
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
  state.duration = saved.duration;

  document.getElementById("preview").src = "/api/workspace/video";
  document.getElementById("videoInfo").textContent =
    `Restored previous session — duration ${formatTime(saved.duration)}`;

  showStep("stepOutline");
  showStep("step2");
}

// --- Step 1: load video -----------------------------------------------

document.getElementById("loadBtn").addEventListener("click", async () => {
  const input = document.getElementById("videoInput");
  const file = input.files[0];
  if (!file) {
    alert("Pick a video file first.");
    return;
  }

  const preview = document.getElementById("preview");
  preview.src = URL.createObjectURL(file);

  const info = document.getElementById("videoInfo");
  info.textContent = "Uploading...";

  const formData = new FormData();
  formData.append("video", file);

  const vttFile = document.getElementById("vttInput").files[0];
  if (vttFile) {
    formData.append("subtitles", vttFile);
  }

  const response = await fetch("/api/upload", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    info.textContent = `Upload failed: ${err.detail || response.statusText}`;
    return;
  }

  const data = await response.json();
  state.projectId = data.project_id;
  state.duration = data.duration;
  saveSession();

  info.textContent = `Loaded "${data.filename}" — duration ${formatTime(data.duration)}`;

  showStep("stepOutline");
  showStep("step2");
});

// --- Copy-paste prompts for Claude Desktop / claude terminal --------------

async function copyToClipboard(text, button) {
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    window.prompt("Copy this manually (clipboard access was blocked):", text);
    return;
  }
  button.textContent = "Copied!";
  setTimeout(() => {
    button.textContent = original;
  }, 1500);
}

const STEP1_PROMPT =
  "Read AI_EDITING_INSTRUCTIONS.md in this project folder, then do Step 1 " +
  "(generate the outline) exactly as it describes there.";

document.getElementById("copyStep1Btn").addEventListener("click", (e) => {
  copyToClipboard(STEP1_PROMPT, e.currentTarget);
});

document.getElementById("copyStep2Btn").addEventListener("click", (e) => {
  const instruction = document.getElementById("instructionInput").value.trim();
  if (!instruction) {
    alert("Type what you want changed first.");
    return;
  }
  const prompt =
    "Read AI_EDITING_INSTRUCTIONS.md in this project folder if you haven't " +
    "already this conversation, then do Step 2 for this instruction: " +
    instruction;
  copyToClipboard(prompt, e.currentTarget);
});

// --- Step 2 (outline): load workspace/outline.md ---------------------------

document.getElementById("loadOutlineBtn").addEventListener("click", async () => {
  const statusEl = document.getElementById("outlineStatus");
  const viewEl = document.getElementById("outlineView");
  statusEl.textContent = "Loading...";
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
    ? `${data.sections.length} section(s).`
    : "outline.md is empty so far.";

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

document.getElementById("cutSelectedBtn").addEventListener("click", async () => {
  if (!state.projectId) {
    alert("Load a video first.");
    return;
  }

  const checked = Array.from(document.querySelectorAll(".outline-checkbox:checked"));
  if (checked.length === 0) {
    alert("Check at least one paragraph or sub-paragraph to remove first.");
    return;
  }

  const sections = checked.map((cb) => state.outlineSections[Number(cb.dataset.index)]);

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append("sections_json", JSON.stringify(sections));

  const response = await fetch("/api/outline-cuts", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    alert(`Could not build cuts from selection: ${err.detail || response.statusText}`);
    return;
  }

  applyCutsResponse(await response.json());
});

// --- Step 2: generate or parse cuts --------------------------------------

function applyCutsResponse(data) {
  state.cuts = data.cuts.map((c) => ({ ...c, enabled: true }));
  renderWarnings(data.warnings);
  renderSummary(data);
  renderCutsTable();
  document.getElementById("refineBox").style.display = "flex";
  showStep("step3");
  showStep("step4");
}

document.getElementById("parseBtn").addEventListener("click", async () => {
  if (!state.projectId) {
    alert("Load a video first.");
    return;
  }

  const aiResponse = document.getElementById("aiResponse").value;
  if (!aiResponse.trim()) {
    alert("Paste the AI's reply first.");
    return;
  }

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append("ai_response", aiResponse);

  const response = await fetch("/api/parse", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    alert(`Parsing failed: ${err.detail || response.statusText}`);
    return;
  }

  applyCutsResponse(await response.json());
});

async function requestAiEdit(instruction, button, statusEl) {
  if (!state.projectId) {
    alert("Load a video first.");
    return;
  }
  if (!instruction.trim()) {
    alert("Type an instruction first.");
    return;
  }

  button.disabled = true;
  if (statusEl) statusEl.textContent = "Asking Claude... this can take a little while for long transcripts.";

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append("instruction", instruction);

  try {
    const response = await fetch("/api/ai-edit", { method: "POST", body: formData });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      const message = `Claude edit failed: ${err.detail || response.statusText}`;
      if (statusEl) statusEl.textContent = message;
      else alert(message);
      return;
    }

    const data = await response.json();
    if (statusEl) statusEl.textContent = "";
    applyCutsResponse(data);
  } finally {
    button.disabled = false;
  }
}

document.getElementById("generateBtn").addEventListener("click", () => {
  const instruction = document.getElementById("instructionInput").value;
  const button = document.getElementById("generateBtn");
  const statusEl = document.getElementById("aiEditStatus");
  requestAiEdit(instruction, button, statusEl);
});

document.getElementById("loadCutsFileBtn").addEventListener("click", async () => {
  if (!state.projectId) {
    alert("Load a video first.");
    return;
  }

  const response = await fetch(`/api/workspace/cuts?project_id=${encodeURIComponent(state.projectId)}`);

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    alert(`Could not load workspace/cuts.md: ${err.detail || response.statusText}`);
    return;
  }

  applyCutsResponse(await response.json());
});

document.getElementById("refineBtn").addEventListener("click", () => {
  const input = document.getElementById("refineInput");
  const button = document.getElementById("refineBtn");
  requestAiEdit(input.value, button, null).then(() => {
    input.value = "";
  });
});

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
  el.innerHTML = `
    Original duration: <b>${formatTime(data.original_duration)}</b> &nbsp;·&nbsp;
    Cuts found: <b>${state.cuts.length}</b> &nbsp;·&nbsp;
    Removed: <b>${formatTime(data.removed_seconds)}</b> &nbsp;·&nbsp;
    New duration (if all cuts kept enabled): <b id="newDuration">${formatTime(data.new_duration)}</b>
  `;
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

// --- Voice-over text chunks -------------------------------------------

document.getElementById("generateChunksBtn").addEventListener("click", async () => {
  if (!state.projectId) {
    alert("Load a video first.");
    return;
  }

  const statusEl = document.getElementById("chunksStatus");
  statusEl.textContent = "Building chunks...";

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
  const modeNote =
    data.chunking_mode === "outline"
      ? "One chunk per outline paragraph/sub-paragraph."
      : "No outline found — using ~500-character chunks instead. Run Step 1 with Claude first for paragraph-based chunks.";
  statusEl.textContent =
    `${data.chunks.length} chunk(s) — ${data.kept_cue_count} of ${data.total_cue_count} cues kept. ${modeNote} ` +
    "Toggling cuts above? Click this button again to refresh the chunks.";

  if (state.ttsVoices.length === 0) {
    const voicesResponse = await fetch("/api/tts/voices");
    if (voicesResponse.ok) {
      state.ttsVoices = (await voicesResponse.json()).voices;
    }
  }

  renderChunks();
});

function showAudioFitResult(statusEl, result) {
  if (result.fits) {
    statusEl.textContent =
      `Fits — audio is ${result.audio_duration.toFixed(1)}s, slot is ${result.slot_duration.toFixed(1)}s.`;
    statusEl.classList.remove("warning");
  } else {
    statusEl.textContent =
      `Too long — audio is ${result.audio_duration.toFixed(1)}s but the slot is only ` +
      `${result.slot_duration.toFixed(1)}s (${result.overflow_seconds.toFixed(1)}s over). ` +
      "Regenerate it shorter or it will be cut off.";
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
    indexEl.textContent = chunk.title || `Chunk ${index + 1}`;

    const timeEl = document.createElement("span");
    timeEl.className = "chunk-time";
    timeEl.textContent = `${formatTime(chunk.start)} - ${formatTime(chunk.end)}`;

    const slotEl = document.createElement("span");
    slotEl.className = "chunk-slot";
    slotEl.textContent = `slot: ${chunk.slot_duration.toFixed(1)}s`;

    head.append(indexEl, timeEl, slotEl);

    const textEl = document.createElement("textarea");
    textEl.className = "chunk-text-input";
    textEl.value = chunk.text;
    textEl.rows = Math.min(10, Math.max(3, Math.ceil(chunk.text.length / 80)));

    const row = document.createElement("div");
    row.className = "row";

    const copyBtn = document.createElement("button");
    copyBtn.textContent = "Copy text";
    copyBtn.addEventListener("click", () => copyToClipboard(textEl.value, copyBtn));

    const audioInput = document.createElement("input");
    audioInput.type = "file";
    audioInput.accept = "audio/*";

    const uploadBtn = document.createElement("button");
    uploadBtn.textContent = "Upload voice-over";

    const audioStatus = document.createElement("div");
    audioStatus.className = "muted chunk-audio-status";

    uploadBtn.addEventListener("click", async () => {
      const file = audioInput.files[0];
      if (!file) {
        alert("Choose an audio file first.");
        return;
      }

      audioStatus.textContent = "Uploading...";
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
        audioStatus.textContent = `Upload failed: ${err.detail || response.statusText}`;
        audioStatus.classList.add("warning");
        return;
      }

      showAudioFitResult(audioStatus, await response.json());
    });

    row.append(copyBtn, audioInput, uploadBtn);
    card.append(head, textEl, row, audioStatus);

    if (state.ttsVoices.length > 0) {
      const ttsRow = document.createElement("div");
      ttsRow.className = "row";

      const voiceSelect = document.createElement("select");
      for (const voice of state.ttsVoices) {
        const option = document.createElement("option");
        option.value = voice.name;
        option.textContent = voice.label;
        voiceSelect.appendChild(option);
      }

      const generateBtn = document.createElement("button");
      generateBtn.textContent = "Generate with Piper (free, local)";

      generateBtn.addEventListener("click", async () => {
        generateBtn.disabled = true;
        audioStatus.textContent = "Generating speech locally...";
        audioStatus.classList.remove("warning");

        const formData = new FormData();
        formData.append("project_id", state.projectId);
        formData.append("chunk_index", String(index));
        formData.append("text", textEl.value);
        formData.append("slot_duration", String(chunk.slot_duration));
        formData.append("voice", voiceSelect.value);

        try {
          const response = await fetch("/api/transcript-chunks/tts", {
            method: "POST",
            body: formData,
          });

          if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            audioStatus.textContent = `Generation failed: ${err.detail || response.statusText}`;
            audioStatus.classList.add("warning");
            return;
          }

          showAudioFitResult(audioStatus, await response.json());
        } finally {
          generateBtn.disabled = false;
        }
      });

      ttsRow.append(voiceSelect, generateBtn);
      card.append(ttsRow);
    }

    viewEl.appendChild(card);
  });
}

// --- Step 3: render -------------------------------------------------------

document.getElementById("renderBtn").addEventListener("click", async () => {
  const enabledCuts = state.cuts.filter((c) => c.enabled);

  if (enabledCuts.length === 0) {
    alert("No cuts are enabled — nothing to remove. Enable at least one cut, or there's nothing to render.");
    return;
  }

  const formData = new FormData();
  formData.append("project_id", state.projectId);
  formData.append(
    "cuts_json",
    JSON.stringify(enabledCuts.map((c) => ({ start: c.start, end: c.end })))
  );

  const statusEl = document.getElementById("renderStatus");
  statusEl.textContent = "Starting render...";

  const response = await fetch("/api/render", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = `Render failed to start: ${err.detail || response.statusText}`;
    return;
  }

  pollStatus();
});

document.getElementById("renderWithAudioBtn").addEventListener("click", async () => {
  const enabledCuts = state.cuts.filter((c) => c.enabled);

  if (enabledCuts.length === 0) {
    alert("No cuts are enabled — nothing to remove. Enable at least one cut, or there's nothing to render.");
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
      alert("Check \"Add background music\" and choose a music file, or uncheck it.");
      return;
    }
    formData.append("music", musicFile);
  }

  const statusEl = document.getElementById("renderStatus");
  statusEl.textContent = "Starting render...";

  const response = await fetch("/api/render-with-audio", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    statusEl.textContent = `Render failed to start: ${err.detail || response.statusText}`;
    return;
  }

  pollStatus();
});

function pollStatus() {
  if (state.pollTimer) clearInterval(state.pollTimer);

  const statusEl = document.getElementById("renderStatus");
  const startedAt = Date.now();

  state.pollTimer = setInterval(async () => {
    const response = await fetch(`/api/status/${state.projectId}`);
    const data = await response.json();

    const elapsed = Math.round((Date.now() - startedAt) / 1000);

    if (data.status === "rendering") {
      statusEl.textContent = `Rendering... (${elapsed}s elapsed, re-encoding can take a while for long videos)`;
    } else if (data.status === "done") {
      clearInterval(state.pollTimer);
      statusEl.textContent = `Done in ${elapsed}s.`;

      const link = document.getElementById("downloadLink");
      link.href = data.download_url;
      link.style.display = "inline-block";

      const preview = document.getElementById("resultPreview");
      preview.src = data.download_url;
      preview.style.display = "block";
    } else if (data.status === "error") {
      clearInterval(state.pollTimer);
      statusEl.textContent = `Render failed: ${data.error}`;
    }
  }, 1500);
}

restoreSession();
