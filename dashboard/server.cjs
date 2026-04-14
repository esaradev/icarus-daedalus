// Dashboard API server. Reads from agents.yml, fabric/, and Hermes homes.
// Run: node dashboard/server.cjs
const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = Number(process.env.PORT || 3001);
const HOST = process.env.HOST || "127.0.0.1";
const ROOT = path.resolve(__dirname, "..");
const HOME = process.env.HOME;
const FABRIC = process.env.FABRIC_DIR || path.join(HOME, "fabric");
const AGENTS_FILE = path.join(ROOT, "agents.yml");
const START = Date.now();

function safe(p) { try { return fs.readFileSync(p, "utf-8"); } catch { return ""; } }
function jf(p) { try { return JSON.parse(fs.readFileSync(p, "utf-8")); } catch { return null; } }
function exists(p) { try { fs.accessSync(p); return true; } catch { return false; } }
function round(n, places = 2) {
  const f = 10 ** places;
  return Math.round(n * f) / f;
}

function soulSummary(home) {
  const soul = safe(path.join(home, "SOUL.md"));
  if (!soul) return "";
  const lines = soul
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#") && !line.startsWith("- "));
  return lines[0] || "";
}

function parseAgents() {
  const yml = safe(AGENTS_FILE);
  const agents = [];
  let c = null;

  for (const l of yml.split("\n")) {
    const t = l.trim();
    if (t.startsWith("- name:")) {
      if (c) agents.push(c);
      c = { name: t.split(":")[1].trim() };
    } else if (t.startsWith("role:") && c) {
      c.role = t.split(":").slice(1).join(":").trim();
    } else if (t.startsWith("home:") && c) {
      c.home = t.split(":").slice(1).join(":").trim().replace("~", HOME);
    }
  }
  if (c) agents.push(c);
  if (agents.length > 0) return agents;

  const discovered = [];
  for (const entry of fs.readdirSync(HOME, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    if (!entry.name.startsWith(".hermes-")) continue;
    const name = entry.name.slice(".hermes-".length);
    if (!name) continue;
    const home = path.join(HOME, entry.name);
    discovered.push({ name, home, role: soulSummary(home) });
  }

  const fromFabric = new Map();
  for (const entry of scanFabric()) {
    if (!entry.agent || fromFabric.has(entry.agent)) continue;
    const home = path.join(HOME, `.hermes-${entry.agent}`);
    fromFabric.set(entry.agent, {
      name: entry.agent,
      home,
      role: soulSummary(home),
    });
  }

  for (const agent of discovered) fromFabric.set(agent.name, agent);
  return [...fromFabric.values()].sort((a, b) => a.name.localeCompare(b.name));
}

function parseCycles(md) {
  const out = [];
  for (const b of md.split(/^---$/m)) { const m = b.match(/## Cycle (\d+)/); if (!m) continue;
    const ts = (b.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC)/)||[])[1]||"";
    const thought = (b.match(/\*\*Thought:\*\* ([\s\S]*?)(?=\n\n\*\*|\n*$)/)||[])[1]||"";
    out.push({ cycle: +m[1], timestamp: ts, thought: thought.trim() });
  } return out;
}

function gatewayOnline(gw) {
  if (!gw) return false;
  if (gw.gateway_state === "running") {
    const updated = Date.parse(gw.updated_at || "");
    if (Number.isFinite(updated) && Date.now() - updated < 10 * 60 * 1000) return true;
  }
  if (!gw.pid) return false;
  try {
    process.kill(gw.pid, 0);
    return true;
  } catch {
    return false;
  }
}

function scanFabric() {
  if (!fs.existsSync(FABRIC)) return [];
  const entries = [];
  for (const dir of [FABRIC, path.join(FABRIC, "cold")]) {
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir).filter(f => f.endsWith(".md"))) {
      const content = safe(path.join(dir, f)), h = content.slice(0, 800);
      const get = (key) => (h.match(new RegExp(`^${key}: (.+)$`, "m"))||[])[1]||"";
      entries.push({ file: f, agent: get("agent"), platform: get("platform"), type: get("type"),
        tier: get("tier"), timestamp: get("timestamp"), summary: get("summary"),
        project_id: get("project_id"), session_id: get("session_id"), id: get("id"),
        body: content.split("---").slice(2).join("---").trim().slice(0, 300) });
    }
  }
  return entries.sort((a,b) => b.timestamp.localeCompare(a.timestamp));
}

