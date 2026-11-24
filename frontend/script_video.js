// Work type 3: a new video from a script (backend/script_video.py).
//
// Step 1 chooses what the user starts from. "script" hides the YouTube
// editing steps and shows: 2. the brief for Claude (Mode 6), 3. the scenes
// and their footage from Claude's shots.md (editable, downloaded by the
// app), 4. voice + music + render.

const START_MODE_KEY = "videoeditory_start_mode";
const EDIT_STEP_IDS = ["stepProject", "stepEditMode", "step3", "stepAddParts", "stepBroll", "stepAudioMode"];
const SV_STEP_IDS = ["svBrief", "svShots", "svRender"];

// Sent to Claude verbatim, so they stay in English (see app.js).
const MODE6_PROMPT =
  "Read AI_EDITING_INSTRUCTIONS.md in this project folder, then do Mode 6 " +
  "(video from a script) exactly as it describes there. The brief is " +
  "workspace/script_video/brief.md; write workspace/script_video/shots.md.";
const MODE6_CHECK_PROMPT =
  "Read AI_EDITING_INSTRUCTIONS.md in this project folder, then do the Mode 6 " +
  "footage check exactly as it describes there: look at the contact sheets in " +
  "workspace/script_video/sheets/ (README.md says which video each one is) and " +
  "fix the shots in workspace/script_video/shots.md.";

const sv = {
  plan: null, // {title, credits, scenes: [{title, text, shots: [...]}], problems}
  dirty: false,
  pollTimer: null,
  voicesLoaded: false,
};

// --- Start mode -------------------------------------------------------------

function startMode() {
  return document.querySelector('input[name="startMode"]:checked').value;
}

function setStartMode(mode, { remember = true } = {}) {
  document.querySelector(`input[name="startMode"][value="${mode}"]`).checked = true;
  if (remember) {
    try {
      localStorage.setItem(START_MODE_KEY, mode);
    } catch {}
  }
  const script = mode === "script";
  document.getElementById("editStartBlock").style.display = script ? "none" : "";
  for (const id of EDIT_STEP_IDS) {
    const el = document.getElementById(id);
    if (script) {
      // Remember which editing steps were open, to bring them back.
      if (el.dataset.svHidden === undefined) el.dataset.svHidden = el.style.display;
      el.style.display = "none";
    } else if (el.dataset.svHidden !== undefined) {
      el.style.display = el.dataset.svHidden;
      delete el.dataset.svHidden;
    }
  }
  document.getElementById("svBrief").style.display = script ? "block" : "none";
  document.getElementById("svShots").style.display = script && sv.plan ? "block" : "none";
  document.getElementById("svRender").style.display = script && sv.plan ? "block" : "none";
  if (script) {
    updateMaterialLabel();
    if (!sv.plan) loadShots({ quiet: true });
  }
}

document.querySelectorAll('input[name="startMode"]').forEach((input) => {
  input.addEventListener("change", () => setStartMode(input.value));
});

// --- Step 2: the brief --------------------------------------------------------

function updateMaterialLabel() {
  const source = document.getElementById("svSourceSelect").value;
  const label = document.getElementById("svMaterialLabel");
  label.dataset.i18n = {
    research: "sv_material_research_label",
    resources: "sv_material_resources_label",
    own: "sv_material_own_label",
  }[source];
  label.textContent = t(label.dataset.i18n);
}

document.getElementById("svSourceSelect").addEventListener("change", updateMaterialLabel);

document.getElementById("svCopyBriefBtn").addEventListener("click", async (e) => {
  const button = e.currentTarget;
  const status = document.getElementById("svBriefStatus");
  const formData = new FormData();
  formData.append("source", document.getElementById("svSourceSelect").value);
  formData.append("topic", document.getElementById("svTopicInput").value);
  formData.append("material", document.getElementById("svMaterialInput").value);
  formData.append("language", document.getElementById("svLanguageSelect").value);
  formData.append("minutes", document.getElementById("svMinutesInput").value || "3");
  const response = await fetch("/api/script-video/brief", { method: "POST", body: formData });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    status.textContent = t("sv_status_failed", { detail: err.detail || response.statusText });
    return;
  }
  await copyToClipboard(MODE6_PROMPT, button);
  status.textContent = t("sv_brief_saved");
});

document.getElementById("svLoadShotsBtn").addEventListener("click", () => loadShots());

async function loadShots({ quiet = false } = {}) {
  const status = document.getElementById("svBriefStatus");
  const response = await fetch("/api/script-video/shots");
  if (!response.ok) {
    if (!quiet) {
      const err = await response.json().catch(() => ({}));
      status.textContent = t("sv_status_failed", { detail: err.detail || response.statusText });
    }
    return;
  }
  showPlan(await response.json());
  if (!quiet) status.textContent = t("sv_loaded", { count: sv.plan.scenes.length });
}

