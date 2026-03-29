const http = require("http");
const fs = require("fs");
const path = require("path");
const { exec } = require("child_process");

const PORT = 3000;
const ROOT = __dirname;
const HOME = process.env.HOME || process.env.USERPROFILE;
if (!HOME) { console.error("error: HOME not set"); process.exit(1); }

const FABRIC = path.join(HOME, "fabric");
const AGENTS_FILE = path.join(ROOT, "agents.yml");
const START_TIME = Date.now();

function safe(p) { try { return fs.readFileSync(p, "utf-8"); } catch { return ""; } }
function json(p) { try { return JSON.parse(fs.readFileSync(p, "utf-8")); } catch { return null; } }

function parseAgents() {
  const yml = safe(AGENTS_FILE);
  const agents = [];
  let cur = null;
  for (const line of yml.split("\n")) {
    const l = line.trim();
    if (l.startsWith("- name:")) { if (cur) agents.push(cur); cur = { name: l.split(":")[1].trim() }; }
    else if (l.startsWith("role:") && cur) cur.role = l.split(":").slice(1).join(":").trim();
    else if (l.startsWith("home:") && cur) cur.home = l.split(":").slice(1).join(":").trim().replace("~", HOME);
  }
  if (cur) agents.push(cur);
  return agents;
}

function parseCycles(md) {
  const cycles = [];
  for (const block of md.split(/^---$/m)) {
    const m = block.match(/## Cycle (\d+)/);
    if (!m) continue;
    const ts = (block.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)/)||[])[1] || "";
    const thought = (block.match(/\*\*Thought:\*\* ([\s\S]*?)(?=\n\n\*\*|\n*$)/)||[])[1] || "";
    const response = (block.match(/\*\*Response:\*\* ([\s\S]*?)(?=\n\n|\n*$)/)||[])[1] || "";
    cycles.push({ cycle: +m[1], timestamp: ts, thought: thought.trim(), response: response.trim() });
  }
  return cycles;
}

function getFabricEntries() {
  if (!fs.existsSync(FABRIC)) return [];
  const entries = [];
  const scan = (dir, tier) => {
    if (!fs.existsSync(dir)) return;
    for (const f of fs.readdirSync(dir).filter(f => f.endsWith(".md"))) {
      const content = safe(path.join(dir, f));
      const head = content.slice(0, 600);
      entries.push({
        file: f,
        agent: (head.match(/^agent: (.+)$/m)||[])[1] || "",
        platform: (head.match(/^platform: (.+)$/m)||[])[1] || "",
        type: (head.match(/^type: (.+)$/m)||[])[1] || "",
        tier: tier || (head.match(/^tier: (.+)$/m)||[])[1] || "",
        timestamp: (head.match(/^timestamp: (.+)$/m)||[])[1] || "",
        summary: (head.match(/^summary: (.+)$/m)||[])[1] || "",
        body: content.split("---").slice(2).join("---").trim().slice(0, 200),
      });
    }
  };
  scan(FABRIC, null);
  scan(path.join(FABRIC, "cold"), "cold");
  return entries.sort((a,b) => b.timestamp.localeCompare(a.timestamp));
}

function fabricSize() {
  if (!fs.existsSync(FABRIC)) return 0;
  let total = 0;
  try {
    for (const f of fs.readdirSync(FABRIC)) {
      try { total += fs.statSync(path.join(FABRIC, f)).size; } catch {}
    }
  } catch {}
  return total;
}

