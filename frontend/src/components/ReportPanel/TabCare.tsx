import type { CareData } from '../../types'
import FigmaReportCard from './FigmaReportCard'

const TAB = 'suggestions'

export default function TabCare({ data }: { data?: CareData }) {
  if (!data) return <div className="empty-state">等待人文关怀分析...</div>

  return (
    <div className="report-tab-content">
      <FigmaReportCard
        title="心理关怀"
        icon="care"
        evidence="证据来源：心理评估指南 + 患者主诉"
        tab={TAB}
      >
        <div className="figma-card__text">{data.psychological_care}</div>
      </FigmaReportCard>
      <FigmaReportCard
        title="保健措施"
        icon="file"
        evidence="证据来源：健康管理指南 + 患者病历"
        tab={TAB}
      >
        <div className="figma-card__text">{data.health_measures}</div>
      </FigmaReportCard>
      <FigmaReportCard
        title="中医药建议"
        icon="file"
        evidence="证据来源：中西医结合指南"
        tab={TAB}
      >
        <div className="figma-card__text">{data.tcm_suggestions}</div>
      </FigmaReportCard>
      <FigmaReportCard
        title="护理建议"
        icon="file"
        evidence="证据来源：护理指南 + 患者评估"
        tab={TAB}
      >
        <div className="figma-card__text">{data.nursing_care}</div>
      </FigmaReportCard>
    </div>
  )
}