async function loadBrief() {
  const response = await fetch("/api/script-video/brief");
  if (!response.ok) return;
  const data = await response.json();
  if (!data.exists) return;
  // Fill the form back from brief.md (written by the app, fixed layout).
  const text = data.text;
  const source = (text.match(/^- Script: (\w+)/m) || [])[1];
  if (source) document.getElementById("svSourceSelect").value = source;
  const language = (text.match(/^- Language of the voice-over: (\w+)/m) || [])[1];
  if (language) document.getElementById("svLanguageSelect").value = language;
  const minutes = (text.match(/^- Target length: about ([\d.]+)/m) || [])[1];
  if (minutes) document.getElementById("svMinutesInput").value = minutes;
  const topic = (text.match(/## Topic \/ instruction\n\n([\s\S]*?)\n\n(?=## |$)/) || [])[1];
  if (topic && !topic.startsWith("(none")) document.getElementById("svTopicInput").value = topic;
  const material = (text.match(/## (?:Script|Resources)\n\n([\s\S]*?)\n*$/) || [])[1];
  if (material) document.getElementById("svMaterialInput").value = material;
  updateMaterialLabel();
}

// --- Step 3: scenes and footage ----------------------------------------------

function formatSvTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const secs = (seconds - minutes * 60).toFixed(1).padStart(4, "0");
  return `${minutes}:${secs}`;
}

function parseSvTime(text) {
  const parts = text.trim().replace(",", ".").split(":").map(Number);
  if (parts.some((n) => Number.isNaN(n))) return null;
  return parts.reduce((total, n) => total * 60 + n, 0);
}

function showPlan(plan) {
  sv.plan = plan;
  sv.dirty = false;
  document.getElementById("svTitle").textContent = plan.title || "";
  const problems = document.getElementById("svProblems");
  problems.textContent = plan.problems.length ? t("sv_problems") + "\n" + plan.problems.join("\n") : "";
  problems.style.display = plan.problems.length ? "block" : "none";
  renderScenes();
  renderStats();
  if (startMode() === "script") {
    document.getElementById("svShots").style.display = "block";
    document.getElementById("svRender").style.display = "block";
    loadSvVoices();
    loadSvMusic();
  }
}

// Totals from the server: estimated length, video footage, and the target
// range (a sixth to a quarter of the video, e.g. 30–45 s of clips in 3 min).
function renderStats() {
  const stats = sv.plan.stats;
  const el = document.getElementById("svStats");
  if (!stats) {
    el.textContent = "";
    return;
  }
  const level = stats.footage < stats.target ? "low" : stats.footage > stats.target_max ? "high" : "ok";
  el.className = "sv-stats " + (level === "ok" ? "ok" : "low");
  el.textContent = t(`sv_stats_${level}`, {
    total: formatSvTime(stats.total).replace(/\.\d$/, ""),
    footage: Math.round(stats.footage),
    clips: stats.clips,
    target: Math.round(stats.target),
    target_max: Math.round(stats.target_max),
  });
}

function markDirty() {
  sv.dirty = true;
  document.getElementById("svShotsStatus").textContent = t("sv_unsaved");
}

function shotTimingText(shot) {
  return shot.kind === "video" ? `${formatSvTime(shot.start)}-${formatSvTime(shot.end)}` : `${shot.seconds ?? 3}`;
}

function renderScenes() {
  const container = document.getElementById("svScenes");
  container.innerHTML = "";
  sv.plan.scenes.forEach((scene, sceneIndex) => {
    const card = document.createElement("div");
    card.className = "sv-scene";

    const head = document.createElement("div");
    head.className = "sv-scene-head";
    const name = document.createElement("span");
    name.textContent = `${t("sv_scene")} ${sceneIndex + 1}${scene.title ? " · " + scene.title : ""}`;
    const words = document.createElement("span");
    words.className = "muted";
    // ~2.3 words a second for a calm voice-over.
    const seconds = Math.round(scene.text.split(/\s+/).filter(Boolean).length / 2.3);
    const footage = scene.shots
      .filter((s) => s.kind === "video")
      .reduce((sum, s) => sum + Math.min(sv.plan.max_clip || 4.5, s.end - s.start), 0);
    words.textContent = t("sv_scene_lengths", { seconds, footage: Math.round(footage) });
    head.append(name, words);

    const text = document.createElement("textarea");
    text.rows = Math.min(8, Math.max(2, Math.ceil(scene.text.length / 90)));
    text.value = scene.text;
    text.addEventListener("input", () => {
      scene.text = text.value;
      markDirty();
    });

    card.append(head, text);
    scene.shots.forEach((shot, shotIndex) => card.appendChild(renderShot(scene, shot, shotIndex)));
    container.appendChild(card);
  });
}

function renderShot(scene, shot, shotIndex) {
  const row = document.createElement("div");
  row.className = "sv-shot";

  let thumb;
  if (shot.thumb) {
    thumb = document.createElement("img");
    thumb.src = `/api/script-video/thumb/${encodeURIComponent(shot.thumb)}`;
  } else {
    thumb = document.createElement("div");
    thumb.textContent = t("sv_not_downloaded");
  }
  thumb.className = "sv-thumb";

  const body = document.createElement("div");
  body.className = "sv-shot-body";

  const line1 = document.createElement("div");
  line1.className = "sv-shot-line";
  const kind = document.createElement("span");
  kind.className = "sv-kind";
  kind.textContent = t(shot.kind === "video" ? "sv_kind_video" : "sv_kind_image");
  const link = document.createElement("a");
  link.className = "sv-link";
  link.href = shot.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = shot.url;
  const remove = document.createElement("button");
  remove.className = "link-btn";
  remove.textContent = t("sv_remove_shot");
  remove.addEventListener("click", () => {
    scene.shots.splice(shotIndex, 1);
    renderScenes();
    markDirty();
  });
  line1.append(kind, link, remove);

  const line2 = document.createElement("div");
  line2.className = "sv-shot-line";
  const timing = document.createElement("input");
  timing.type = "text";
  timing.className = "sv-timing";
  timing.value = shotTimingText(shot);
  timing.title = t(shot.kind === "video" ? "sv_timing_video_title" : "sv_timing_image_title");
  timing.addEventListener("change", () => {
    if (shot.kind === "video") {
      const [startText, endText] = timing.value.split(/\s*[-–]\s*/);
      const start = parseSvTime(startText || "");
      const end = parseSvTime(endText || "");
      if (start === null || end === null || end <= start) {
        timing.value = shotTimingText(shot);
        alert(t("sv_bad_timing"));
        return;
      }
      shot.start = start;
      shot.end = end;
    } else {
      const seconds = Number(timing.value.replace(",", "."));
      if (!(seconds > 0)) {
        timing.value = shotTimingText(shot);
        return;
      }
      shot.seconds = seconds;
    }
    markDirty();
  });
  const caption = document.createElement("input");
  caption.type = "text";
  caption.placeholder = t("sv_caption_placeholder");
  caption.value = shot.caption || "";
  caption.addEventListener("input", () => {
    shot.caption = caption.value;
    markDirty();
  });
  const title = document.createElement("input");
  title.type = "text";
  title.placeholder = t("sv_title_placeholder");
  title.value = shot.title || "";
  title.addEventListener("input", () => {
    shot.title = title.value;
    markDirty();
  });
  line2.append(timing, caption, title);

  if (shot.kind === "video") {
    const cropLabel = document.createElement("label");
    const crop = document.createElement("input");
    crop.type = "checkbox";
    crop.checked = !!shot.crop;
    crop.addEventListener("change", () => {
      shot.crop = crop.checked;
      markDirty();
    });
    cropLabel.append(crop, " ", t("sv_crop_label"));
    cropLabel.title = t("sv_crop_title");
    line2.appendChild(cropLabel);
  }

  body.append(line1, line2);
  row.append(thumb, body);
  return row;
}

async function saveShots() {
  const formData = new FormData();
  formData.append("plan_json", JSON.stringify(sv.plan));
  const response = await fetch("/api/script-video/shots", { method: "POST", body: formData });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    document.getElementById("svShotsStatus").textContent = t("sv_status_failed", { detail: err.detail || response.statusText });
    return false;
  }
  showPlan(await response.json());
  return true;
}

document.getElementById("svSaveBtn").addEventListener("click", async () => {
  if (await saveShots()) document.getElementById("svShotsStatus").textContent = t("sv_saved");
});

document.getElementById("svFetchBtn").addEventListener("click", async () => {
  if (sv.dirty && !(await saveShots())) return;
  const response = await fetch("/api/script-video/fetch", { method: "POST" });
  const status = document.getElementById("svShotsStatus");
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    status.textContent = t("sv_status_failed", { detail: err.detail || response.statusText });
    return;
  }
  pollSvJob(status);
});

document.getElementById("svCopyCheckBtn").addEventListener("click", (e) => {
  copyToClipboard(MODE6_CHECK_PROMPT, e.currentTarget);
});

// --- Background jobs (download / render) -------------------------------------

function pollSvJob(statusEl) {
  clearInterval(sv.pollTimer);
  sv.pollTimer = setInterval(async () => {
    const response = await fetch("/api/script-video/status");
    if (!response.ok) return;
    const job = await response.json();
    const pct = Math.round((job.progress || 0) * 100);
    if (["starting", "fetching", "voicing", "rendering"].includes(job.status)) {
      statusEl.textContent = `${job.message || t("sv_working")} (${pct}%)`;
      return;
    }
    clearInterval(sv.pollTimer);
    if (job.status === "error") {
      statusEl.textContent = t("sv_status_failed", { detail: job.error });
    } else if (job.status === "fetched") {
      statusEl.textContent = job.message ? job.message : t("sv_fetched");
      loadShots({ quiet: true });
    } else if (job.status === "done") {
      statusEl.textContent = t("sv_rendered");
      const link = document.getElementById("svDownloadLink");
      link.href = job.download_url;
      link.style.display = "inline-block";
      const credits = document.getElementById("svCreditsLink");
      credits.href = job.credits_url;
      credits.style.display = "inline-block";
      const preview = document.getElementById("svPreview");
      preview.src = job.download_url;
      preview.style.display = "block";
    }
  }, 1000);
}

// --- Step 4: voice, music, render ---------------------------------------------

const SV_DEFAULT_VOICES = { Russian: "ru_RU-dmitri-medium", English: "en_US-ryan-medium" };

async function loadSvVoices() {
  if (sv.voicesLoaded) return;
  const response = await fetch("/api/tts/voices");
  if (!response.ok) return;
  const { voices } = await response.json();
  const select = document.getElementById("svVoiceSelect");
  select.innerHTML = "";
  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = voice.name;
    option.textContent = voice.provider === "azure" ? `${voice.label} — Azure` : `${voice.label} — Piper (${t("sv_free")})`;
    select.appendChild(option);
  }
  // Free Piper voice in the brief's language by default.
  const preferred = SV_DEFAULT_VOICES[document.getElementById("svLanguageSelect").value];
  if (voices.some((v) => v.name === preferred)) select.value = preferred;
  sv.voicesLoaded = true;
}

