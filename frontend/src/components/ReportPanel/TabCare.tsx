import type { CareData } from '../../types'
import FigmaReportCard from './FigmaReportCard'
import { formatClinicalValue } from './textFormat'
import ClinicalText from './ClinicalText'

const TAB = 'suggestions'

function safeText(v: unknown): string {
  return formatClinicalValue(v)
}

function CareCard({ title, content, evidence }: { title: string; content: unknown; evidence: string }) {
  const text = safeText(content)
  if (!text) return null
  return (
    <FigmaReportCard title={title} icon="file" evidence={evidence} tab={TAB}>
      <ClinicalText text={text} />
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
