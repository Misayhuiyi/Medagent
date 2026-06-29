import type { CareData } from '../../types'
import FigmaReportCard from './FigmaReportCard'

const TAB = 'suggestions'

function safeText(v: unknown): string {
  if (!v) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'object') {
    const obj = v as Record<string, unknown>
    if ('summary' in obj && typeof obj.summary === 'string') return obj.summary as string
    if ('smoking' in obj || 'alcohol' in obj) {
      const parts: string[] = []
      if (obj.smoking && typeof obj.smoking === 'object') {
        const s = obj.smoking as Record<string, unknown>
        parts.push(`吸烟：${s.status || ''}${s.packYears ? ' (' + s.packYears + '包年)' : ''}`)
      }
      if (obj.alcohol && typeof obj.alcohol === 'object') {
        const a = obj.alcohol as Record<string, unknown>
        parts.push(`饮酒：${a.status || ''}`)
      }
      if (obj.occupationalExposure && Array.isArray(obj.occupationalExposure)) {
        const items = obj.occupationalExposure.map((e: unknown) => {
          if (typeof e === 'object' && e) {
            const ee = e as Record<string, string>
            return `${ee.exposure || ''}（${ee.detail || ''}）`
          }
          return String(e)
        })
        if (items.length) parts.push(`职业暴露：${items.join('；')}`)
      }
      return parts.filter(Boolean).join('\n')
    }
    if ('details' in obj && Array.isArray(obj.details)) {
      return obj.details.map((d: unknown) => {
        if (typeof d === 'object' && d) {
          const dd = d as Record<string, string>
          return `${dd.system || ''}：${dd.disease || ''}${dd.notes ? '（' + dd.notes + '）' : ''}`
        }
        return String(d)
      }).filter(Boolean).join('\n')
    }
    return JSON.stringify(v, null, 2)
  }
  return String(v)
}

function CareCard({ title, content, evidence }: { title: string; content: unknown; evidence: string }) {
  const text = safeText(content)
  if (!text) return null
  return (
    <FigmaReportCard title={title} icon="file" evidence={evidence} tab={TAB}>
      <div className="figma-card__text" style={{ whiteSpace: 'pre-wrap' }}>{text}</div>
    </FigmaReportCard>
  )
}

export default function TabCare({ data }: { data?: CareData }) {
  if (!data) return <div className="empty-state">等待人文关怀分析...</div>

  return (
    <div className="report-tab-content">
      <CareCard title="心理关怀" content={data.psychological_care} evidence="证据来源：心理评估指南 + 患者主诉" />
      <CareCard title="保健措施" content={data.health_measures} evidence="证据来源：健康管理指南 + 患者病历" />
      <CareCard title="中医药建议" content={data.tcm_suggestions} evidence="证据来源：中西医结合指南" />
      <CareCard title="护理建议" content={data.nursing_care} evidence="证据来源：护理指南 + 患者评估" />
    </div>
  )
}
