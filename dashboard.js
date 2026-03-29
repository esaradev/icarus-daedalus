const http = require("http");
const fs = require("fs");
const path = require("path");
const { exec } = require("child_process");

const PORT = 3000;
const ROOT = __dirname;
const HOME = process.env.HOME || process.env.USERPROFILE;
if (!HOME) { console.error("HOME not set"); process.exit(1); }
const FABRIC = path.join(HOME, "fabric");
const AGENTS_FILE = path.join(ROOT, "agents.yml");
const START = Date.now();

function safe(p) { try { return fs.readFileSync(p, "utf-8"); } catch { return ""; } }
function jsonF(p) { try { return JSON.parse(fs.readFileSync(p, "utf-8")); } catch { return null; } }

function parseAgents() {
  const yml = safe(AGENTS_FILE); const agents = []; let cur = null;
  for (const line of yml.split("\n")) {
    const l = line.trim();
    if (l.startsWith("- name:")) { if (cur) agents.push(cur); cur = { name: l.split(":")[1].trim() }; }
    else if (l.startsWith("role:") && cur) cur.role = l.split(":").slice(1).join(":").trim();
    else if (l.startsWith("home:") && cur) cur.home = l.split(":").slice(1).join(":").trim().replace("~", HOME);
  }
  if (cur) agents.push(cur); return agents;
}

function parseCycles(md) {
  const cycles = [];
  for (const block of md.split(/^---$/m)) {
    const m = block.match(/## Cycle (\d+)/); if (!m) continue;
    const ts = (block.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)/)||[])[1] || "";
    const thought = (block.match(/\*\*Thought:\*\* ([\s\S]*?)(?=\n\n\*\*|\n*$)/)||[])[1] || "";
    const response = (block.match(/\*\*Response:\*\* ([\s\S]*?)(?=\n\n|\n*$)/)||[])[1] || "";
    cycles.push({ cycle: +m[1], timestamp: ts, thought: thought.trim(), response: response.trim(), raw: block.trim() });
  }
  return cycles;
}

function scanFabric() {
  if (!fs.existsSync(FABRIC)) return [];
  const entries = []; const dirs = [FABRIC];
  const cold = path.join(FABRIC, "cold");
  if (fs.existsSync(cold)) dirs.push(cold);
  for (const dir of dirs) {
    for (const f of fs.readdirSync(dir).filter(f => f.endsWith(".md"))) {
      const fp = path.join(dir, f); const content = safe(fp); const head = content.slice(0, 600);
      entries.push({
        file: f, path: fp, dir: dir === cold ? "cold" : "hot",
        agent: (head.match(/^agent: (.+)$/m)||[])[1] || "",
        platform: (head.match(/^platform: (.+)$/m)||[])[1] || "",
        type: (head.match(/^type: (.+)$/m)||[])[1] || "",
        tier: (head.match(/^tier: (.+)$/m)||[])[1] || "",
        timestamp: (head.match(/^timestamp: (.+)$/m)||[])[1] || "",
        summary: (head.match(/^summary: (.+)$/m)||[])[1] || "",
        refs: (head.match(/^refs: \[(.+)\]$/m)||[])[1] || "",
        body: content.split("---").slice(2).join("---").trim(),
        size: Buffer.byteLength(content),
      });
    }
  }
  return entries.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
}

