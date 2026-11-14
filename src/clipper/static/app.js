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
  data.append("hook", document.getElementById("hook").value);
  data.append("gemini_key", document.getElementById("gemini").value);
  data.append("groq_key", document.getElementById("groq").value);
  data.append("captions", document.getElementById("captions").value);
  data.append("punch", document.getElementById("punch").checked ? "1" : "0");
  data.append("loop", document.getElementById("loop").checked ? "1" : "0");
  const file = document.getElementById("file").files[0];
  if (file) data.append("file", file);
  const music = document.getElementById("music").files[0];
  if (music) data.append("music", music);

  try {
    const res = await fetch("/api/jobs", { method: "POST", body: data });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "Could not start");
    await poll(body.id);
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
