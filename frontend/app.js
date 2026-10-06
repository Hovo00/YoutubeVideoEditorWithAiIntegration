const state = {
  projectId: null,
  duration: 0,
  cuts: [], // {start, end, text, reason, enabled}
  pollTimer: null,
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

  const response = await fetch("/api/upload", { method: "POST", body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    info.textContent = `Upload failed: ${err.detail || response.statusText}`;
    return;
  }

  const data = await response.json();
  state.projectId = data.project_id;
  state.duration = data.duration;

  info.textContent = `Loaded "${data.filename}" — duration ${formatTime(data.duration)}`;

  showStep("step2");
});

// --- Step 2: parse AI response ------------------------------------------

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

  const data = await response.json();

  state.cuts = data.cuts.map((c) => ({ ...c, enabled: true }));

  renderWarnings(data.warnings);
  renderSummary(data);
  renderCutsTable();

  showStep("step3");
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