async function loadSvMusic(selectName) {
  const response = await fetch("/api/music");
  if (!response.ok) return;
  const data = await response.json();
  const select = document.getElementById("svMusicSelect");
  const current = selectName ?? select.value;
  select.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.dataset.i18n = "host_music_none";
  none.textContent = t("host_music_none");
  select.appendChild(none);
  for (const name of data.tracks) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  }
  select.value = data.tracks.includes(current) ? current : "";
  updateSvMusicControls();
}

function updateSvMusicControls() {
  document.getElementById("svMusicVolume").style.display = document.getElementById("svMusicSelect").value ? "" : "none";
}

document.getElementById("svMusicSelect").addEventListener("change", updateSvMusicControls);

document.getElementById("svMusicAddBtn").addEventListener("click", () => {
  document.getElementById("svMusicFileInput").click();
});

document.getElementById("svMusicFileInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const formData = new FormData();
  formData.append("music", file);
  const response = await fetch("/api/music", { method: "POST", body: formData });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    alert(t("host_music_upload_failed", { detail: err.detail || response.statusText }));
    return;
  }
  loadSvMusic(file.name);
});

document.getElementById("svRenderBtn").addEventListener("click", async () => {
  const status = document.getElementById("svRenderStatus");
  if (sv.dirty && !(await saveShots())) return;
  if (!sv.plan.scenes.every((s) => s.shots.every((shot) => shot.status === "ready"))) {
    status.textContent = t("sv_need_download");
    return;
  }
  const voice = document.getElementById("svVoiceSelect").value;
  if (!voice) {
    alert(t("alert_no_voices"));
    return;
  }
  const formData = new FormData();
  formData.append("voice", voice);
  formData.append("music", document.getElementById("svMusicSelect").value);
  formData.append("music_db", document.getElementById("svMusicDbInput").value || "-24");
  formData.append("clip_effects", document.getElementById("svClipEffectsCheck").checked ? "true" : "false");
  document.getElementById("svDownloadLink").style.display = "none";
  document.getElementById("svCreditsLink").style.display = "none";
  document.getElementById("svPreview").style.display = "none";
  const response = await fetch("/api/script-video/render", { method: "POST", body: formData });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    status.textContent = t("sv_status_failed", { detail: err.detail || response.statusText });
    return;
  }
  pollSvJob(status);
});

// Scene cards are built in JS: rebuild them when the interface language changes.
document.getElementById("uiLangSelect").addEventListener("change", () => {
  if (sv.plan) renderScenes();
  updateMaterialLabel();
});

// --- Startup --------------------------------------------------------------------

loadBrief();
(function restoreStartMode() {
  let saved = null;
  try {
    saved = localStorage.getItem(START_MODE_KEY);
  } catch {}
  if (saved === "script") setStartMode("script", { remember: false });
})();