function parseTimestamp(ts) {
  if (!ts) return null;
  const date = new Date(ts + (ts.includes("Z") ? "" : " UTC"));
  return Number.isNaN(date.getTime()) ? null : date;
}

function minutesSince(ts) {
  const date = parseTimestamp(ts);
  if (!date) return null;
  return Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
}

function classifyAgentStatus({ online, lastActiveMinutes, entries }) {
  if (!online) return "offline";
  if (entries === 0) return "idle";
  if (lastActiveMinutes == null) return "idle";
  if (lastActiveMinutes > 12 * 60) return "stale";
  return "healthy";
}

function agentData(a, entries) {
  const home = a.home || path.join(HOME, ".hermes-" + a.name);
  const gw = jf(path.join(home, "gateway_state.json")); let online = false, plats = {};
  if (gw) { online = gatewayOnline(gw); plats = gw.platforms || {}; }
  const env = safe(path.join(home, ".env"));
  const cp = [];
  if (env.includes("TELEGRAM_BOT_TOKEN")) cp.push({ name: "telegram", state: plats.telegram?.state||"offline", color: "#229ED9" });
  if (env.includes("DISCORD_BOT_TOKEN")) cp.push({ name: "discord", state: plats.discord?.state||"offline", color: "#5865F2" });
  if (env.includes("SLACK_BOT_TOKEN")) cp.push({ name: "slack", state: plats.slack?.state||"offline", color: "#611f69" });
  if (env.includes("WHATSAPP_ENABLED")) cp.push({ name: "whatsapp", state: "configured", color: "#25D366" });
  if (env.includes("SIGNAL_HTTP_URL")) cp.push({ name: "signal", state: "configured", color: "#3A76F0" });
  if (env.includes("EMAIL_ADDRESS")) cp.push({ name: "email", state: "configured", color: "#6b7280" });
  const cycles = parseCycles(safe(path.join(ROOT, "examples/hermes-demo/" + a.name + "-log.md")));
  const agentEntries = entries.filter(e => e.agent === a.name);
  const latestEntry = agentEntries[0];
  const today = new Date().toISOString().slice(0, 10);
  const weekCutoff = Date.now() - 7 * 864e5;
  const lastActive = cycles.length > 0 ? cycles[cycles.length-1].timestamp : (latestEntry?.timestamp || "");
  const lastActiveMinutes = minutesSince(lastActive);
  const status = classifyAgentStatus({ online, lastActiveMinutes, entries: agentEntries.length });
  return { name: a.name, role: a.role||"", online, platforms: cp, cycles: cycles.length,
    entries: agentEntries.length,
    lastActive,
    lastOutput: cycles.length > 0 ? cycles[cycles.length-1].thought.slice(0, 120) : ((latestEntry?.summary || latestEntry?.body || "").slice(0, 120)),
    status,
    lastActiveMinutes,
    entriesToday: agentEntries.filter(e => (e.timestamp || "").startsWith(today)).length,
    entries7d: agentEntries.filter(e => {
      const date = parseTimestamp(e.timestamp);
      return date ? date.getTime() >= weekCutoff : false;
    }).length,
    projectCount: new Set(agentEntries.map(e => e.project_id).filter(Boolean)).size,
    sessionCount: new Set(agentEntries.map(e => e.session_id).filter(Boolean)).size,
  };
}

