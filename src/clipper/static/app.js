
const recapForm = document.getElementById("recap-form");
const recapGo = document.getElementById("recap-go");
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b === btn));
    const tab = btn.getAttribute("data-tab");
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.getAttribute("data-panel") !== tab);
    });
  });
});
if (recapForm) {
  recapForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    recapGo.disabled = true;
    results.classList.add("hidden");
    results.innerHTML = "";
    progress.classList.remove("hidden");
    statusEl.className = "status";
    statusEl.textContent = "Starting recap…";
    logEl.textContent = "";
    const data = new FormData();
    data.append("url", document.getElementById("recap-url").value.trim());
    data.append("title", document.getElementById("recap-title").value.trim());
    data.append("format", document.getElementById("recap-format").value);
    data.append("voice", document.getElementById("recap-voice").value);
    data.append("grade", document.getElementById("recap-grade").value);
    data.append("model", document.getElementById("recap-model").value);
    data.append("plot_text", document.getElementById("recap-plot-text").value);
    data.append("spoilers", document.getElementById("recap-spoilers").checked ? "1" : "0");
    data.append("enqueue", document.getElementById("recap-enqueue").checked ? "1" : "0");
    const target = document.getElementById("recap-target").value;
    if (target) data.append("target_seconds", target);
    const file = document.getElementById("recap-file").files[0];
    if (file) data.append("file", file);
    const subs = document.getElementById("recap-subs").files[0];
    if (subs) {
      const name = (subs.name || "").toLowerCase();
      if (name.endsWith(".srt") || name.endsWith(".vtt")) data.append("subs", subs);
      else data.append("plot", subs);
    }
    const music = document.getElementById("recap-music").files[0];
    if (music) data.append("music", music);
    try {
      const res = await fetch("/api/recap", { method: "POST", body: data });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "Could not start recap");
      await poll(body.id);
    } catch (err) {
      statusEl.className = "status err";
      statusEl.textContent = err.message || String(err);
    } finally {
      recapGo.disabled = false;
    }
  });
}

const form = document.getElementById("form");
const go = document.getElementById("go");
const progress = document.getElementById("progress");
const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const results = document.getElementById("results");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  go.disabled = true;
  results.classList.add("hidden");
  results.innerHTML = "";
  progress.classList.remove("hidden");
  statusEl.className = "status";
  statusEl.textContent = "Starting…";
  logEl.textContent = "";

  const data = new FormData();
  data.append("url", document.getElementById("url").value.trim());
  data.append("count", document.getElementById("count").value);
  data.append("preset", document.getElementById("preset").value);
  data.append("layout", document.getElementById("layout").value);
  data.append("grade", document.getElementById("grade").value);
  data.append("style", document.getElementById("style").value);
  data.append("model", document.getElementById("model").value);
  data.append("language", document.getElementById("language").value);
  data.append("brief", document.getElementById("brief").value);
  data.append("hook", document.getElementById("hook").value);
  data.append("gemini_key", document.getElementById("gemini").value);
  data.append("groq_key", document.getElementById("groq").value);
  data.append("captions", document.getElementById("captions").value);
  data.append("punch", document.getElementById("punch").checked ? "1" : "0");
  data.append("loop", document.getElementById("loop").checked ? "1" : "0");
  data.append("auto_music", document.getElementById("auto_music").checked ? "1" : "0");
  data.append("sfx", document.getElementById("sfx").checked ? "1" : "0");
  data.append("enqueue", document.getElementById("enqueue").checked ? "1" : "0");
  const file = document.getElementById("file").files[0];
  if (file) data.append("file", file);
  const music = document.getElementById("music").files[0];
  if (music) data.append("music", music);

  try {
    const res = await fetch("/api/jobs", { method: "POST", body: data });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "Could not start");
    await poll(body.id);
    loadQueue();
  } catch (err) {
    statusEl.className = "status err";
    statusEl.textContent = err.message || String(err);
  } finally {
    go.disabled = false;
  }
});

