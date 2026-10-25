import type { ResearchSession } from '@/types/research'
import { normaliseSynthesis } from './researchOverviewAdapter'
import type { ProgressSnapshot } from './eventAdapter'

const API_ROOT = '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, init)
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch { /* Keep the status based message. */ }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export async function createResearchSession(question: string, files: File[]) {
  const body = new FormData()
  body.append('question', question)
  files.forEach((file) => body.append('files', file))
  const result = await request<{ session_id: string }>('/sessions', { method: 'POST', body })
  return result.session_id
}

export interface SessionSnapshot {
  id: string
  status: 'running' | 'paused' | 'done' | 'failed' | 'aborted'
  research_goal: string
}

export function getSession(id: string) {
  return request<SessionSnapshot>(`/sessions/${encodeURIComponent(id)}`)
}

export function getProgressSnapshot(id: string) {
  return request<ProgressSnapshot>(`/sessions/${encodeURIComponent(id)}/progress`)
}

export function getResearch(id: string, includeDrafts = false) {
  return request<ResearchSession>(`/sessions/${encodeURIComponent(id)}/research${includeDrafts ? '?include_drafts=true' : ''}`)
}

export interface TimelineMessage {
  seq: number
  ts: number
  role: string
  agent: string | null
  kind: string
  title: string
  body_markdown: string
  refs: string[]
}

export function getTimeline(id: string) {
  return request<{ messages: TimelineMessage[] }>(`/sessions/${encodeURIComponent(id)}/timeline`)
}

export function getSynthesis(id: string) {
  return request<unknown>(`/sessions/${encodeURIComponent(id)}/synthesis`)
}

export interface AnalysisReport {
  sample_count?: number
  generated_at?: string
  summary_markdown?: string
  candidates?: Array<{ candidate_key?: string; biomarker?: string; alteration_type?: string; drug?: string; p_value?: number }>
  plots?: Array<{ name: string; content_type: string; url: string }>
}

export interface AttachmentRecord {
  id: string
  filename: string
  kind: 'tabular' | 'document'
  size: number
  status: 'stored' | 'ingested' | 'analysed' | 'failed'
}

export function getAnalysis(id: string) {
  return request<AnalysisReport>(`/sessions/${encodeURIComponent(id)}/analysis`)
}

export function getAttachments(id: string) {
  return request<{ attachments: AttachmentRecord[] }>(`/sessions/${encodeURIComponent(id)}/attachments`)
}

export { normaliseSynthesis }

export function sessionAction(id: string, action: 'pause' | 'resume' | 'abort') {
  return request<{ ok: boolean }>(`/sessions/${encodeURIComponent(id)}/${action}`, { method: 'POST' })
}
