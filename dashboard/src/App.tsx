import { useState } from "react"
import { Sidebar } from "./components/sidebar.tsx"
import type { Page } from "./components/sidebar.tsx"
import { useData } from "./lib/api.ts"
import { Overview } from "./pages/overview.tsx"
import { Fleet } from "./pages/fleet.tsx"
import { Memory } from "./pages/memory.tsx"
import { ActivityPage } from "./pages/activity.tsx"
import { Logs } from "./pages/logs.tsx"
import { Icarus } from "./pages/icarus.tsx"

const PAGE_LABELS: Record<string, string> = {
  overview: "Overview",
  fleet: "Fleet",
  memory: "Memory",
  activity: "Activity",
  logs: "Logs",
  icarus: "Icarus — Persistent Knowledge",
}

function App() {
  const [page, setPage] = useState<Page>("overview")
  const { data, error } = useData()

  return (
    <>
      <Sidebar page={page} onNavigate={setPage} />
      <main className="flex-1 overflow-y-auto">
        <div className="p-6">
          <header className="flex items-center justify-between mb-6">
            <h1 className="text-[18px] font-semibold">{PAGE_LABELS[page]}</h1>
            {data && (
              <div className="flex items-center gap-3">
                <span className="inline-flex items-center h-5 px-1.5 text-[11px] rounded bg-success/15 text-success tabular-nums">
                  {data.stats.activeAgents} live
                </span>
                <span className="text-[11px] text-text-3 tabular-nums">
                  {data.stats.totalAgents} agents / {data.stats.totalEntries} entries
                </span>
              </div>
            )}
          </header>
          {error && !data && (
            <p className="text-[13px] text-text-3">
              Cannot reach API. Run <code className="font-mono text-text-2">npm run server</code>
            </p>
          )}
          {!data && !error && <p className="text-[11px] text-text-3">Loading&hellip;</p>}
          {data && page === "overview" && <Overview data={data} onNavigate={setPage} />}
          {data && page === "fleet" && <Fleet data={data} />}
          {data && page === "memory" && <Memory data={data} />}
          {data && page === "activity" && <ActivityPage data={data} />}
          {data && page === "logs" && <Logs data={data} />}
          {page === "icarus" && <Icarus />}
        </div>
      </main>
    </>
  )
}

export default App