function getData() {
  const agents = parseAgents();
  const entries = getFabricEntries();
  const today = new Date().toISOString().slice(0, 10);

  const agentStatuses = agents.map(a => {
    const home = a.home || path.join(HOME, ".hermes-" + a.name);
    const gw = json(path.join(home, "gateway_state.json"));
    let online = false;
    let platforms = {};
    if (gw) {
      try { process.kill(gw.pid, 0); online = true; } catch {}
      platforms = gw.platforms || {};
    }
    const env = safe(path.join(home, ".env"));
    const configuredPlatforms = [];
    if (env.includes("TELEGRAM_BOT_TOKEN")) configuredPlatforms.push({ name: "telegram", abbr: "TGM", state: platforms.telegram?.state || (online ? "configured" : "offline") });
    if (env.includes("DISCORD_BOT_TOKEN")) configuredPlatforms.push({ name: "discord", abbr: "DSC", state: platforms.discord?.state || "offline" });
    if (env.includes("SLACK_BOT_TOKEN")) configuredPlatforms.push({ name: "slack", abbr: "SLK", state: platforms.slack?.state || "offline" });
    if (env.includes("WHATSAPP_ENABLED")) configuredPlatforms.push({ name: "whatsapp", abbr: "WHA", state: "configured" });
    if (env.includes("SIGNAL_HTTP_URL")) configuredPlatforms.push({ name: "signal", abbr: "SIG", state: "configured" });
    if (env.includes("EMAIL_ADDRESS")) configuredPlatforms.push({ name: "email", abbr: "EML", state: "configured" });
    if (env.includes("SLACK_WEBHOOK") && !env.includes("SLACK_BOT_TOKEN")) configuredPlatforms.push({ name: "slack-wh", abbr: "SWH", state: "configured" });

    const logFile = path.join(ROOT, a.name + "-log.md");
    const cycles = parseCycles(safe(logFile));
    const lastTs = cycles.length > 0 ? cycles[cycles.length - 1].timestamp : "";
    const lastPlatform = entries.filter(e => e.agent === a.name)[0]?.platform || "";
    const totalEntries = entries.filter(e => e.agent === a.name).length;
    const avgLen = cycles.length > 0 ? Math.round(cycles.reduce((s, c) => s + (c.thought || "").length, 0) / cycles.length) : 0;

    return { name: a.name, role: a.role || "", online, platforms: configuredPlatforms, lastActive: lastTs, lastPlatform, cycles, totalEntries, avgLen };
  });

  // timeline: entries per day per agent (last 14 days)
  const timeline = {};
  for (let i = 13; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    timeline[d] = {};
    agents.forEach(a => timeline[d][a.name] = 0);
  }
  for (const e of entries) {
    const day = e.timestamp.slice(0, 10);
    if (timeline[day]) {
      timeline[day][e.agent] = (timeline[day][e.agent] || 0) + 1;
    }
  }

  // platform distribution
  const platDist = {};
  for (const e of entries) {
    const p = e.platform || "cli";
    platDist[p] = (platDist[p] || 0) + 1;
  }

  // tier counts
  const hot = entries.filter(e => e.tier === "hot").length;
  const warm = entries.filter(e => e.tier === "warm").length;
  const cold = entries.filter(e => e.tier === "cold").length;
  const totalCycles = Math.max(...agentStatuses.map(a => a.cycles.length), 0);
  const entriesToday = entries.filter(e => e.timestamp.startsWith(today)).length;

  // compaction
  const compRaw = safe(path.join(ROOT, "compaction-history.md"));
  const compaction = [];
  for (const block of compRaw.split(/^---$/m)) {
    const m = block.match(/## (.+)/);
    if (!m) continue;
    const lines = block.split("\n").filter(l => l.trim() && !l.startsWith("##"));
    compaction.push({ timestamp: m[1].trim(), details: lines.map(l => l.trim()) });
  }

  // feed: last cycle per agent
  const feed = [];
  for (const a of agentStatuses) {
    if (a.cycles.length > 0) {
      const last = a.cycles[a.cycles.length - 1];
      feed.push({ agent: a.name, cycle: last.cycle, timestamp: last.timestamp, thought: last.thought, response: last.response });
    }
  }

  return {
    agents: agentStatuses,
    entries: entries.slice(0, 30),
    feed: feed.sort((a,b) => b.cycle - a.cycle),
    stats: {
      totalAgents: agentStatuses.length,
      activeAgents: agentStatuses.filter(a => a.online).length,
      totalCycles,
      totalEntries: entries.length,
      entriesToday,
      hot, warm, cold,
      brainSize: fabricSize(),
      platforms: [...new Set(agentStatuses.flatMap(a => a.platforms.map(p => p.name)))],
      uptime: Math.floor((Date.now() - START_TIME) / 1000),
    },
    timeline,
    platDist,
    compaction: compaction.reverse().slice(0, 10),
    lastCycleTs: feed.length > 0 ? feed[0].timestamp : "",
  };
}

// SSE
const clients = new Set();
function broadcast() {
  const d = JSON.stringify(getData());
  for (const c of clients) c.write("data: " + d + "\n\n");
}

const watched = new Set();
function watchAll() {
  const paths = [AGENTS_FILE, path.join(ROOT, "compaction-history.md")];
  parseAgents().forEach(a => {
    paths.push(path.join(ROOT, a.name + "-log.md"));
    const home = a.home || path.join(HOME, ".hermes-" + a.name);
    paths.push(path.join(home, "gateway_state.json"));
  });
  if (fs.existsSync(FABRIC)) paths.push(FABRIC);
  for (const p of paths) {
    if (watched.has(p)) continue;
    try { fs.watch(p, { persistent: false }, () => broadcast()); watched.add(p); } catch {}
  }
}
watchAll();
setInterval(watchAll, 10000);

const HTML = safe(path.join(ROOT, "dashboard.html"));

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname === "/api/data") {
    res.writeHead(200, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" });
    res.end(JSON.stringify(getData()));
    return;
  }
  if (url.pathname === "/api/stream") {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    res.write("data: " + JSON.stringify(getData()) + "\n\n");
    clients.add(res);
    req.on("close", () => clients.delete(res));
    return;
  }
  if (req.method === "POST") {
    if (url.pathname === "/api/action/cycle") {
      exec("bash " + path.join(ROOT, "dialogue.sh") + " >> " + path.join(ROOT, "cron.log") + " 2>&1");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end('{"ok":true}');
      return;
    }
    if (url.pathname === "/api/action/compact") {
      exec("FORCE_COMPACT=1 bash " + path.join(ROOT, "dialogue.sh") + " >> " + path.join(ROOT, "cron.log") + " 2>&1");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end('{"ok":true}');
      return;
    }
    if (url.pathname === "/api/action/add-agent") {
      let body = "";
      req.on("data", c => body += c);
      req.on("end", () => {
        try {
          const { name, role } = JSON.parse(body);
          exec("bash " + path.join(ROOT, "add-agent.sh") + " --name " + name + " --role '" + role + "'");
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end('{"ok":true}');
        } catch { res.writeHead(400); res.end('{"error":"bad request"}'); }
      });
      return;
    }
    if (url.pathname === "/api/action/sync") {
      exec("bash " + path.join(ROOT, "fabric-sync.sh") + " sync 2>&1");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end('{"ok":true}');
      return;
    }
  }
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(HTML);
});

server.listen(PORT, () => console.log("dashboard: http://localhost:" + PORT));
