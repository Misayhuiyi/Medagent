import axios from 'axios'
import type {
  Patient,
  PatientFile,
  FileContent,
  ChatMessage,
  SSEEvent,
  ReportData,
} from '../types'

// ── Axios 实例 ──

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// ── SSE 解析器 ──

export function parseSSE(buffer: string): { remaining: string; events: SSEEvent[] } {
  const events: SSEEvent[] = []
  const blocks = buffer.split('\n\n')
  const remaining = blocks.pop()!

  for (const block of blocks) {
    if (!block.trim()) continue
    let type: SSEEvent['type'] | undefined
    let id: number | undefined
    let data: unknown
    for (const line of block.split('\n')) {
      if (line.startsWith('id:')) id = parseInt(line.slice(3).trim())
      else if (line.startsWith('event:')) type = line.slice(6).trim() as SSEEvent['type']
      else if (line.startsWith('data:')) {
        try { data = JSON.parse(line.slice(5).trim()) } catch { /* skip malformed */ }
      }
    }
    if (type && data !== undefined) {
      events.push({ id, type, data } as SSEEvent)
    }
  }

  return { remaining, events }
}

// ── 患者 API ──

export async function fetchPatients(): Promise<Patient[]> {
  const res = await api.get<Patient[]>('/patients')
  return res.data
}

export async function fetchPatientFiles(patientId: string): Promise<PatientFile[]> {
  const res = await api.get<PatientFile[]>(`/patients/${encodeURIComponent(patientId)}/files`)
  return res.data
}

export async function fetchFileContent(patientId: string, filename: string): Promise<FileContent> {
  const res = await api.get<FileContent>(`/patients/${encodeURIComponent(patientId)}/files/${encodeURIComponent(filename)}`)
  return res.data
}

// ── 聊天 API ──

export async function fetchChatHistory(patientId: string): Promise<ChatMessage[]> {
  const res = await api.get<ChatMessage[]>(`/chat/${encodeURIComponent(patientId)}/history`)
  return res.data
}

// ── 报告 API ──

export async function fetchReport(patientId: string): Promise<ReportData> {
  const res = await api.get<ReportData>(`/reports/${encodeURIComponent(patientId)}`)
  return res.data
}

export async function saveReport(patientId: string, report: ReportData): Promise<void> {
  await api.post(`/reports/${encodeURIComponent(patientId)}`, report)
}

export function getDownloadUrl(patientId: string, format: 'md' | 'html' | 'pdf'): string {
  return `/api/reports/${encodeURIComponent(patientId)}/download?format=${format}`
}


