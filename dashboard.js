const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = 3000;
const ROOT = __dirname;
const HOME = process.env.HOME || process.env.USERPROFILE;
if (!HOME) { console.error("error: HOME environment variable not set"); process.exit(1); }

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

const AGENT_PATHS = {
  icarus: path.join(HOME, ".hermes-icarus"),
  daedalus: path.join(HOME, ".hermes-daedalus"),
};

function readSafe(p) {
  try { return fs.readFileSync(p, "utf-8"); } catch { return ""; }
}

function readJson(p) {
  try { return JSON.parse(fs.readFileSync(p, "utf-8")); } catch { return null; }
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

function getAgentInfo(name, agentPath) {
  const soul = readSafe(path.join(agentPath, "SOUL.md"));
  const gwState = readJson(path.join(agentPath, "gateway_state.json"));
  const env = readSafe(path.join(agentPath, ".env"));
  const hasTelegram = env.includes("TELEGRAM_BOT_TOKEN");
  const hasSlack = env.includes("SLACK_WEBHOOK_URL");
  const model = (env.match(/LLM_MODEL=(.+)/)||[])[1] || "unknown";

  let gatewayUp = false;
  let platforms = {};
  if (gwState) {
    // Check if the PID is actually running
    try { process.kill(gwState.pid, 0); gatewayUp = true; } catch { gatewayUp = false; }
    platforms = gwState.platforms || {};
  }

  return {
    name,
    soul: soul.slice(0, 300) + (soul.length > 300 ? "..." : ""),
    model,
    gateway: gatewayUp ? "running" : "stopped",
    platforms: {
      telegram: hasTelegram ? (platforms.telegram?.state || "configured") : "not configured",
      slack: hasSlack ? "configured" : "not configured",
    },
    memoryBytes: Buffer.byteLength(readSafe(path.join(agentPath, "memories/MEMORY.md"))),
  };
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

  const allText = icarusRaw + daedalusRaw + icarusCodeRaw + daedalusCodeRaw;
  const worldUrls = [...new Set((allText.match(/https:\/\/(?:marble\.)?worldlabs\.ai\/world\/[a-f0-9-]+/g) || []))];

  return {
    dialogue: { icarus, daedalus },
    codeReview: { icarus: icarusCode, daedalus: daedalusCode },
    memory: {
      icarus: { content: icarusMem, bytes: Buffer.byteLength(icarusMem) },
      daedalus: { content: daedalusMem, bytes: Buffer.byteLength(daedalusMem) },
    },
    agents: {
      icarus: getAgentInfo("icarus", AGENT_PATHS.icarus),
      daedalus: getAgentInfo("daedalus", AGENT_PATHS.daedalus),
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

const sseClients = new Set();

function broadcast() {
  const data = JSON.stringify(getStats());
  for (const res of sseClients) res.write("data: " + data + "\n\n");
}

const watched = new Set();
function watchFiles() {
  for (const f of [...Object.values(LOG_FILES), ...Object.values(MEMORY_FILES),
    ...Object.values(AGENT_PATHS).map(p => path.join(p, "gateway_state.json"))]) {
    if (watched.has(f)) continue;
    try { fs.watch(f, { persistent: false }, () => broadcast()); watched.add(f); } catch {}
  }
}
watchFiles();
setInterval(watchFiles, 5000);

const HTML = fs.readFileSync(path.join(ROOT, "dashboard.html"), "utf-8");


const server = http.createServer((req, res) => {
  if (req.url === "/api/stats") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(getStats()));
    return;
  }
  if (req.url === "/api/stream") {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    res.write("data: " + JSON.stringify(getStats()) + "\n\n");
    sseClients.add(res);
    req.on("close", () => sseClients.delete(res));
    return;
  }
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(HTML);
});

server.listen(PORT, () => console.log("dashboard: http://localhost:" + PORT));
