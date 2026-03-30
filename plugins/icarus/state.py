"""Shared state: fabric I/O, retriever, training helpers, creative state."""

import json
import logging
import os
import re
import secrets
import subprocess
import tempfile
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

FABRIC_DIR = Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric"))
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "")) if os.environ.get("HERMES_HOME") else None
AGENT_NAME = os.environ.get("HERMES_AGENT_NAME", "")
PLUGIN_DIR = Path(__file__).parent

if not AGENT_NAME and HERMES_HOME and ".hermes-" in str(HERMES_HOME):
    AGENT_NAME = str(HERMES_HOME).split(".hermes-")[-1].rstrip("/")

# ── Session state ────────────────────────────────────────
session_id = ""
exchanges: list = []

# ── Training job tracking ────────────────────────────────
_JOB_FILE = (HERMES_HOME or Path.home()) / ".icarus-training-job.txt"


def _last_job_id():
    if _JOB_FILE.exists():
        return _JOB_FILE.read_text("utf-8").strip()
    return ""


def _save_job_id(jid):
    _JOB_FILE.write_text(jid, "utf-8")


# ── Creative state ───────────────────────────────────────
_STATE_FILE = (HERMES_HOME or Path.home()) / ".icarus-state.json"


def load_creative():
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {"cycle": 0, "themes": [], "questions": [], "learnings": []}


def save_creative(s):
    try:
        _STATE_FILE.write_text(json.dumps(s, indent=2), "utf-8")
    except Exception as exc:
        logger.warning("icarus: save state failed: %s", exc)


# ── Fabric I/O ───────────────────────────────────────────

def write_entry(entry_type, content, summary, tier="hot", tags="", platform="cli",
                status="", outcome="", review_of="", revises="", customer_id="", assigned_to=""):
    """Write a fabric entry with full schema v1 fields. Returns the filepath."""
    FABRIC_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H%MZ")
    ts_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    agent = AGENT_NAME or "agent"
    suffix = secrets.token_hex(2)
    filename = f"{agent}-{entry_type}-{ts}-{suffix}.md"

    sid = session_id or os.environ.get(
        "FABRIC_SESSION_ID", f"sess-{now.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}")
    project_id = os.environ.get(
        "FABRIC_PROJECT_ID",
        Path.cwd().name if Path.cwd() != Path.home() else "unknown")

    lines = [
        "---",
        f"id: {secrets.token_hex(4)}",
        f"agent: {agent}",
        f"platform: {platform}",
        f"timestamp: {ts_iso}",
        f"type: {entry_type}",
        f"tier: {tier}",
        f"summary: {summary}",
        f"project_id: {project_id}",
        f"session_id: {sid}",
    ]
    if tags:
        lines.append(f"tags: [{tags}]")
    if status:
        lines.append(f"status: {status}")
    if outcome:
        lines.append(f"outcome: {outcome}")
    if review_of:
        lines.append(f"review_of: {review_of}")
    if revises:
        lines.append(f"revises: {revises}")
    if customer_id:
        lines.append(f"customer_id: {customer_id}")
    if assigned_to:
        lines.append(f"assigned_to: {assigned_to}")
    lines.extend(["---", "", content])

    path = FABRIC_DIR / filename
    path.write_text("\n".join(lines), "utf-8")
    logger.info("icarus: wrote %s", filename)
    return str(path)


