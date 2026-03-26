const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = 3000;
const ROOT = __dirname;
const HOME = process.env.HOME || process.env.USERPROFILE;

const LOG_FILES = {
  icarus: path.join(ROOT, "icarus-log.md"),
  daedalus: path.join(ROOT, "daedalus-log.md"),
  "icarus-code": path.join(ROOT, "templates/code-review/icarus-log.md"),
  "daedalus-code": path.join(ROOT, "templates/code-review/daedalus-log.md"),
};

const MEMORY_FILES = {
  icarus: path.join(HOME, ".hermes-icarus/memories/MEMORY.md"),
  daedalus: path.join(HOME, ".hermes-daedalus/memories/MEMORY.md"),
};

function readSafe(p) {
  try {
    return fs.readFileSync(p, "utf-8");
  } catch {
    return "";
  }
}

function parseCycles(md) {
  const cycles = [];
  const blocks = md.split(/^---$/m).filter((b) => b.trim());
  for (const block of blocks) {
    const header = block.match(/## Cycle (\d+)/);
    if (!header) continue;
    const num = parseInt(header[1], 10);
    const ts = block.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)/);
    const thought = block.match(/\*\*Thought:\*\* ([\s\S]*?)(?=\n\n\*\*|\n*$)/);
    const question = block.match(/\*\*Question:\*\* ([\s\S]*?)(?=\n\n|\n*$)/);
    const response = block.match(/\*\*Response:\*\* ([\s\S]*?)(?=\n\n\*\*|\n*$)/);
    const challenge = block.match(/\*\*Challenge:\*\* ([\s\S]*?)(?=\n\n|\n*$)/);
    // Code review format: raw content after timestamp line
    const codeMatch = block.match(/```[\s\S]*?```/g);
    const reviewMatch = block.match(/(?:MUST FIX|SHOULD FIX|NIT)[:\s][\s\S]*?(?=(?:MUST FIX|SHOULD FIX|NIT|CORRECTED|\*\*|$))/gi);

    cycles.push({
      cycle: num,
      timestamp: ts ? ts[1] : null,
      thought: thought ? thought[1].trim() : null,
      question: question ? question[1].trim() : null,
      response: response ? response[1].trim() : null,
      challenge: challenge ? challenge[1].trim() : null,
      code: codeMatch || null,
      reviews: reviewMatch || null,
      raw: block.trim(),
    });
  }
  return cycles;
}

function getStats() {
  const icarusRaw = readSafe(LOG_FILES.icarus);
  const daedalusRaw = readSafe(LOG_FILES.daedalus);
  const icarusCodeRaw = readSafe(LOG_FILES["icarus-code"]);
  const daedalusCodeRaw = readSafe(LOG_FILES["daedalus-code"]);
  const icarusMem = readSafe(MEMORY_FILES.icarus);
  const daedalusMem = readSafe(MEMORY_FILES.daedalus);

  const icarus = parseCycles(icarusRaw);
  const daedalus = parseCycles(daedalusRaw);
  const icarusCode = parseCycles(icarusCodeRaw);
  const daedalusCode = parseCycles(daedalusCodeRaw);

  // Extract world URLs from all logs
  const allText = icarusRaw + daedalusRaw + icarusCodeRaw + daedalusCodeRaw;
  const worldUrls = [...new Set((allText.match(/https:\/\/(?:marble\.)?worldlabs\.ai\/world\/[a-f0-9-]+/g) || []))];

  return {
    dialogue: { icarus, daedalus },
    codeReview: { icarus: icarusCode, daedalus: daedalusCode },
    memory: {
      icarus: { content: icarusMem, bytes: Buffer.byteLength(icarusMem) },
      daedalus: { content: daedalusMem, bytes: Buffer.byteLength(daedalusMem) },
    },
    worlds: worldUrls,
    totals: {
      dialogueCycles: Math.max(icarus.length, daedalus.length),
      codeCycles: Math.max(icarusCode.length, daedalusCode.length),
      totalMessages: icarus.length + daedalus.length + icarusCode.length + daedalusCode.length,
      memoryBytes: Buffer.byteLength(icarusMem) + Buffer.byteLength(daedalusMem),
    },
  };
}

// SSE clients
const sseClients = new Set();