function agentStatus(a) {
  const home = a.home || path.join(HOME, ".hermes-" + a.name);
  const gw = jsonF(path.join(home, "gateway_state.json"));
  let online = false; let platforms = {};
  if (gw) { try { process.kill(gw.pid, 0); online = true; } catch {} platforms = gw.platforms || {}; }
  const env = safe(path.join(home, ".env"));
  const soul = safe(path.join(home, "SOUL.md"));
  const cp = [];
  if (env.includes("TELEGRAM_BOT_TOKEN")) cp.push({ name: "telegram", abbr: "TGM", state: platforms.telegram?.state || (online ? "idle" : "offline"), color: "#229ED9" });
  if (env.includes("DISCORD_BOT_TOKEN")) cp.push({ name: "discord", abbr: "DSC", state: platforms.discord?.state || "offline", color: "#5865F2" });
  if (env.includes("SLACK_BOT_TOKEN")) cp.push({ name: "slack", abbr: "SLK", state: platforms.slack?.state || "offline", color: "#611f69" });
  if (env.includes("WHATSAPP_ENABLED")) cp.push({ name: "whatsapp", abbr: "WHA", state: "configured", color: "#25D366" });
  if (env.includes("SIGNAL_HTTP_URL")) cp.push({ name: "signal", abbr: "SIG", state: "configured", color: "#3A76F0" });
  if (env.includes("EMAIL_ADDRESS")) cp.push({ name: "email", abbr: "EML", state: "configured", color: "#888" });
  if (env.includes("SLACK_WEBHOOK") && !env.includes("SLACK_BOT_TOKEN")) cp.push({ name: "slack-wh", abbr: "SWH", state: "configured", color: "#611f69" });
  const logFile = path.join(ROOT, a.name + "-log.md");
  const cycles = parseCycles(safe(logFile));
  const entries = scanFabric().filter(e => e.agent === a.name);
  const avgLen = cycles.length > 0 ? Math.round(cycles.reduce((s, c) => s + (c.thought || "").length, 0) / cycles.length) : 0;
  return { name: a.name, role: a.role || "", online, platforms: cp, soul,
    cycles, totalEntries: entries.length, avgLen,
    lastActive: cycles.length > 0 ? cycles[cycles.length - 1].timestamp : "",
    lastPlatform: entries.length > 0 ? entries[0].platform : "",
    firstSeen: cycles.length > 0 ? cycles[0].timestamp : "",
    entriesByPlatform: entries.reduce((m, e) => { m[e.platform] = (m[e.platform]||0)+1; return m; }, {}),
    entriesByDay: entries.reduce((m, e) => { const d = e.timestamp.slice(0,10); m[d] = (m[d]||0)+1; return m; }, {}),
    responseLengths: cycles.map(c => ({ cycle: c.cycle, len: (c.thought||"").length })),
    recentEntries: entries.slice(0, 10),
    recentCycles: cycles.slice(-10).reverse(),
  };
}

function fabricSize() {
  if (!fs.existsSync(FABRIC)) return 0;
  let t = 0; try { for (const f of fs.readdirSync(FABRIC)) { try { t += fs.statSync(path.join(FABRIC, f)).size; } catch {} } } catch {} return t;
}

function fabricLs(subdir) {
  const dir = subdir ? path.join(FABRIC, subdir) : FABRIC;
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).map(f => {
    const fp = path.join(dir, f); const st = fs.statSync(fp);
    return { name: f, isDir: st.isDirectory(), size: st.size, mtime: st.mtime.toISOString() };
  }).sort((a, b) => b.isDir - a.isDir || a.name.localeCompare(b.name));
}

