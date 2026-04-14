import { LayoutDashboard, Bot, Database, Activity, ScrollText, BookOpen } from "lucide-react"
import { cn } from "../lib/cn.ts"

const NAV = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "fleet", label: "Fleet", icon: Bot },
  { id: "memory", label: "Memory", icon: Database },
  { id: "activity", label: "Activity", icon: Activity },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "icarus", label: "Icarus", icon: BookOpen },
] as const

export type Page = (typeof NAV)[number]["id"]

export function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (p: Page) => void }) {
  return (
    <aside className="w-[240px] shrink-0 bg-surface border-r border-border flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 h-12">
        <div className="w-6 h-6 rounded bg-accent/10 flex items-center justify-center">
          <Bot size={14} strokeWidth={1.5} className="text-accent" />
        </div>
        <span className="text-[14px] font-semibold">fabric</span>
      </div>
      <nav className="flex-1 px-2 py-1 flex flex-col gap-0.5">
        {NAV.map((item) => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={cn(
              "w-full flex items-center gap-2 h-8 px-2 text-[12px] border-l-2 transition-colors",
              page === item.id
                ? "border-l-accent bg-surface-3 text-text font-medium"
                : "border-l-transparent text-text-2 hover:bg-surface-3"
            )}
          >
            <item.icon size={16} strokeWidth={1.5} />
            {item.label}
          </button>
        ))}
      </nav>
      <div className="px-3 py-3 border-t border-border">
        <span className="text-[11px] text-text-3 font-mono">v2.0.0</span>
      </div>
    </aside>
  )
}
