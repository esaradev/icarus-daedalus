import { useMemo, useState } from "react"
import { Search, FileText, Users, Tag, FolderOpen, BookOpen } from "lucide-react"
import { useWiki } from "../lib/api.ts"
import type { WikiPage } from "../lib/types.ts"
import { Stat } from "../components/stat.tsx"
import { cn } from "../lib/cn.ts"

const TYPE_ORDER = ["source", "entity", "topic", "index", "note"] as const
const TYPE_ICONS: Record<string, typeof FileText> = {
  source: FolderOpen,
  entity: Users,
  topic: Tag,
  index: BookOpen,
  note: FileText,
}

export function Icarus() {
  const { data, error } = useWiki()
  const [selected, setSelected] = useState<string | null>(null)
  const [q, setQ] = useState("")

  const pages = data?.pages ?? []

  const filtered = useMemo(() => {
    if (!q.trim()) return pages
    const needle = q.toLowerCase()
    return pages.filter((p) =>
      p.title.toLowerCase().includes(needle) ||
      p.summary.toLowerCase().includes(needle) ||
      p.body.toLowerCase().includes(needle)
    )
  }, [pages, q])

  const grouped = useMemo(() => {
    const g: Record<string, WikiPage[]> = {}
    filtered.forEach((p) => { (g[p.type] ||= []).push(p) })
    return g
  }, [filtered])

  const current = selected
    ? pages.find((p) => p.path === selected) ?? null
    : filtered[0] ?? null

  const lastIngest = useMemo(() => {
    const logBody = data?.logBody ?? ""
    const m = logBody.match(/- (\S+) ingested/g)
    if (!m || !m.length) return "—"
    const last = m[m.length - 1]
    return last.replace("- ", "").replace(" ingested", "")
  }, [data?.logBody])

  const sourceCount = pages.filter((p) => p.type === "source").length

  if (error && !data) {
    return (
      <p className="text-[13px] text-text-3">
        Cannot reach API. Run <code className="font-mono text-text-2">npm run server</code>
      </p>
    )
  }

  if (!data) return <p className="text-[11px] text-text-3">Loading&hellip;</p>

  if (pages.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-lg p-8 text-center">
        <BookOpen size={24} strokeWidth={1.5} className="text-text-3 mx-auto mb-3" />
        <p className="text-[14px] text-text-2 mb-1">No wiki pages yet.</p>
        <p className="text-[12px] text-text-3">
          Drop a file into <code className="font-mono text-text-2">~/fabric/raw/inbox/</code>,
          then call <code className="font-mono text-text-2">wiki_init</code> and
          <code className="font-mono text-text-2"> wiki_ingest</code>.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="bg-warning/10 border border-warning/30 rounded-lg px-3 py-2">
        <div className="text-[11px] text-warning font-medium">
          This view is now part of the Hermes dashboard.
        </div>
        <div className="text-[11px] text-text-2 mt-0.5">
          The canonical Icarus wiki view lives in the Hermes fork at{" "}
          <code className="font-mono">esaradev/hermes-agent</code> → <code className="font-mono">hermes dashboard</code> → Icarus.
          This page is kept for existing users and will stop receiving new features.
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Pages" value={pages.length} />
        <Stat label="Sources ingested" value={sourceCount} />
        <Stat label="Last ingest" value={lastIngest === "—" ? "—" : relTime(lastIngest)} />
      </div>

      <div className="grid grid-cols-[320px_1fr] gap-4">
        <div className="bg-surface border border-border rounded-lg overflow-hidden flex flex-col">
          <div className="p-2 border-b border-border">
            <div className="relative">
              <Search size={14} strokeWidth={1.5} className="absolute left-2 top-1/2 -translate-y-1/2 text-text-3" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search pages"
                className="w-full h-8 pl-7 pr-2 text-[12px] bg-bg border border-border rounded"
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto max-h-[70vh]">
            {TYPE_ORDER.map((t) => {
              const ps = grouped[t]
              if (!ps || ps.length === 0) return null
              const Icon = TYPE_ICONS[t] || FileText
              return (
                <div key={t}>
                  <div className="px-3 py-1.5 flex items-center gap-1.5 bg-surface-2 border-y border-border text-[11px] uppercase font-semibold text-text-3">
                    <Icon size={12} strokeWidth={1.5} />
                    {t}s
                    <span className="ml-auto tabular-nums">{ps.length}</span>
                  </div>
                  {ps.map((p) => (
                    <button
                      key={p.path}
                      onClick={() => setSelected(p.path)}
                      className={cn(
                        "w-full text-left px-3 py-2 border-b border-border hover:bg-surface-3 transition-colors",
                        (current?.path === p.path) && "bg-surface-3"
                      )}
                    >
                      <div className="text-[12px] font-medium text-text truncate">{p.title}</div>
                      {p.summary && (
                        <div className="text-[11px] text-text-3 truncate mt-0.5">{p.summary}</div>
                      )}
                    </button>
                  ))}
                </div>
              )
            })}
            {filtered.length === 0 && (
              <div className="px-3 py-6 text-[12px] text-text-3 text-center">No pages match.</div>
            )}
          </div>
        </div>

        <div className="bg-surface border border-border rounded-lg p-5 max-h-[calc(70vh+44px)] overflow-y-auto">
          {current ? <PageView page={current} onNavigate={(p) => setSelected(p)} pages={pages} /> : (
            <p className="text-[12px] text-text-3">Select a page.</p>
          )}
        </div>
      </div>
    </div>
  )
}