def read_recent(agent="", limit=5):
    """Read recent hot entries."""
    if not FABRIC_DIR.exists():
        return []
    out = []
    for f in sorted(FABRIC_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        head = f.read_text("utf-8")[:600]
        if "tier: hot" not in head:
            continue
        if agent and f"agent: {agent}" not in head:
            continue
        summary = ""
        m = re.search(r"^summary: (.+)$", head, re.MULTILINE)
        if m:
            summary = m.group(1)
        entry_agent = ""
        m = re.search(r"^agent: (.+)$", head, re.MULTILINE)
        if m:
            entry_agent = m.group(1)
        ts = ""
        m = re.search(r"^timestamp: (.+)$", head, re.MULTILINE)
        if m:
            ts = m.group(1)
        out.append({"agent": entry_agent, "timestamp": ts, "summary": summary})
        if len(out) >= limit:
            break
    return out


def read_cross_agent(limit=3):
    """Read recent entries from OTHER agents."""
    if not FABRIC_DIR.exists():
        return []
    out = []
    for f in sorted(FABRIC_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        head = f.read_text("utf-8")[:600]
        if AGENT_NAME and f"agent: {AGENT_NAME}" in head:
            continue
        if not any(t in head for t in ("type: review", "type: dialogue", "type: decision")):
            continue
        agent = ""
        m = re.search(r"^agent: (.+)$", head, re.MULTILINE)
        if m:
            agent = m.group(1)
        summary = ""
        m = re.search(r"^summary: (.+)$", head, re.MULTILINE)
        if m:
            summary = m.group(1)
        if summary:
            out.append(f"{agent}: {summary}")
        if len(out) >= limit:
            break
    return out


def _parse_head(filepath, max_bytes=800):
    """Parse frontmatter fields from a fabric entry header."""
    text = filepath.read_text("utf-8")[:max_bytes]
    fields = {}
    for key in ("agent", "type", "tier", "status", "summary", "timestamp",
                "review_of", "revises", "customer_id", "assigned_to", "id", "outcome"):
        m = re.search(rf"^{key}: (.+)$", text, re.MULTILINE)
        if m:
            fields[key] = m.group(1)
    fields["file"] = filepath.name
    return fields


def has_entry_ref(ref):
    """Return True when agent:id resolves to a real fabric entry."""
    if not ref or ":" not in ref or not FABRIC_DIR.exists():
        return False
    agent, entry_id = ref.split(":", 1)
    agent = agent.strip()
    entry_id = entry_id.strip()
    if not agent or not entry_id:
        return False

    for d in (FABRIC_DIR, FABRIC_DIR / "cold"):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            h = _parse_head(f)
            if h.get("agent", "").strip() == agent and h.get("id", "").strip() == entry_id:
                return True
    return False


def read_pending(customer_id=None):
    """Find entries needing this agent's attention.

    Returns three lists:
      open_tasks  - status:open entries explicitly assigned to THIS agent
      reviews     - type:review entries from OTHER agents that review THIS agent's work
      open_tickets - status:open customer-scoped entries explicitly assigned to THIS agent
    """
    if not FABRIC_DIR.exists():
        return [], [], []

    agent = AGENT_NAME
    open_tasks = []
    reviews = []
    open_tickets = []

    for f in sorted(FABRIC_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        h = _parse_head(f)
        entry_agent = h.get("agent", "")

        assigned_to = h.get("assigned_to", "").strip()

        # open tasks from other agents that explicitly target this agent
        if h.get("status") == "open" and entry_agent != agent:
            if not agent or assigned_to != agent:
                continue
            if customer_id and h.get("customer_id") != customer_id:
                continue
            open_tasks.append(h)

        # reviews of my work (from other agents)
        if h.get("type") == "review" and entry_agent != agent:
            ref = h.get("review_of", "")
            if agent and ref.startswith(f"{agent}:"):
                reviews.append(h)

        # open tickets with customer_id explicitly assigned to this agent
        if h.get("status") == "open" and h.get("customer_id"):
            if not agent or assigned_to != agent:
                continue
            if customer_id and h.get("customer_id") != customer_id:
                continue
            if h not in open_tasks:
                open_tickets.append(h)

        if len(open_tasks) + len(reviews) + len(open_tickets) >= 30:
            break

    return open_tasks, reviews, open_tickets


def search_entries(query, limit=10):
    """Keyword search across fabric."""
    if not FABRIC_DIR.exists():
        return []
    results = []
    q = query.lower()
    for d in [FABRIC_DIR, FABRIC_DIR / "cold"]:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            text = f.read_text("utf-8")
            if q not in text.lower():
                continue
            summary = ""
            m = re.search(r"^summary: (.+)$", text[:500], re.MULTILINE)
            if m:
                summary = m.group(1)
            agent = ""
            m = re.search(r"^agent: (.+)$", text[:500], re.MULTILINE)
            if m:
                agent = m.group(1)
            # find matching lines
            matches = [line.strip() for line in text.split("\n") if q in line.lower()][:3]
            results.append({"file": f.name, "agent": agent, "summary": summary, "matches": matches})
            if len(results) >= limit:
                return results
    return results


# ── Retriever ────────────────────────────────────────────

_retriever = None


def _load_retriever():
    paths = [
        PLUGIN_DIR / "fabric-retrieve.py",
        Path(os.environ.get("FABRIC_RETRIEVE_PATH", "")),
    ]
    if HERMES_HOME:
        paths.append(HERMES_HOME / "plugins" / "icarus" / "fabric-retrieve.py")
        paths.append(HERMES_HOME / "plugins" / "fabric-memory" / "fabric-retrieve.py")
    for p in paths:
        if p and p.exists():
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("fabric_retrieve", str(p))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.FABRIC_DIR = FABRIC_DIR
                return mod
            except Exception as exc:
                logger.debug("icarus: retriever load failed from %s: %s", p, exc)
    return None


def recall(query, max_results=5, agent=None, project=None):
    """Smart ranked retrieval. Falls back to read_recent."""
    global _retriever
    if _retriever is None:
        _retriever = _load_retriever()
    if _retriever is None:
        return read_recent(agent, max_results)

    _retriever.FABRIC_DIR = FABRIC_DIR
    try:
        results = _retriever.retrieve(query, max_results=max_results, agent=agent, project=project)
        return [{"score": score, **entry} for score, entry in results]
    except Exception as exc:
        logger.debug("icarus: retrieval error: %s", exc)
        return read_recent(agent, max_results)


# ── Training ─────────────────────────────────────────────

def _together_key():
    key = os.environ.get("TOGETHER_API_KEY", "")
    if key:
        return key
    # check agent .env
    if HERMES_HOME and (HERMES_HOME / ".env").exists():
        for line in (HERMES_HOME / ".env").read_text().split("\n"):
            if line.startswith("TOGETHER_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _together_request(method, url, data=None):
    """Make an authenticated request to Together AI. Returns parsed JSON."""
    key = _together_key()
    if not key:
        raise RuntimeError("TOGETHER_API_KEY not set")
    headers = {"Authorization": f"Bearer {key}"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def export_training():
    """Export fabric entries as training pairs. Returns stats dict."""
    export_script = PLUGIN_DIR / "export-training.py"
    if not export_script.exists():
        # try repo root
        repo_root = PLUGIN_DIR.parent.parent
        export_script = repo_root / "export-training.py"
    if not export_script.exists():
        return {"error": "export-training.py not found"}

    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["python3", str(export_script), "--output", tmpdir],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return {"error": result.stderr or "export failed"}

        # parse output for stats
        output = result.stdout
        pairs = 0
        m = re.search(r"total pairs:\s+(\d+)", output)
        if m:
            pairs = int(m.group(1))

        tokens = 0
        m = re.search(r"estimated tokens:\s+([\d,]+)", output)
        if m:
            tokens = int(m.group(1).replace(",", ""))

        # read the together.jsonl for upload
        together_path = Path(tmpdir) / "together.jsonl"
        training_data = together_path.read_text("utf-8") if together_path.exists() else ""

        return {
            "pairs": pairs,
            "estimated_tokens": tokens,
            "output": output.strip(),
            "training_data_path": str(together_path) if together_path.exists() else None,
            "_training_data": training_data,
        }


def start_training(model=None, suffix=None, epochs=3, batch_size=None, learning_rate=None, checkpoints=None):
    """Export, upload, and start a Together AI fine-tune. Returns job ID."""
    key = _together_key()
    if not key:
        return {"error": "TOGETHER_API_KEY not set in .env"}

    # export
    export = export_training()
    if "error" in export:
        return export
    if export["pairs"] < 10:
        return {"error": f"only {export['pairs']} pairs, need at least 10"}

    training_data = export.get("_training_data", "")
    if not training_data:
        return {"error": "no training data produced"}

    # upload via multipart form
    boundary = secrets.token_hex(16)
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="purpose"\r\n\r\nfine-tune\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="training.jsonl"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
        f"{training_data}\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    req = urllib.request.Request(
        "https://api.together.xyz/v1/files/upload",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        upload_data = json.loads(resp.read())
    except Exception as exc:
        return {"error": f"upload failed: {exc}"}

    file_id = upload_data.get("id", "")
    if not file_id:
        return {"error": "upload succeeded but no file ID returned"}

    # start fine-tune
    agent = AGENT_NAME or "agent"
    ft_model = model or os.environ.get("TOGETHER_MODEL", "Qwen/Qwen2-7B-Instruct")
    ft_suffix = suffix or os.environ.get("TOGETHER_SUFFIX", f"{agent}-v1")
    ft_batch = int(batch_size if batch_size is not None else os.environ.get("TOGETHER_BATCH_SIZE", "8"))
    ft_lr = float(learning_rate if learning_rate is not None else os.environ.get("TOGETHER_LR", "1e-5"))
    ft_checkpoints = int(checkpoints if checkpoints is not None else os.environ.get("TOGETHER_CHECKPOINTS", "1"))

    if ft_batch < 8:
        return {"error": f"batch_size must be >= 8 (got {ft_batch})"}
    if ft_lr <= 0:
        return {"error": f"learning_rate must be > 0 (got {ft_lr})"}
    if ft_checkpoints < 1:
        return {"error": f"n_checkpoints must be >= 1 (got {ft_checkpoints})"}

    try:
        ft_data = _together_request("POST", "https://api.together.xyz/v1/fine-tunes", {
            "training_file": file_id,
            "model": ft_model,
            "n_epochs": epochs,
            "suffix": ft_suffix,
            "batch_size": ft_batch,
            "learning_rate": ft_lr,
            "n_checkpoints": ft_checkpoints,
        })
    except Exception as exc:
        return {"error": f"fine-tune start failed: {exc}"}

    job_id = ft_data.get("id", "")
    if not job_id:
        return {"error": "fine-tune accepted but no job ID"}

    _save_job_id(job_id)

    return {
        "job_id": job_id,
        "model": ft_model,
        "suffix": ft_suffix,
        "epochs": epochs,
        "batch_size": ft_batch,
        "learning_rate": ft_lr,
        "n_checkpoints": ft_checkpoints,
        "pairs": export["pairs"],
        "file_id": file_id,
    }


def check_training(job_id=None):
    """Check a Together AI fine-tune job status."""
    jid = job_id or _last_job_id()
    if not jid:
        return {"error": "no job ID — run fabric_train first"}
    try:
        data = _together_request("GET", f"https://api.together.xyz/v1/fine-tunes/{jid}")
    except Exception as exc:
        return {"error": f"status check failed: {exc}"}

    result = {"job_id": jid, "status": data.get("status", "unknown")}
    if data.get("status") == "completed":
        result["model_id"] = data.get("model_output_name", "")
        result["instruction"] = (
            f"Set in .env: LLM_MODEL={result['model_id']}"
        )
    if data.get("status") in ("failed", "cancelled", "error"):
        result["error"] = data.get("error", "unknown")
    return result


# ── SOUL ─────────────────────────────────────────────────

def load_soul():
    if HERMES_HOME:
        soul = HERMES_HOME / "SOUL.md"
        if soul.exists():
            return soul.read_text("utf-8")
    return ""


# ── Memory file ──────────────────────────────────────────

def write_memory_file(s):
    if not HERMES_HOME:
        return
    mem_dir = HERMES_HOME / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    agent = AGENT_NAME or "agent"
    lines = [f"# {agent} memory\n"]
    if s.get("questions"):
        lines.append("## open questions")
        for q in s["questions"][-5:]:
            lines.append(f"- {q}")
        lines.append("")
    if s.get("learnings"):
        lines.append("## learnings")
        for ln in s["learnings"][-5:]:
            lines.append(f"- {ln}")
        lines.append("")
    lines.append(f"cycles: {s.get('cycle', 0)}")
    (mem_dir / "MEMORY.md").write_text("\n".join(lines), "utf-8")
