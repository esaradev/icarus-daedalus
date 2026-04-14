import { useState, useEffect } from "react"
import type { DashboardData, Telemetry, WikiData } from "./types.ts"

function defaultTelemetry(): Telemetry {
  return {
    health: {
      healthyAgents: 0,
      staleAgents: 0,
      idleAgents: 0,
      offlineAgents: 0,
      silentAgents: 0,
    },
    memory: {
      hotRate: 0,
      coldRate: 0,
      unscopedEntries: 0,
      projectCoverage: 0,
      sessionCoverage: 0,
    },
    coordination: {
      multiPlatformAgents: 0,
      avgPlatformsPerAgent: 0,
      avgEntriesPerAgent: 0,
      avgEntriesPerProject: 0,
      avgEntriesPerSession: 0,
    },
    platformStates: {},
    leaders: {
      byEntries: [],
      byToday: [],
      byProjects: [],
    },
    projects: [],
  }
}

function normalizeData(input: DashboardData): DashboardData {
  const telemetry = input.telemetry ?? defaultTelemetry()
  return {
    ...input,
    agents: input.agents ?? [],
    entries: input.entries ?? [],
    platDist: input.platDist ?? {},
    typeDist: input.typeDist ?? {},
    timeline: input.timeline ?? {},
    telemetry: {
      ...defaultTelemetry(),
      ...telemetry,
      health: { ...defaultTelemetry().health, ...telemetry.health },
      memory: { ...defaultTelemetry().memory, ...telemetry.memory },
      coordination: { ...defaultTelemetry().coordination, ...telemetry.coordination },
      leaders: { ...defaultTelemetry().leaders, ...telemetry.leaders },
      platformStates: telemetry.platformStates ?? {},
      projects: telemetry.projects ?? [],
    },
  }
}

export function useData(interval = 5000) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    const load = () =>
      fetch("/api/data")
        .then((r) => r.json())
        .then((d: DashboardData) => { if (active) { setData(normalizeData(d)); setError(false) } })
        .catch(() => { if (active) setError(true) })
    load()
    const id = setInterval(load, interval)
    return () => { active = false; clearInterval(id) }
  }, [interval])

  return { data, error }
}

export function useWiki(interval = 10000) {
  const [data, setData] = useState<WikiData | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    const load = () =>
      fetch("/api/wiki/pages")
        .then((r) => r.json())
        .then((d: WikiData) => { if (active) { setData(d); setError(false) } })
        .catch(() => { if (active) setError(true) })
    load()
    const id = setInterval(load, interval)
    return () => { active = false; clearInterval(id) }
  }, [interval])

  return { data, error }
}
