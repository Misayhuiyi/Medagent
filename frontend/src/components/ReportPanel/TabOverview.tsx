import type { ReactNode } from 'react'
import type { OverviewData, LesionItem } from '../../types'
import FigmaReportCard from './FigmaReportCard'

const TAB = 'patient-overview'

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

function OverviewTextCard({ title, content, evidence }: { title: string; content: unknown; evidence: string }) {
  const text = safeText(content)
  if (!text) return null
  return (
    <FigmaReportCard title={title} icon="overview" evidence={evidence} tab={TAB}>
      <div className="figma-card__text" style={{ whiteSpace: 'pre-wrap' }}>{text}</div>
    </FigmaReportCard>
  )
}

function AssessmentCard({
  colorKey, title, children,
}: {
  colorKey: string; title: string; children: ReactNode
}) {
  const tone = colorKey.replace(/_/g, '-')
  return (
    <FigmaReportCard
      title={title}
      icon="overview"
      evidence="证据来源：影像报告 + 实验室检查 + AI 结构化评估"
      className={`assessment-card assessment-card--${tone}`}
      tab={TAB}
    >
      {children}
    </FigmaReportCard>
  )
}

function LesionTable({ lesions }: { lesions: LesionItem[] }) {
  if (!lesions?.length) return null
  return (
    <table className="lesion-table">
      <thead>
        <tr>
          <th>编号</th>
          <th>位置</th>
          <th className="is-numeric">基线</th>
          <th className="is-numeric">当前</th>
          <th className="is-numeric">变化</th>
        </tr>
      </thead>
      <tbody>
        {lesions.map((l) => (
          <tr key={l.id}>
            <td className="lesion-table__id">{l.id}</td>
            <td>{l.location}</td>
            <td className="is-numeric">{l.baseline}mm</td>
            <td className="is-numeric">{l.current}mm</td>
            <td className={`is-numeric ${l.change.startsWith('-') ? 'is-improved' : l.change.startsWith('+') ? 'is-worse' : 'is-stable'}`}>
              {l.change}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function EfficacyRow({ label, data }: { label: string; data?: { response?: string; change?: string } }) {
  if (!data) return null
  return (
    <div className="efficacy-row">
      <span>{label}</span>
      <span>
        <strong>{data.response || '未评估'}</strong>{data.change ? ` (${data.change})` : ''}
      </span>
    </div>
  )
}

export default function TabOverview({ data }: { data?: OverviewData }) {
  if (!data) return <div className="empty-state">等待概况分析...</div>

  return (
    <div className="report-tab-content overview-tab-content">
      <OverviewTextCard title="主诉" content={data.chief_complaint} evidence="证据来源：门诊病历 + 当前问诊" />
      <OverviewTextCard title="体格检查" content={data.physical_examination} evidence="证据来源：体格检查记录" />
      {data.auxiliary_examination && (
        <FigmaReportCard title="辅助检查" icon="overview" evidence="证据来源：影像报告 + 检验报告" tab={TAB}>
          {data.auxiliary_examination.imaging && (
            <div className="figma-card__text report-text--subitem">
              <strong>影像：</strong>{safeText(data.auxiliary_examination.imaging)}
            </div>
          )}
          {data.auxiliary_examination.lab_tests && (
            <div className="figma-card__text">
              <strong>检验：</strong>{safeText(data.auxiliary_examination.lab_tests)}
            </div>
          )}
        </FigmaReportCard>
      )}

      {data.ai_tumor_burden && (
        <AssessmentCard colorKey="tumor_burden" title={`AI 肿瘤负荷 — ${data.ai_tumor_burden.clinical_stage}`}>
          <div className="assessment-card__meta">
            TNM: {data.ai_tumor_burden.t_stage}{data.ai_tumor_burden.n_stage}{data.ai_tumor_burden.m_stage}
          </div>
          <div className="figma-card__text report-text--compact">{data.ai_tumor_burden.conclusion}</div>
          <LesionTable lesions={data.ai_tumor_burden.lesions || []} />
        </AssessmentCard>
      )}

      {data.ai_efficacy && (
        <AssessmentCard colorKey="efficacy" title="AI 疗效评估">
          <EfficacyRow label="vs 基线" data={data.ai_efficacy.vs_baseline} />
          <EfficacyRow label="vs 上次" data={data.ai_efficacy.vs_previous} />
          <EfficacyRow label="最佳疗效" data={data.ai_efficacy.best_response} />
        </AssessmentCard>
      )}

      {data.ai_adverse_events && (
        <AssessmentCard colorKey="adverse" title="AI 不良反应评估">
          {['symptoms', 'signs', 'imaging', 'lab_tests'].map((key) => {
            const val = data.ai_adverse_events[key as 'symptoms' | 'signs' | 'imaging' | 'lab_tests']
            if (!val) return null
            const labels: Record<string, string> = { symptoms: '症状', signs: '体征', imaging: '影像', lab_tests: '检验' }
            return <div key={key} className="figma-card__text"><strong>{labels[key]}：</strong>{safeText(val)}</div>
          })}
          {data.ai_adverse_events.conclusion && (
            <div className="figma-card__text report-text--emphasis">
              {safeText(data.ai_adverse_events.conclusion)}
            </div>
          )}
        </AssessmentCard>
      )}

      <OverviewTextCard title="合并症" content={data.ai_comorbidity} evidence="证据来源：既往史 + 当前病历" />

      {data.ecog_score && (
        <AssessmentCard colorKey="other" title={`ECOG 评分 — ${data.ecog_score.score} 分`}>
          <div className="figma-card__text">{safeText(data.ecog_score.description)}</div>
        </AssessmentCard>
      )}

      {data.diagnosis && (
        <FigmaReportCard title="诊断总结" icon="overview" evidence="证据来源：综合诊断 + 病理/基因/影像资料" tab={TAB}>
          {data.diagnosis.tumor || data.diagnosis.adverse_events || data.diagnosis.comorbidity ? (
            <div className="figma-card__text">
              {data.diagnosis.tumor && <div><strong>肿瘤：</strong>{safeText(data.diagnosis.tumor)}</div>}
              {data.diagnosis.adverse_events && <div><strong>不良反应：</strong>{safeText(data.diagnosis.adverse_events)}</div>}
              {data.diagnosis.comorbidity && <div><strong>合并症：</strong>{safeText(data.diagnosis.comorbidity)}</div>}
            </div>
          ) : (
            <div className="figma-card__text" style={{ whiteSpace: 'pre-wrap' }}>{safeText(data.diagnosis)}</div>
          )}
        </FigmaReportCard>
      )}
    </div>
  )
}