function buildTelemetry(agents, entries) {
  const totalEntries = entries.length || 1;
  const projectMap = new Map();
  const platformStates = {};
  const health = { healthyAgents: 0, staleAgents: 0, idleAgents: 0, offlineAgents: 0, silentAgents: 0 };

  for (const agent of agents) {
    if (agent.status === "healthy") health.healthyAgents += 1;
    if (agent.status === "stale") health.staleAgents += 1;
    if (agent.status === "idle") health.idleAgents += 1;
    if (agent.status === "offline") health.offlineAgents += 1;
    if (!agent.entries) health.silentAgents += 1;

    for (const platform of agent.platforms || []) {
      if (!platformStates[platform.name]) platformStates[platform.name] = {};
      const state = platform.state || "unknown";
      platformStates[platform.name][state] = (platformStates[platform.name][state] || 0) + 1;
    }
  }

  for (const entry of entries) {
    const id = entry.project_id || "unscoped";
    if (!projectMap.has(id)) projectMap.set(id, { id, entries: 0, agents: new Set(), sessions: new Set() });
    const p = projectMap.get(id);
    p.entries += 1;
    if (entry.agent) p.agents.add(entry.agent);
    if (entry.session_id) p.sessions.add(entry.session_id);
  }

  const projects = [...projectMap.values()]
    .map((p) => ({ id: p.id, entries: p.entries, agents: p.agents.size, sessions: p.sessions.size }))
    .sort((a, b) => b.entries - a.entries)
    .slice(0, 8);

  const scopedProjects = entries.filter((e) => e.project_id).length;
  const scopedSessions = entries.filter((e) => e.session_id).length;
  const projectIds = new Set(entries.map((e) => e.project_id).filter(Boolean));
  const sessionIds = new Set(entries.map((e) => e.session_id).filter(Boolean));
  const multiPlatformAgents = agents.filter((agent) => new Set((agent.platforms || []).map((p) => p.name)).size > 1).length;

  return {
    health,
    memory: {
      hotRate: round(entries.filter((e) => e.tier === "hot").length / totalEntries),
      coldRate: round(entries.filter((e) => e.tier === "cold").length / totalEntries),
      unscopedEntries: entries.filter((e) => !e.project_id || !e.session_id).length,
      projectCoverage: round(scopedProjects / totalEntries),
      sessionCoverage: round(scopedSessions / totalEntries),
    },
    coordination: {
      multiPlatformAgents,
      avgPlatformsPerAgent: round(agents.reduce((sum, agent) => sum + (agent.platforms?.length || 0), 0) / Math.max(agents.length, 1)),
      avgEntriesPerAgent: round(entries.length / Math.max(agents.length, 1)),
      avgEntriesPerProject: round(entries.length / Math.max(projectIds.size, 1)),
      avgEntriesPerSession: round(entries.length / Math.max(sessionIds.size, 1)),
    },
    platformStates,
    leaders: {
      byEntries: [...agents]
        .sort((a, b) => (b.entries || 0) - (a.entries || 0))
        .slice(0, 5)
        .map((agent) => ({ name: agent.name, value: agent.entries || 0 })),
      byToday: [...agents]
        .sort((a, b) => (b.entriesToday || 0) - (a.entriesToday || 0))
        .slice(0, 5)
        .map((agent) => ({ name: agent.name, value: agent.entriesToday || 0 })),
      byProjects: [...agents]
        .sort((a, b) => (b.projectCount || 0) - (a.projectCount || 0))
        .slice(0, 5)
        .map((agent) => ({ name: agent.name, value: agent.projectCount || 0 })),
    },
    projects,
  };
}

function getData() {
  const entries = scanFabric();
  const agents = parseAgents().map((agent) => agentData(agent, entries));
  const today = new Date().toISOString().slice(0, 10);
  const hot = entries.filter(e => e.tier === "hot").length;
  const warm = entries.filter(e => e.tier === "warm").length;
  const cold = entries.filter(e => e.tier === "cold").length;
  const platDist = {}; entries.forEach(e => { platDist[e.platform||"cli"] = (platDist[e.platform||"cli"]||0)+1; });
  const typeDist = {}; entries.forEach(e => { typeDist[e.type||"other"] = (typeDist[e.type||"other"]||0)+1; });
  // cross-platform
  const agentPlats = {};
  entries.forEach(e => { if (!agentPlats[e.agent]) agentPlats[e.agent] = new Set(); agentPlats[e.agent].add(e.platform); });
  let xRecalls = 0;
  Object.values(agentPlats).forEach(s => { if (s.size > 1) xRecalls += s.size - 1; });
  // timeline
  const timeline = {};
  for (let i = 13; i >= 0; i--) { const d = new Date(Date.now() - i*864e5).toISOString().slice(0,10); timeline[d] = {}; agents.forEach(a => timeline[d][a.name] = 0); }
  entries.forEach(e => { const d = e.timestamp.slice(0,10); if (timeline[d]) timeline[d][e.agent] = (timeline[d][e.agent]||0)+1; });
  const telemetry = buildTelemetry(agents, entries);

  return { agents, entries: entries.slice(0, 50), stats: {
    totalAgents: agents.length, activeAgents: agents.filter(a => a.online).length,
    totalEntries: entries.length, entriesToday: entries.filter(e => e.timestamp.startsWith(today)).length,
    hot, warm, cold, brainSize: (() => { let t=0; for (const dir of [FABRIC, path.join(FABRIC, "cold")]) { try { fs.readdirSync(dir).forEach(f => { try { t+=fs.statSync(path.join(dir,f)).size } catch {} }) } catch {} } return t })(),
    xRecalls, uptime: Math.floor((Date.now()-START)/1000),
  }, platDist, typeDist, timeline, telemetry };
}