function relTime(iso: string) {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return iso
  const delta = (Date.now() - t) / 1000
  if (delta < 60) return `${Math.round(delta)}s ago`
  if (delta < 3600) return `${Math.round(delta / 60)}m ago`
  if (delta < 86400) return `${Math.round(delta / 3600)}h ago`
  return `${Math.round(delta / 86400)}d ago`
}

const MODE_STYLES: Record<string, string> = {
  llm: "border-accent/40 text-accent bg-accent/10",
  heuristic: "border-border text-text-3 bg-surface-3",
  "heuristic-no-key": "border-border text-text-3 bg-surface-3",
  "heuristic-fallback": "border-warning/40 text-warning bg-warning/10",
}

function PageView({ page, onNavigate, pages }: {
  page: WikiPage
  onNavigate: (p: string) => void
  pages: WikiPage[]
}) {
  const paths = new Set(pages.map((p) => p.path))
  const mode = page.frontmatter.extraction_mode
  const modeReason = page.frontmatter.extraction_reason
  return (
    <article>
      <div className="flex items-baseline justify-between mb-1">
        <h2 className="text-[16px] font-semibold">{page.title}</h2>
        <div className="flex items-center gap-2">
          {mode && (
            <span
              title={modeReason
                ? `How entity/topic pages were extracted from the source: ${modeReason}`
                : "How entity/topic pages were extracted from the source"}
              className={cn(
                "text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded border",
                MODE_STYLES[mode] || "border-border text-text-3"
              )}
            >
              {mode}
            </span>
          )}
          <span className="text-[11px] text-text-3 uppercase">{page.type}</span>
        </div>
      </div>
      {page.summary && <p className="text-[12px] text-text-2 mb-4">{page.summary}</p>}
      {modeReason && (
        <p className="text-[11px] text-text-3 mb-4">{modeReason}</p>
      )}
      <div className="prose-wiki text-[13px] leading-6">
        {renderMarkdown(page.body, paths, onNavigate)}
      </div>
      {page.frontmatter.sources && (
        <div className="mt-6 pt-4 border-t border-border">
          <div className="text-[11px] uppercase font-semibold text-text-3 mb-2">Sources</div>
          <div className="flex flex-wrap gap-2">
            {extractSourceLinks(page.frontmatter.sources).map((s) => (
              <button
                key={s}
                onClick={() => paths.has(s) && onNavigate(s)}
                className={cn(
                  "text-[11px] px-2 py-0.5 rounded border",
                  paths.has(s)
                    ? "border-accent/40 text-accent hover:bg-accent/10"
                    : "border-border text-text-3 opacity-60 cursor-default"
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
    </article>
  )
}

function extractSourceLinks(raw: string): string[] {
  const out: string[] = []
  const re = /\[\[([^\]]+)\]\]/g
  let m
  while ((m = re.exec(raw)) !== null) out.push(m[1])
  return out
}

function renderMarkdown(
  body: string,
  paths: Set<string>,
  onNavigate: (p: string) => void,
) {
  const lines = body.split("\n")
  const out: React.ReactNode[] = []
  let inList = false
  let listItems: React.ReactNode[] = []
  const flushList = (key: string) => {
    if (inList) {
      out.push(<ul key={key} className="list-disc ml-5 my-2 space-y-1">{listItems}</ul>)
      inList = false
      listItems = []
    }
  }

  lines.forEach((line, i) => {
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    if (h) {
      flushList(`l${i}`)
      const level = h[1].length
      const text = h[2]
      const cls =
        level === 1 ? "text-[15px] font-semibold mt-4 mb-2"
        : level === 2 ? "text-[14px] font-semibold mt-3 mb-1"
        : "text-[13px] font-semibold mt-2 mb-1 text-text-2"
      out.push(<div key={`h${i}`} className={cls}>{renderInline(text, paths, onNavigate)}</div>)
      return
    }
    const li = line.match(/^\s*[-*]\s+(.*)$/)
    if (li) {
      inList = true
      listItems.push(<li key={`li${i}`}>{renderInline(li[1], paths, onNavigate)}</li>)
      return
    }
    if (!line.trim()) {
      flushList(`l${i}`)
      return
    }
    flushList(`l${i}`)
    out.push(<p key={`p${i}`} className="my-2">{renderInline(line, paths, onNavigate)}</p>)
  })
  flushList("end")
  return out
}

function renderInline(
  text: string,
  paths: Set<string>,
  onNavigate: (p: string) => void,
): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  const re = /\[\[([^\]]+)\]\]|\*\*([^*]+)\*\*|`([^`]+)`/g
  let last = 0
  let m
  let idx = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    if (m[1]) {
      const target = m[1]
      const exists = paths.has(target)
      parts.push(
        <button
          key={`k${idx++}`}
          onClick={() => exists && onNavigate(target)}
          className={cn(
            "font-mono text-[12px] px-1 rounded transition-colors",
            exists
              ? "text-accent hover:bg-accent/10 cursor-pointer"
              : "text-text-3 opacity-60 cursor-default"
          )}
        >
          {target}
        </button>
      )
    } else if (m[2]) {
      parts.push(<strong key={`k${idx++}`}>{m[2]}</strong>)
    } else if (m[3]) {
      parts.push(
        <code key={`k${idx++}`} className="font-mono text-[12px] bg-surface-3 px-1 rounded">
          {m[3]}
        </code>
      )
    }
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}
