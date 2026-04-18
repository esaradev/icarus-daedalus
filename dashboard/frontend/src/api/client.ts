export type Agent = {
  id: string;
  name: string;
  platform: string;
  status: string;
  current_task: string | null;
  last_seen_at: string | null;
};

export type Counts = {
  healthy: number; idle: number; stale: number; offline: number; blocked: number;
};

export type Metrics = {
  recall_success_rate: number;
  recall_sample_size: number;
  reuse_rate: number;
  verification_rate: number;
  entries_today: number;
  promotions_today: number;
  stale_knowledge_count: number;
  contradiction_count: number;
  unresolved_handoffs: number;
};

export type MemoryEntry = {
  id: number;
  author_agent_id: string | null;
  author_name?: string | null;
  session_id: string | null;
  project_id: string | null;
  kind: string;
  source: string;
  title: string;
  body: string;
  verified_at: string | null;
  reuse_count: number;
  created_at: string;
  updated_at: string;
  score?: number;
  signals?: { relevance: number; recency: number; reuse: number; trust: number };
};

export type ProjectActivity = { project_id: string; name: string; entries_24h: number };

export type FleetOut = {
  agents: Agent[]; counts: Counts; metrics: Metrics; highlights: MemoryEntry[];
  projects: ProjectActivity[];
};

export type EventRow = {
  id: number; agent_id: string | null; agent_name: string | null;
  session_id: string | null; source: string; kind: string; payload: Record<string, unknown>; occurred_at: string;
};

export type Recall = {
  id: number; agent_id: string | null; session_id: string | null;
  source: string; query: string; returned_entry_ids: number[]; was_useful: boolean | null; created_at: string;
};

export type SourceCount = {
  source: string;
  count: number;
};

export type SourceDebug = {
  agents: SourceCount[];
  events: SourceCount[];
  memory_entries: SourceCount[];
  recalls: SourceCount[];
};

export type AgentDetail = {
  agent: Agent;
  recent_writes: MemoryEntry[];
  recent_recalls: Recall[];
  contribution: { write_volume_7d: number; reuse_rate: number; verification_rate: number };
  writes_by_day: { date: string; count: number }[];
};

export type ProvenanceEdge = {
  id: number; src_type: string; src_id: string; dst_type: string; dst_id: string;
  relation: string; created_at: string;
};

export type MemoryDetail = MemoryEntry & {
  edges_in: ProvenanceEdge[]; edges_out: ProvenanceEdge[]; recalled_by: Recall[];
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  fleet: () => get<FleetOut>("/fleet"),
  activity: (limit = 50) => get<EventRow[]>(`/fleet/activity?limit=${limit}`),
  sourceDebug: () => get<SourceDebug>("/debug/sources"),
  agent: (id: string) => get<AgentDetail>(`/agents/${id}`),
  memory: (params: {
    q?: string; agent_id?: string; project_id?: string; kind?: string;
    verified?: boolean; since?: string; limit?: number; offset?: number;
  }) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined || v === null || v === "") return;
      qs.set(k, String(v));
    });
    return get<MemoryEntry[]>(`/memory?${qs.toString()}`);
  },
  memoryDetail: (id: number) => get<MemoryDetail>(`/memory/${id}`),
  topRecalled: () => get<MemoryEntry[]>(`/memory/top-recalled?window_days=7&limit=8`),
  topReused: () => get<MemoryEntry[]>(`/memory/top-reused?limit=8`),
  retrieve: (body: {
    query: string; agent_id?: string; project_id?: string; kind?: string;
    verified?: boolean; since?: string; limit?: number;
  }) => post<MemoryEntry[]>("/retrieve", body),
  rateRecall: (id: number, was_useful: boolean | null) =>
    patch<Recall>(`/recalls/${id}`, { was_useful }),
  wikiTree: () => get<WikiTree>("/wiki/tree"),
  wikiPages: (subdir: string, limit = 100, offset = 0) =>
    get<WikiPageSummary[]>(`/wiki/pages?subdir=${subdir}&limit=${limit}&offset=${offset}`),
  wikiPage: (path: string) =>
    get<WikiPageDetail>(`/wiki/page?path=${encodeURIComponent(path)}`),
  wikiHealth: () => get<WikiHealth>("/wiki/health"),
  wikiBacklinks: (memory_entry_id: number) =>
    get<WikiBacklink[]>(`/wiki/backlinks?memory_entry_id=${memory_entry_id}`),
  maintenanceStatus: () => get<MaintenanceStatus>("/maintenance/status"),
};

export type WikiTree = {
  subdirs: { name: string; count: number }[];
  total_pages: number;
  updated_at: string | null;
  wiki_dir: string;
};

export type WikiPageSummary = {
  slug: string; path: string; title: string; updated_at: string; size_bytes: number;
};

export type WikiForwardLink = { target: string; path: string | null; resolved: boolean };
export type WikiBacklink = { path: string; title: string };

export type WikiPageDetail = {
  path: string;
  slug: string;
  title: string;
  body_md: string;
  forward_links: WikiForwardLink[];
  backlinks: WikiBacklink[];
  sources: { ref?: string }[];
  updated_at: string;
  frontmatter: Record<string, unknown>;
};

export type MaintenanceStatus = {
  corpus: {
    total: number;
    quality_avg: number;
    stale_count: number;
    healthy_count: number;
    distribution: { range: string; count: number }[];
  };
  fabric: {
    total: number;
    cold_count: number;
    duplicate_count: number;
    stale_count: number;
    by_type: Record<string, number>;
  };
  wiki: {
    page_count: number;
    broken_links: number;
    orphan_pages: number;
  };
};

export type WikiHealth = {
  page_count: number;
  broken_links: { page?: string; missing?: string }[];
  orphan_pages: string[];
  pages_without_sources: string[];
  status: string;
  llm: { provider: string | null; model: string | null; status: string; reason: string };
};
