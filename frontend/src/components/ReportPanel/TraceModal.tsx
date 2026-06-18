import { useEffect, useState } from 'react'
import { Modal, Spin } from 'antd'
import MarkdownRenderer from '../common/MarkdownRenderer'

interface TraceResult {
  source: string
  content: string
  page: string
  evidence_level: number
  year: string
}

interface Props {
  open: boolean
  question: string
  patientId: string
  tab?: string
  onClose: () => void
}

export default function TraceModal({ open, question, patientId, tab, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<TraceResult[]>([])

  useEffect(() => {
    if (!open || !question) return
    setLoading(true)
    fetch('/api/kb/trace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, top_k: 5, patient_id: patientId, tab: tab || '' }),
    })
      .then((r) => r.json())
      .then((data) => setResults(data.results || []))
      .catch(() => setResults([]))
      .finally(() => setLoading(false))
  }, [open, question])

  const levelLabel = (lv: number) => {
    if (lv >= 7) return 'Ⅰ级'
    if (lv >= 5) return 'Ⅱ级'
    if (lv >= 3) return 'Ⅲ级'
    return 'Ⅳ级'
  }

  return (
    <Modal
      title="证据溯源"
      open={open}
      onCancel={onClose}
      footer={null}
      width={680}
      styles={{ body: { maxHeight: '60vh', overflowY: 'auto', padding: '12px 16px' } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
      ) : results.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 32, color: '#a6a6a6' }}>未找到相关证据</div>
      ) : (
        results.map((r, i) => (
          <div key={i} style={{
            marginBottom: 12, padding: 10,
            border: '1px solid #e5e5e5', borderRadius: 8,
            background: '#fff',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontWeight: 600, fontSize: 13, color: '#007aff' }}>
                {r.source} {r.year}
              </span>
              <span style={{
                fontSize: 11, padding: '1px 6px', borderRadius: 4,
                background: '#e6f4ff', color: '#007aff',
              }}>
                {levelLabel(r.evidence_level)} · {r.page ? `第${r.page}页` : ''}
              </span>
            </div>
            <div style={{ fontSize: 12, lineHeight: 1.6, color: '#383838' }}>
              <MarkdownRenderer content={r.content} />
            </div>
          </div>
        ))
      )}
    </Modal>
  )
}