async function poll(id) {
  for (;;) {
    const res = await fetch(`/api/jobs/${id}`);
    const job = await res.json();
    statusEl.textContent = job.message || job.status;
    logEl.textContent = (job.log || []).join("\n");
    logEl.scrollTop = logEl.scrollHeight;
    if (job.status === "done") {
      statusEl.className = "status ok";
      renderClips(id, job.clips || []);
      return;
    }
    if (job.status === "error") {
      statusEl.className = "status err";
      throw new Error(job.message || "Job failed");
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
}

function renderClips(jobId, clips) {
  results.classList.remove("hidden");
  if (!clips.length) {
    results.innerHTML = "<p>No clips were produced.</p>";
    return;
  }
  results.innerHTML = clips.map((c) => {
    const fileUrl = `/api/jobs/${jobId}/file?path=${encodeURIComponent(c.path)}`;
    const txtUrl = `/api/jobs/${jobId}/file?path=${encodeURIComponent(c.sidecar)}`;
    const tags = (c.hashtags || []).map((t) => "#" + t.replace(/^#/, "")).join(" ");
    return `<article class="clip">
      <div class="clip-grid">
        <video src="${fileUrl}" controls playsinline></video>
        <div class="meta">
          <h3>${escapeHtml(c.title || "Clip " + c.index)}</h3>
          <p>${escapeHtml(c.description || "")}</p>
          <p class="tags">${escapeHtml(tags)}</p>
          <p>${c.start.toFixed(1)}s – ${c.end.toFixed(1)}s · ${c.duration.toFixed(1)}s${c.preset ? " · " + escapeHtml(c.preset) : ""}${c.layout ? " · " + escapeHtml(c.layout) : ""}</p>
          ${c.hook ? `<p>Hook: ${escapeHtml(c.hook)}</p>` : ""}
          ${c.queue_id ? `<p>Queue id: ${escapeHtml(c.queue_id)} (pending review)</p>` : ""}
          ${(c.title_options && c.title_options.length) ? `<p>Title options: ${escapeHtml(c.title_options.join(" · "))}</p>` : ""}
          <p>
            <a class="dl" href="${fileUrl}" download>Download MP4</a>
            <a class="dl" href="${txtUrl}" download>Title & hashtags</a>
          </p>
        </div>
      </div>
    </article>`;
  }).join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
}

async function loadSettings() {
  const res = await fetch("/api/settings");
  const s = await res.json();
  document.getElementById("publish_method").value = s.publish_method || "buffer";
  document.getElementById("per_day").value = s.per_day || 3;
  document.getElementById("schedule_times").value = (s.schedule_times || []).join(", ");
  document.getElementById("github_repo").value = s.github_repo || "";
  document.getElementById("buffer_channel_id").value = s.buffer_channel_id || "";
  document.getElementById("draft_only").checked = s.draft_only !== false;
  document.getElementById("autopilot").checked = !!s.autopilot;
  if (s.model) document.getElementById("model").value = s.model;
  if (s.language) document.getElementById("language").value = s.language;
  const capEl = document.getElementById("autofind_daily_cap");
  if (capEl) capEl.value = s.autofind_daily_cap || 8;
  const intEl = document.getElementById("autofind_interval_hours");
  if (intEl) intEl.value = s.autofind_interval_hours || 6;
  const enEl = document.getElementById("autofind_enabled");
  if (enEl) enEl.checked = !!s.autofind_enabled;
  const keys = [];
  if (s.has_gemini_key) keys.push("Gemini");
  if (s.has_groq_key) keys.push("Groq");
  if (s.has_buffer_key) keys.push("Buffer");
  if (s.has_github_token) keys.push("GitHub token");
  if (s.has_youtube_oauth) keys.push("YouTube OAuth");
  const status = document.getElementById("key-status");
  status.textContent = keys.length
    ? "Keys found in .env: " + keys.join(", ") + ". Values are never shown."
    : "No API keys in .env. Heuristic hooks still work. Add free Gemini/Groq/Buffer keys locally if you want them.";
}

document.getElementById("save-settings").addEventListener("click", async () => {
  const times = document.getElementById("schedule_times").value.split(/[,\s]+/).filter(Boolean);
  const payload = {
    publish_method: document.getElementById("publish_method").value,
    per_day: Number(document.getElementById("per_day").value) || 3,
    schedule_times: times,
    github_repo: document.getElementById("github_repo").value.trim(),
    buffer_channel_id: document.getElementById("buffer_channel_id").value.trim(),
    draft_only: document.getElementById("draft_only").checked,
    autopilot: document.getElementById("autopilot").checked,
    autofind_enabled: !!(document.getElementById("autofind_enabled") && document.getElementById("autofind_enabled").checked),
    autofind_daily_cap: Number((document.getElementById("autofind_daily_cap") || {}).value) || 8,
    autofind_interval_hours: Number((document.getElementById("autofind_interval_hours") || {}).value) || 6,
  };
  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const el = document.getElementById("settings-status");
  el.textContent = res.ok ? "Settings saved. Secrets stay in .env only." : "Could not save settings.";
});

document.getElementById("load-channels").addEventListener("click", async () => {
  const status = document.getElementById("channel-status");
  status.textContent = "Loading…";
  const res = await fetch("/api/buffer/channels");
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    status.textContent = body.detail || "Could not load channels.";
    return;
  }
  const channels = body.channels || [];
  status.textContent = channels.length
    ? channels.map((c) => `${c.displayName || c.name} (${c.service}) — ${c.id}`).join(" · ")
    : "No channels returned. Connect YouTube in Buffer first.";
  const yt = channels.find((c) => String(c.service || "").toLowerCase().includes("youtube"));
  if (yt && !document.getElementById("buffer_channel_id").value) {
    document.getElementById("buffer_channel_id").value = yt.id;
  }
});

async function loadQueue() {
  const box = document.getElementById("queue-list");
  const res = await fetch("/api/queue");
  const body = await res.json();
  const items = body.items || [];
  if (!items.length) {
    box.innerHTML = "<p class='hint'>Queue is empty. New clips show up here for review.</p>";
    return;
  }
  box.innerHTML = items.slice().reverse().map((item) => {
    return `<div class="queue-item">
      <div>
        <strong>${escapeHtml(item.title || item.path || item.id)}</strong>
        <span class="pill">${escapeHtml(item.status)}</span>
        <div class="hint">${escapeHtml(item.id)}${item.due_at ? " · due " + escapeHtml(item.due_at) : ""}${item.error ? " · " + escapeHtml(item.error) : ""}${item.source_label ? " · source " + escapeHtml(item.source_label) : ""}${item.license ? " · licence " + escapeHtml(item.license) : ""}</div>
      </div>
      <div class="queue-actions">
        ${item.status === "pending_review" ? `<button type="button" data-act="approve" data-id="${item.id}">Approve</button>` : ""}
        ${item.status === "pending_review" ? `<button type="button" class="secondary" data-act="reject" data-id="${item.id}">Reject</button>` : ""}
        ${item.status === "approved" ? `<button type="button" data-act="publish" data-id="${item.id}">Send as draft</button>` : ""}
      </div>
    </div>`;
  }).join("");
  box.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      await fetch(`/api/queue/${btn.dataset.id}/${btn.dataset.act}?draft=1`, { method: "POST" });
      loadQueue();
    });
  });
}

