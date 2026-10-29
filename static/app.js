const $ = (id) => document.getElementById(id);
const statusEl = $("status");

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("err", isError);
}

// Random per-browser ID: the server only shows documents added from this browser
function getSessionId() {
  const make = () => (crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join(""));
  try {
    let id = localStorage.getItem("docchat-session");
    if (!id) {
      id = make();
      localStorage.setItem("docchat-session", id);
    }
    return id;
  } catch {
    return make(); // storage blocked: session lasts until the page is closed
  }
}
const SESSION_ID = getSessionId();

function withSession(options) {
  return { ...options, headers: { ...options.headers, "X-Session-Id": SESSION_ID } };
}

async function api(path, options = {}) {
  const res = await fetch(path, withSession(options));
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

// ---------- Documents ----------

function expiresIn(epochSeconds) {
  const mins = Math.max(0, Math.round((epochSeconds * 1000 - Date.now()) / 60000));
  return mins >= 60 ? `expires in ${Math.round(mins / 60)}h` : `expires in ${mins}m`;
}

async function showLimits() {
  const l = await api("/api/limits");
  $("limits").textContent =
    `Private to this browser · up to ${l.max_docs_per_session} docs, ${l.max_upload_mb} MB each · auto-deleted after ${l.doc_ttl_hours}h`;
}

async function refreshDocs() {
  const docs = await api("/api/documents");
  const list = $("docs");
  list.innerHTML = "";
  if (!docs.length) {
    list.innerHTML = '<li class="empty">No documents yet</li>';
    return;
  }
  for (const d of docs) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="name"></span><span class="meta">${d.chunks} chunks · ${expiresIn(d.expires_at)}</span><button title="Remove">×</button>`;
    li.querySelector(".name").textContent = d.source;
    li.querySelector(".name").title = d.source;
    li.querySelector("button").onclick = async () => {
      await api(`/api/documents/${d.doc_id}`, { method: "DELETE" });
      refreshDocs();
    };
    list.appendChild(li);
  }
}

async function uploadFiles(files) {
  for (const file of files) {
    setStatus(`Reading and embedding ${file.name}…`);
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await api("/api/documents/upload", { method: "POST", body: form });
      setStatus(`Added ${r.source} (${r.chunks} chunks)`);
    } catch (e) {
      setStatus(`${file.name}: ${e.message}`, true);
    }
  }
  refreshDocs();
}

const drop = $("drop");
$("file").onchange = (e) => uploadFiles(e.target.files);
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  uploadFiles(e.dataTransfer.files);
};

$("urlForm").onsubmit = async (e) => {
  e.preventDefault();
  const url = $("url").value.trim();
  setStatus("Fetching article…");
  try {
    const r = await api("/api/documents/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    setStatus(`Added article (${r.chunks} chunks)`);
    $("url").value = "";
    refreshDocs();
  } catch (err) {
    setStatus(err.message, true);
  }
};

// ---------- Chat ----------

const messages = $("messages");

function addMessage(cls) {
  messages.querySelector(".welcome")?.remove();
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  messages.appendChild(div);
  return div;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderAnswer(el, text) {
  el.innerHTML = escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\[(\d+)\]/g, '<span class="cite">[$1]</span>');
}

function renderSources(el, sources) {
  const wrap = document.createElement("div");
  wrap.className = "sources";
  for (const s of sources) {
    const d = document.createElement("details");
    const where = s.page > 0 ? `${s.source} · p.${s.page}` : s.source;
    d.innerHTML = "<summary></summary><p></p>";
    d.querySelector("summary").textContent = `[${s.n}] ${where}`;
    d.querySelector("p").textContent = s.text;
    wrap.appendChild(d);
  }
  el.appendChild(wrap);
}

async function ask(question) {
  addMessage("user").textContent = question;
  const bot = addMessage("bot typing");
  const send = $("send");
  send.disabled = true;

  let answer = "";
  let sources = [];
  try {
    const res = await fetch("/api/chat", withSession({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }));
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }

    // Parse the server-sent event stream
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();
      for (const raw of events) {
        const event = raw.match(/^event: (.*)$/m)?.[1];
        const data = JSON.parse(raw.match(/^data: (.*)$/m)?.[1] ?? "null");
        if (event === "sources") sources = data;
        else if (event === "token") { answer += data; renderAnswer(bot, answer); }
        else if (event === "error") throw new Error(data);
      }
      messages.scrollTop = messages.scrollHeight;
    }
    if (sources.length) renderSources(bot, sources);
  } catch (e) {
    bot.classList.add("error");
    bot.textContent = `Error: ${e.message}`;
  } finally {
    bot.classList.remove("typing");
    send.disabled = false;
    messages.scrollTop = messages.scrollHeight;
  }
}

const q = $("question");
$("ask").onsubmit = (e) => {
  e.preventDefault();
  const text = q.value.trim();
  if (!text) return;
  q.value = "";
  ask(text);
};
q.onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("ask").requestSubmit();
  }
};

refreshDocs().catch((e) => setStatus(e.message, true));
showLimits().catch(() => {});
