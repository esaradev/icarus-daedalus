export type Platform = {
  name: string
  state: string
  color: string
}

export type Agent = {
  name: string
  role: string
  online: boolean
  platforms: Platform[]
  cycles: number
  entries: number
  lastActive: string
  lastOutput: string
  status?: "healthy" | "stale" | "idle" | "offline"
  lastActiveMinutes?: number | null
  entriesToday?: number
  entries7d?: number
  projectCount?: number
  sessionCount?: number
}

export type Entry = {
  file: string
  agent: string
  platform: string
  type: string
  tier: string
  timestamp: string
  summary: string
  project_id: string
  session_id: string
  id: string
  body: string
}

export type Stats = {
  totalAgents: number
  activeAgents: number
  totalEntries: number
  entriesToday: number
  hot: number
  warm: number
  cold: number
  brainSize: number
  xRecalls: number
  uptime: number
}

export type DashboardData = {
  agents: Agent[]
  entries: Entry[]
  stats: Stats
  platDist: Record<string, number>
  typeDist: Record<string, number>
  timeline: Record<string, Record<string, number>>
  telemetry: Telemetry
}

export type Telemetry = {
  health: {
    healthyAgents: number
    staleAgents: number
    idleAgents: number
    offlineAgents: number
    silentAgents: number
  }
  memory: {
    hotRate: number
    coldRate: number
    unscopedEntries: number
    projectCoverage: number
    sessionCoverage: number
  }
  coordination: {
    multiPlatformAgents: number
    avgPlatformsPerAgent: number
    avgEntriesPerAgent: number
    avgEntriesPerProject: number
    avgEntriesPerSession: number
  }
  platformStates: Record<string, Record<string, number>>
  leaders: {
    byEntries: Array<{ name: string; value: number }>
    byToday: Array<{ name: string; value: number }>
    byProjects: Array<{ name: string; value: number }>
  }
  projects: Array<{ id: string; entries: number; agents: number; sessions: number }>
}

export type WikiPage = {
  path: string
  type: string
  title: string
  summary: string
  frontmatter: Record<string, string>
  body: string
  links: string[]
  updated: string
}

export type WikiData = {
  pages: WikiPage[]
  indexBody: string
  logBody: string
  homeBody: string
}