function broadcast() {
  const data = JSON.stringify(getStats());
  for (const res of sseClients) {
    res.write(`data: ${data}\n\n`);
  }
}

// Watch log files for changes
for (const f of [...Object.values(LOG_FILES), ...Object.values(MEMORY_FILES)]) {
  try {
    fs.watch(f, { persistent: false }, () => broadcast());
  } catch {
    // file may not exist yet
  }
}

// Also poll every 5s for files that didn't exist at startup
setInterval(() => {
  for (const f of [...Object.values(LOG_FILES), ...Object.values(MEMORY_FILES)]) {
    try {
      fs.watch(f, { persistent: false }, () => broadcast());
    } catch {
      // still doesn't exist
    }
  }
}, 5000);

const HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Icarus / Daedalus</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #101014;
    --surface: #18181c;
    --border: #2a2a30;
    --text: #c8c8d0;
    --text-dim: #6e6e78;
    --text-bright: #e8e8f0;
    --accent-a: #c87040;
    --accent-b: #5080a8;
    --accent-a-dim: rgba(200,112,64,0.12);
    --accent-b-dim: rgba(80,128,168,0.12);
    --mono: "SF Mono", "Cascadia Code", "Fira Code", Consolas, monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif;
  }

  html { font-size: 14px; }
  body {
    font-family: var(--sans);
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
  }

  /* ── Header ──────────────────────────── */
  header {
    padding: 24px 32px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: baseline;
    gap: 16px;
  }
  header h1 {
    font-family: var(--mono);
    font-size: 16px;
    font-weight: 500;
    color: var(--text-bright);
    letter-spacing: -0.02em;
  }
  header .subtitle {
    font-size: 12px;
    color: var(--text-dim);
    font-family: var(--mono);
  }
  header .live {
    font-size: 11px;
    color: var(--text-dim);
    font-family: var(--mono);
    margin-left: auto;
  }
  header .live::before {
    content: "";
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #48a868;
    margin-right: 6px;
    vertical-align: middle;
  }

  /* ── Stats bar ───────────────────────── */
  .stats {
    display: flex;
    gap: 1px;
    background: var(--border);
    border-bottom: 1px solid var(--border);
  }
  .stat {
    flex: 1;
    background: var(--surface);
    padding: 16px 24px;
  }
  .stat-label {
    font-size: 11px;
    font-family: var(--mono);
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
  }
  .stat-value {
    font-family: var(--mono);
    font-size: 22px;
    font-weight: 600;
    color: var(--text-bright);
  }
  .stat-detail {
    font-size: 11px;
    color: var(--text-dim);
    font-family: var(--mono);
    margin-top: 2px;
  }

  /* ── Tabs ─────────────────────────────── */
  .tabs {
    display: flex;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  .tab {
    padding: 10px 20px;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-dim);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: color 0.15s, border-color 0.15s;
  }
  .tab:hover { color: var(--text); }
  .tab.active {
    color: var(--text-bright);
    border-bottom-color: var(--text-bright);
  }

  /* ── Main layout ─────────────────────── */
  .panels { display: none; }
  .panels.active { display: flex; min-height: calc(100vh - 180px); }
  .panel-single.active { display: block; }

  .panel {
    flex: 1;
    overflow-y: auto;
    max-height: calc(100vh - 180px);
  }
  .panel + .panel { border-left: 1px solid var(--border); }

  .panel-header {
    position: sticky;
    top: 0;
    background: var(--surface);
    padding: 12px 20px;
    border-bottom: 1px solid var(--border);
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 500;
    z-index: 1;
  }
  .panel-header.agent-a { color: var(--accent-a); }
  .panel-header.agent-b { color: var(--accent-b); }

  /* ── Cycle entries ───────────────────── */
  .cycle {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
  }
  .cycle:last-child { border-bottom: none; }

  .cycle-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
  }
  .cycle-num {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-dim);
    font-weight: 600;
    letter-spacing: 0.04em;
  }
  .cycle-ts {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-dim);
  }

  .cycle-field {
    margin-bottom: 8px;
  }
  .cycle-field:last-child { margin-bottom: 0; }

  .field-label {
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 3px;
  }
  .agent-a .field-label { color: var(--accent-a); }
  .agent-b .field-label { color: var(--accent-b); }

  .field-body {
    color: var(--text);
    line-height: 1.65;
  }

  /* ── Code blocks ─────────────────────── */
  .code-block {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px 14px;
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre;
    color: var(--text);
    margin: 6px 0;
  }

  /* ── Review severity ─────────────────── */
  .severity {
    display: inline-block;
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.04em;
    padding: 2px 6px;
    border-radius: 3px;
    margin-right: 6px;
  }
  .severity-must { background: rgba(200,64,64,0.15); color: #d06060; }
  .severity-should { background: rgba(200,160,64,0.15); color: #c8a040; }
  .severity-nit { background: rgba(100,100,120,0.15); color: #808090; }

  /* ── Memory panel ────────────────────── */
  .memory-content {
    padding: 20px;
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.6;
    white-space: pre-wrap;
    color: var(--text);
    max-width: 900px;
  }
  .memory-bar {
    margin: 20px;
    max-width: 400px;
  }
  .memory-bar-track {
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }
  .memory-bar-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.3s;
  }
  .memory-bar-fill.a { background: var(--accent-a); }
  .memory-bar-fill.b { background: var(--accent-b); }
  .memory-bar-label {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-dim);
    margin-bottom: 6px;
    display: flex;
    justify-content: space-between;
  }

  /* ── Worlds panel ────────────────────── */
  .world-link {
    display: block;
    padding: 12px 20px;
    border-bottom: 1px solid var(--border);
    color: var(--accent-b);
    text-decoration: none;
    font-family: var(--mono);
    font-size: 13px;
    transition: background 0.1s;
  }
  .world-link:hover { background: var(--accent-b-dim); }

  .empty-state {
    padding: 40px 20px;
    text-align: center;
    color: var(--text-dim);
    font-family: var(--mono);
    font-size: 12px;
  }

  /* ── Responsive ──────────────────────── */
  @media (max-width: 768px) {
    .panels.active { flex-direction: column; }
    .panel + .panel { border-left: none; border-top: 1px solid var(--border); }
    .panel { max-height: none; }
    header { padding: 16px; }
    .stat { padding: 12px 16px; }
  }
</style>
</head>
<body>
<header>
  <h1>Icarus / Daedalus</h1>
  <span class="subtitle">two agents. persistent memory. every platform.</span>
  <span class="live" id="live">connected</span>
</header>

<div class="stats" id="stats"></div>

<div class="tabs" id="tabs"></div>

<div class="panels active" id="panel-dialogue">
  <div class="panel" id="icarus-dialogue"></div>
  <div class="panel" id="daedalus-dialogue"></div>
</div>

<div class="panels" id="panel-code">
  <div class="panel" id="icarus-code"></div>
  <div class="panel" id="daedalus-code"></div>
</div>

<div class="panels panel-single" id="panel-memory">
  <div id="memory-content"></div>
</div>

<div class="panels panel-single" id="panel-worlds">
  <div id="worlds-content"></div>
</div>

<script>
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

function switchTab(panel) {
  $$(".tab").forEach(t => t.classList.remove("active"));
  $(\`.tab[data-panel="\${panel}"]\`).classList.add("active");
  $$(".panels").forEach(p => p.classList.remove("active"));
  $(\`#panel-\${panel}\`).classList.add("active");
}

let currentTab = null;

function renderTabs(data) {
  const tabs = [];
  if (data.totals.dialogueCycles > 0) tabs.push({ id: "dialogue", label: "dialogue" });
  if (data.totals.codeCycles > 0) tabs.push({ id: "code", label: "code review" });
  tabs.push({ id: "memory", label: "memory" });
  if (data.worlds.length > 0) tabs.push({ id: "worlds", label: "worlds" });

  // Default to first available tab
  if (!currentTab || !tabs.find(t => t.id === currentTab)) {
    currentTab = tabs[0].id;
  }

  $("#tabs").innerHTML = tabs
    .map(t => \`<div class="tab \${t.id === currentTab ? "active" : ""}" data-panel="\${t.id}">\${t.label}</div>\`)
    .join("");

  $$(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      currentTab = tab.dataset.panel;
      switchTab(currentTab);
    });
  });

  // Show/hide panels
  $$(".panels").forEach(p => p.classList.remove("active"));
  $(\`#panel-\${currentTab}\`).classList.add("active");
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function renderStats(data) {
  const t = data.totals;
  const memPct = Math.round((t.memoryBytes / 4400) * 100);
  const allCycles = [...data.dialogue.icarus, ...data.codeReview.icarus];
  const lastCycle = allCycles.length > 0 ? allCycles[allCycles.length - 1] : null;
  const lastTs = lastCycle ? lastCycle.timestamp : "none";

  let stats = [];

  stats.push(\`<div class="stat">
    <div class="stat-label">cycles</div>
    <div class="stat-value">\${t.dialogueCycles + t.codeCycles}</div>
    <div class="stat-detail">last: \${lastTs}</div>
  </div>\`);

  if (t.dialogueCycles > 0) {
    stats.push(\`<div class="stat">
      <div class="stat-label">dialogue</div>
      <div class="stat-value">\${t.dialogueCycles}</div>
    </div>\`);
  }

  if (t.codeCycles > 0) {
    stats.push(\`<div class="stat">
      <div class="stat-label">code reviews</div>
      <div class="stat-value">\${t.codeCycles}</div>
    </div>\`);
  }

  stats.push(\`<div class="stat">
    <div class="stat-label">messages</div>
    <div class="stat-value">\${t.totalMessages}</div>
  </div>\`);

  stats.push(\`<div class="stat">
    <div class="stat-label">memory</div>
    <div class="stat-value">\${memPct}%</div>
    <div class="stat-detail">\${t.memoryBytes} / 4400 bytes</div>
  </div>\`);

  if (data.worlds.length > 0) {
    stats.push(\`<div class="stat">
      <div class="stat-label">worlds</div>
      <div class="stat-value">\${data.worlds.length}</div>
    </div>\`);
  }

  $("#stats").innerHTML = stats.join("");
}

function renderDialogueCycle(c, agent) {
  const cls = agent === "icarus" ? "agent-a" : "agent-b";
  let fields = "";

  if (c.thought) {
    fields += \`<div class="cycle-field"><div class="field-label">thought</div><div class="field-body">\${escHtml(c.thought)}</div></div>\`;
  }
  if (c.question) {
    fields += \`<div class="cycle-field"><div class="field-label">question</div><div class="field-body">\${escHtml(c.question)}</div></div>\`;
  }
  if (c.response) {
    fields += \`<div class="cycle-field"><div class="field-label">response</div><div class="field-body">\${escHtml(c.response)}</div></div>\`;
  }
  if (c.challenge) {
    fields += \`<div class="cycle-field"><div class="field-label">challenge</div><div class="field-body">\${escHtml(c.challenge)}</div></div>\`;
  }

  return \`<div class="cycle \${cls}">
    <div class="cycle-header">
      <span class="cycle-num">CYCLE \${c.cycle}</span>
      <span class="cycle-ts">\${c.timestamp || ""}</span>
    </div>
    \${fields}
  </div>\`;
}

function renderCodeCycle(c, agent) {
  const cls = agent === "icarus" ? "agent-a" : "agent-b";
  let body = "";

  if (c.code) {
    for (const block of c.code) {
      const clean = block.replace(/^\`\`\`\\w*\\n?/, "").replace(/\\n?\`\`\`$/, "");
      body += \`<div class="code-block">\${escHtml(clean)}</div>\`;
    }
  }

  if (c.reviews) {
    for (const r of c.reviews) {
      const sev = r.match(/^(MUST FIX|SHOULD FIX|NIT)/i);
      const sevClass = sev ? "severity-" + sev[1].split(" ")[0].toLowerCase() : "";
      const sevLabel = sev ? sev[1] : "";
      body += \`<div class="cycle-field">
        <span class="severity \${sevClass}">\${sevLabel}</span>
        <span class="field-body">\${escHtml(r.replace(/^(MUST FIX|SHOULD FIX|NIT)[:\\s]*/i, "").trim())}</span>
      </div>\`;
    }
  }

  if (!c.code && !c.reviews) {
    // Raw content for code review entries
    const raw = c.raw.replace(/## Cycle \\d+/, "").replace(/\\d{4}-\\d{2}-\\d{2}.*UTC/, "").trim();
    if (raw.includes("\`\`\`")) {
      const blocks = raw.match(/\`\`\`[\\s\\S]*?\`\`\`/g) || [];
      const text = raw.replace(/\`\`\`[\\s\\S]*?\`\`\`/g, "").trim();
      if (text) body += \`<div class="field-body">\${escHtml(text)}</div>\`;
      for (const block of blocks) {
        const clean = block.replace(/^\`\`\`\\w*\\n?/, "").replace(/\\n?\`\`\`$/, "");
        body += \`<div class="code-block">\${escHtml(clean)}</div>\`;
      }
    } else {
      body += \`<div class="field-body">\${escHtml(raw)}</div>\`;
    }
  }

  return \`<div class="cycle \${cls}">
    <div class="cycle-header">
      <span class="cycle-num">CYCLE \${c.cycle}</span>
      <span class="cycle-ts">\${c.timestamp || ""}</span>
    </div>
    \${body}
  </div>\`;
}

function renderPanel(cycles, container, agent, renderFn) {
  const cls = agent === "icarus" ? "agent-a" : "agent-b";
  const label = agent === "icarus" ? "icarus" : "daedalus";
  const reversed = [...cycles].reverse();
  container.innerHTML = \`<div class="panel-header \${cls}">\${label}</div>\`
    + (reversed.length === 0
      ? '<div class="empty-state">no cycles yet</div>'
      : reversed.map(c => renderFn(c, agent)).join(""));
}

function renderMemory(data) {
  const limit = 2200;
  const iBytes = data.memory.icarus.bytes;
  const dBytes = data.memory.daedalus.bytes;

  $("#memory-content").innerHTML = \`
    <div class="memory-bar">
      <div class="memory-bar-label">
        <span>icarus</span>
        <span>\${iBytes} / \${limit}</span>
      </div>
      <div class="memory-bar-track">
        <div class="memory-bar-fill a" style="width: \${Math.min(100, (iBytes / limit) * 100)}%"></div>
      </div>
    </div>
    <div class="memory-bar">
      <div class="memory-bar-label">
        <span>daedalus</span>
        <span>\${dBytes} / \${limit}</span>
      </div>
      <div class="memory-bar-track">
        <div class="memory-bar-fill b" style="width: \${Math.min(100, (dBytes / limit) * 100)}%"></div>
      </div>
    </div>
    <div class="memory-content">\${escHtml(data.memory.icarus.content || "(empty)")}</div>
  \`;
}

function renderWorlds(data) {
  if (data.worlds.length === 0) {
    $("#worlds-content").innerHTML = '<div class="empty-state">no worlds generated yet</div>';
    return;
  }
  $("#worlds-content").innerHTML = data.worlds
    .map(url => \`<a class="world-link" href="\${escHtml(url)}" target="_blank" rel="noopener">\${escHtml(url)}</a>\`)
    .join("");
}

function render(data) {
  renderTabs(data);
  renderStats(data);
  renderPanel(data.dialogue.icarus, $("#icarus-dialogue"), "icarus", renderDialogueCycle);
  renderPanel(data.dialogue.daedalus, $("#daedalus-dialogue"), "daedalus", renderDialogueCycle);
  renderPanel(data.codeReview.icarus, $("#icarus-code"), "icarus", renderCodeCycle);
  renderPanel(data.codeReview.daedalus, $("#daedalus-code"), "daedalus", renderCodeCycle);
  renderMemory(data);
  renderWorlds(data);
}

// Initial fetch
fetch("/api/stats").then(r => r.json()).then(render);

// SSE for live updates
const sse = new EventSource("/api/stream");
sse.onmessage = e => render(JSON.parse(e.data));
sse.onerror = () => {
  $("#live").textContent = "reconnecting";
  $("#live").style.opacity = "0.5";
};
sse.onopen = () => {
  $("#live").textContent = "connected";
  $("#live").style.opacity = "1";
};
</script>
</body>
</html>`;

const server = http.createServer((req, res) => {
  if (req.url === "/api/stats") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(getStats()));
    return;
  }

  if (req.url === "/api/stream") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    res.write(`data: ${JSON.stringify(getStats())}\n\n`);
    sseClients.add(res);
    req.on("close", () => sseClients.delete(res));
    return;
  }

  // Serve dashboard
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(HTML);
});

server.listen(PORT, () => {
  console.log(`dashboard: http://localhost:${PORT}`);
});