loadSettings().catch(() => {});
loadQueue().catch(() => {});


async function loadSources() {
  const box = document.getElementById("source-list");
  const cap = document.getElementById("source-cap");
  if (!box) return;
  const res = await fetch("/api/sources");
  const body = await res.json();
  if (cap) cap.textContent = `Daily cap: ${body.used_today || 0}/${body.daily_cap || 8} used today (Asia/Calcutta). Remaining: ${body.remaining ?? 0}.`;
  const sources = body.sources || [];
  if (!sources.length) {
    box.innerHTML = "<p class='hint'>No watched sources yet. Add a channel, playlist, brief link, keyword, or trailer title.</p>";
    return;
  }
  box.innerHTML = sources.map((s) => {
    const flags = [s.cc_only ? "CC-only" : "", s.recap ? "recap" : ""].filter(Boolean).join(", ");
    return `<div class="queue-item">
      <div>
        <strong>${escapeHtml(s.label || s.query)}</strong>
        <span class="pill">${escapeHtml(s.kind || "")}</span>
        <div class="hint">${escapeHtml(s.query)}${flags ? " · " + escapeHtml(flags) : ""}</div>
      </div>
      <div class="queue-actions">
        <button type="button" class="secondary" data-rm="${s.id}">Remove</button>
      </div>
    </div>`;
  }).join("");
  box.querySelectorAll("button[data-rm]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      await fetch(`/api/sources/${btn.dataset.rm}/remove`, { method: "POST" });
      loadSources();
    });
  });
}

const addBtn = document.getElementById("source-add");
if (addBtn) {
  addBtn.addEventListener("click", async () => {
    const status = document.getElementById("source-status");
    const query = document.getElementById("source-query").value.trim();
    if (!query) {
      status.textContent = "Add a URL, keyword, or title first.";
      return;
    }
    const payload = {
      kind: document.getElementById("source-kind").value,
      query,
      cc_only: document.getElementById("source-cc").checked,
      recap: document.getElementById("source-recap").checked || document.getElementById("source-kind").value === "trailer",
    };
    const res = await fetch("/api/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    status.textContent = res.ok ? "Source saved." : "Could not save source.";
    if (res.ok) document.getElementById("source-query").value = "";
    loadSources();
  });
}
const runBtn = document.getElementById("source-run");
if (runBtn) {
  runBtn.addEventListener("click", async () => {
    const status = document.getElementById("source-status");
    status.textContent = "Checking sources…";
    runBtn.disabled = true;
    try {
      const res = await fetch("/api/find/run", { method: "POST" });
      const body = await res.json().catch(() => ({}));
      const n = (body.items || []).length;
      status.textContent = n ? `Queued ${n} new draft(s) for review.` : "Nothing new, or the daily cap is used.";
      loadSources();
      loadQueue();
    } finally {
      runBtn.disabled = false;
    }
  });
}
loadSources().catch(() => {});