// ── Wiki (Icarus persistent knowledge layer) ─────────────────

const WIKI_DIR = path.join(FABRIC, "wiki");
const WIKI_SUBS = ["entities", "topics", "sources", "indexes", "notes"];

function wikiTypeForSubdir(sub, fmType) {
  if (fmType) return fmType;
  if (sub === "indexes") return "index";
  return sub.replace(/s$/, "");
}

function parseWikiFrontmatter(text) {
  const m = text.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!m) return { fm: {}, body: text };
  const fm = {};
  m[1].split("\n").forEach((line) => {
    const i = line.indexOf(":");
    if (i < 0) return;
    const k = line.slice(0, i).trim();
    let v = line.slice(i + 1).trim();
    if (v.startsWith('"') && v.endsWith('"')) v = v.slice(1, -1);
    fm[k] = v;
  });
  return { fm, body: text.slice(m[0].length) };
}

function extractLinks(text) {
  const out = [];
  const re = /\[\[([^\]]+)\]\]/g;
  let m;
  while ((m = re.exec(text)) !== null) out.push(m[1]);
  return Array.from(new Set(out));
}

function scanWiki() {
  const pages = [];
  if (!exists(WIKI_DIR)) return { pages, indexBody: "", logBody: "", homeBody: "" };
  for (const sub of WIKI_SUBS) {
    const d = path.join(WIKI_DIR, sub);
    if (!exists(d)) continue;
    for (const f of fs.readdirSync(d)) {
      if (!f.endsWith(".md")) continue;
      const full = path.join(d, f);
      const text = safe(full);
      const { fm, body } = parseWikiFrontmatter(text);
      pages.push({
        path: `${sub}/${f.replace(/\.md$/, "")}`,
        type: wikiTypeForSubdir(sub, fm.type),
        title: fm.title || f.replace(/\.md$/, ""),
        summary: fm.summary || "",
        frontmatter: fm,
        body,
        links: extractLinks(body),
        updated: fm.updated || fm.created || "",
      });
    }
  }
  pages.sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
  return {
    pages,
    indexBody: safe(path.join(WIKI_DIR, "index.md")),
    logBody: safe(path.join(WIKI_DIR, "log.md")),
    homeBody: safe(path.join(WIKI_DIR, "Home.md")),
  };
}

function readWikiPage(relPath) {
  const safeRel = String(relPath || "").replace(/^\/+/, "");
  if (safeRel.includes("..") || !safeRel.endsWith(".md")) return null;
  const full = path.join(WIKI_DIR, safeRel);
  if (!full.startsWith(WIKI_DIR + path.sep) && full !== WIKI_DIR) return null;
  if (!exists(full)) return null;
  const text = safe(full);
  const { fm, body } = parseWikiFrontmatter(text);
  return {
    path: safeRel.replace(/\.md$/, ""),
    frontmatter: fm,
    body,
    links: extractLinks(body),
  };
}

function createServer() {
  return http.createServer((req, res) => {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Content-Type", "application/json");
    if (req.url === "/api/data") { res.end(JSON.stringify(getData())); return; }
    if (req.url === "/api/entries") { res.end(JSON.stringify(scanFabric())); return; }
    if (req.url === "/api/health") { res.end(JSON.stringify({ ok: true })); return; }
    if (req.url === "/api/wiki/pages") { res.end(JSON.stringify(scanWiki())); return; }
    if (req.url && req.url.startsWith("/api/wiki/page")) {
      const u = new URL(req.url, `http://${HOST}`);
      const p = u.searchParams.get("path");
      const page = readWikiPage(p ? `${p}.md` : "");
      if (!page) { res.writeHead(404); res.end("{}"); return; }
      res.end(JSON.stringify(page));
      return;
    }
    res.writeHead(404); res.end("{}");
  });
}

if (require.main === module) {
  createServer().listen(PORT, HOST, () => console.log(`API: http://${HOST}:${PORT}`));
}

module.exports = {
  AGENTS_FILE,
  FABRIC,
  HOST,
  PORT,
  createServer,
  getData,
  parseAgents,
  scanFabric,
  scanWiki,
  readWikiPage,
};