function getOverview() {
  const agents = parseAgents().map(agentStatus);
  const entries = scanFabric();
  const today = new Date().toISOString().slice(0, 10);
  const hot = entries.filter(e => e.tier === "hot").length;
  const warm = entries.filter(e => e.tier === "warm").length;
  const cold = entries.filter(e => e.tier === "cold").length;
  const totalCycles = Math.max(...agents.map(a => a.cycles.length), 0);
  const timeline = {};
  for (let i = 13; i >= 0; i--) { const d = new Date(Date.now() - i * 864e5).toISOString().slice(0, 10); timeline[d] = {}; agents.forEach(a => timeline[d][a.name] = 0); }
  for (const e of entries) { const day = e.timestamp.slice(0, 10); if (timeline[day]) timeline[day][e.agent] = (timeline[day][e.agent] || 0) + 1; }
  const platDist = {}; for (const e of entries) { const p = e.platform || "cli"; platDist[p] = (platDist[p] || 0) + 1; }
  const typeDist = {}; for (const e of entries) { const t = e.type || "other"; typeDist[t] = (typeDist[t] || 0) + 1; }
  const compRaw = safe(path.join(ROOT, "compaction-history.md"));
  const compaction = [];
  for (const block of compRaw.split(/^---$/m)) { const m = block.match(/## (.+)/); if (!m) continue; compaction.push({ timestamp: m[1].trim(), details: block.split("\n").filter(l => l.trim() && !l.startsWith("##")).map(l => l.trim()) }); }
  const feed = agents.filter(a => a.cycles.length > 0).map(a => { const last = a.cycles[a.cycles.length - 1]; return { agent: a.name, cycle: last.cycle, timestamp: last.timestamp, thought: last.thought, response: last.response }; }).sort((a, b) => b.cycle - a.cycle);
  // ticker events
  const ticker = [];
  entries.slice(0, 3).forEach(e => ticker.push({ text: e.agent + " wrote to fabric", time: e.timestamp }));
  compaction.slice(-2).forEach(c => ticker.push({ text: "compaction ran", time: c.timestamp }));
  return {
    agents, entries: entries.slice(0, 30), feed, ticker,
    stats: { totalAgents: agents.length, activeAgents: agents.filter(a => a.online).length, totalCycles, totalEntries: entries.length,
      entriesToday: entries.filter(e => e.timestamp.startsWith(today)).length, hot, warm, cold, brainSize: fabricSize(),
      platforms: [...new Set(agents.flatMap(a => a.platforms.map(p => p.name)))], uptime: Math.floor((Date.now() - START) / 1000) },
    timeline, platDist, typeDist, compaction: compaction.reverse().slice(0, 10), lastCycleTs: feed.length > 0 ? feed[0].timestamp : "",
  };
}

function getSystem() {
  const hermes = safe(path.join(HOME, ".hermes/hermes-agent/VERSION")).trim() || "unknown";
  const agents = parseAgents();
  const envStatus = agents.map(a => {
    const home = a.home || path.join(HOME, ".hermes-" + a.name);
    const env = safe(path.join(home, ".env"));
    return { name: a.name, vars: {
      ANTHROPIC_API_KEY: env.includes("ANTHROPIC_API_KEY") ? "SET" : "NOT SET",
      TELEGRAM_BOT_TOKEN: env.includes("TELEGRAM_BOT_TOKEN") ? "SET" : "NOT SET",
      DISCORD_BOT_TOKEN: env.includes("DISCORD_BOT_TOKEN") ? "SET" : "NOT SET",
      SLACK_BOT_TOKEN: env.includes("SLACK_BOT_TOKEN") ? "SET" : "NOT SET",
      SLACK_WEBHOOK_URL: env.includes("SLACK_WEBHOOK_URL") ? "SET" : "NOT SET",
    }};
  });
  const cronLog = safe(path.join(ROOT, "cron.log")).split("\n").filter(l => l.trim()).slice(-20);
  return { hermes, node: process.version, platform: process.platform, arch: process.arch,
    fabricSize: fabricSize(), agents: safe(AGENTS_FILE), envStatus, cronLog };
}

// SSE
const clients = new Set();
function broadcast() { const d = JSON.stringify(getOverview()); for (const c of clients) c.write("data: " + d + "\n\n"); }
const watched = new Set();
function watchAll() {
  const paths = [AGENTS_FILE, path.join(ROOT, "compaction-history.md")];
  parseAgents().forEach(a => { paths.push(path.join(ROOT, a.name + "-log.md")); paths.push(path.join(a.home || path.join(HOME, ".hermes-" + a.name), "gateway_state.json")); });
  if (fs.existsSync(FABRIC)) paths.push(FABRIC);
  for (const p of paths) { if (watched.has(p)) continue; try { fs.watch(p, { persistent: false }, () => broadcast()); watched.add(p); } catch {} }
}
watchAll(); setInterval(watchAll, 10000);

const HTML = safe(path.join(ROOT, "dashboard.html"));

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  const json = (data) => { res.writeHead(200, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }); res.end(JSON.stringify(data)); };

  // API
  if (url.pathname === "/api/overview" || url.pathname === "/api/data") return json(getOverview());
  if (url.pathname === "/api/agents") return json(parseAgents().map(agentStatus));
  if (url.pathname.startsWith("/api/agent/")) { const name = url.pathname.split("/")[3]; const a = parseAgents().find(x => x.name === name); return a ? json(agentStatus(a)) : (res.writeHead(404), res.end("not found")); }
  if (url.pathname === "/api/memory") {
    let entries = scanFabric();
    const q = url.searchParams;
    if (q.get("agent")) entries = entries.filter(e => e.agent === q.get("agent"));
    if (q.get("platform")) entries = entries.filter(e => e.platform === q.get("platform"));
    if (q.get("type")) entries = entries.filter(e => e.type === q.get("type"));
    if (q.get("tier")) entries = entries.filter(e => e.tier === q.get("tier"));
    return json(entries);
  }
  if (url.pathname.startsWith("/api/memory/")) { const file = decodeURIComponent(url.pathname.split("/").slice(3).join("/")); const fp = path.join(FABRIC, file); return json({ content: safe(fp) }); }
  if (url.pathname === "/api/platforms") {
    const agents = parseAgents().map(agentStatus);
    const plats = {}; agents.forEach(a => a.platforms.forEach(p => {
      if (!plats[p.name]) plats[p.name] = { name: p.name, abbr: p.abbr, color: p.color, agents: [], entries: 0, state: "offline" };
      plats[p.name].agents.push(a.name);
      if (p.state === "connected") plats[p.name].state = "connected";
    }));
    const entries = scanFabric();
    Object.values(plats).forEach(p => p.entries = entries.filter(e => e.platform === p.name).length);
    return json(Object.values(plats));
  }
  if (url.pathname === "/api/cycles") {
    const agents = parseAgents().map(a => ({ name: a.name, cycles: parseCycles(safe(path.join(ROOT, a.name + "-log.md"))) }));
    const merged = {}; agents.forEach(a => a.cycles.forEach(c => {
      if (!merged[c.cycle]) merged[c.cycle] = { cycle: c.cycle, timestamp: c.timestamp, agents: [] };
      merged[c.cycle].agents.push({ name: a.name, thought: c.thought, response: c.response });
    }));
    return json(Object.values(merged).sort((a, b) => b.cycle - a.cycle));
  }
  if (url.pathname === "/api/fabric") { const sub = url.searchParams.get("dir") || ""; return json(fabricLs(sub)); }
  if (url.pathname.startsWith("/api/fabric/")) { const fp = decodeURIComponent(url.pathname.slice(12)); return json({ content: safe(path.join(FABRIC, fp)) }); }
  if (url.pathname === "/api/system") return json(getSystem());
  if (url.pathname === "/api/search") {
    const q = (url.searchParams.get("q") || "").toLowerCase();
    if (!q) return json([]);
    return json(scanFabric().filter(e => (e.body + e.summary + e.agent + e.platform + e.type).toLowerCase().includes(q)).slice(0, 50));
  }
  if (url.pathname === "/api/events") {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    res.write("data: " + JSON.stringify(getOverview()) + "\n\n");
    clients.add(res); req.on("close", () => clients.delete(res)); return;
  }

  // Actions
  if (req.method === "POST") {
    const act = (cmd) => { exec(cmd); res.writeHead(200, { "Content-Type": "application/json" }); res.end('{"ok":true}'); };
    if (url.pathname === "/api/cycle") return act("bash " + path.join(ROOT, "dialogue.sh") + " >> " + path.join(ROOT, "cron.log") + " 2>&1 &");
    if (url.pathname === "/api/compact") return act("FORCE_COMPACT=1 bash " + path.join(ROOT, "dialogue.sh") + " >> " + path.join(ROOT, "cron.log") + " 2>&1 &");
    if (url.pathname === "/api/sync") return act("bash " + path.join(ROOT, "fabric-sync.sh") + " sync 2>&1 &");
    if (url.pathname === "/api/agent") {
      let body = ""; req.on("data", c => body += c); req.on("end", () => {
        try { const { name, role } = JSON.parse(body); act("bash " + path.join(ROOT, "add-agent.sh") + " --name " + name + " --role '" + role + "'"); }
        catch { res.writeHead(400); res.end('{"error":"bad"}'); }
      }); return;
    }
  }

  res.writeHead(200, { "Content-Type": "text/html" }); res.end(HTML);
});

server.listen(PORT, () => console.log("dashboard: http://localhost:" + PORT));
