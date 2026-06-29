import ReactECharts from 'echarts-for-react'
import type { HistoryData, TimelineItem } from '../../types'
import FigmaReportCard from './FigmaReportCard'

const TAB = 'patient-history'

const COLOR_MAP: Record<string, string> = {
  green: '#34c759',
  blue: '#0071e3',
  red: '#ff3b30',
}

function safeText(v: unknown): string {
  if (!v) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'object') {
    const obj = v as Record<string, unknown>
    if ('summary' in obj && typeof obj.summary === 'string') return obj.summary as string
    // 个人史格式：{smoking:{status,packYears}, alcohol:{status}}
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
    // details 数组 → 系统分类列表
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

function HistoryTextCard({ title, content, evidence }: { title: string; content: unknown; evidence: string }) {
  const text = safeText(content)
  if (!text) return null
  return (
    <FigmaReportCard title={title} icon="history" evidence={evidence} tab={TAB}>
      <div className="figma-card__text" style={{ whiteSpace: 'pre-wrap' }}>{text}</div>
    </FigmaReportCard>
  )
}

function normalizeTimeline(timeline: unknown): TimelineItem[] {
  if (!Array.isArray(timeline)) return []
  return timeline.map((item: unknown) => {
    if (typeof item !== 'object' || !item) return item as TimelineItem
    const raw = item as Record<string, unknown>
    return {
      date: String(raw.date || raw.time || ''),
      label: String(raw.label || raw.event || ''),
      content: String(raw.content || raw.detail || raw.event || ''),
      color: (raw.color as TimelineItem['color']) || 'blue',
      type: String(raw.type || raw.stage || ''),
    }
  })
}

function TimelineView({ timeline }: { timeline: TimelineItem[] }) {
  if (!timeline.length) return null
  return (
    <div className="report-timeline">
      {timeline.map((item, i) => (
        <div className="report-timeline__item" key={`${item.date}-${item.label}`}>
          <div className="report-timeline__axis">
            <div className="report-timeline__dot" style={{ background: COLOR_MAP[item.color] || '#8e8e93' }} />
            {i < timeline.length - 1 && (
              <div className="report-timeline__line" />
            )}
          </div>
          <div className="report-timeline__content">
            <div className="report-timeline__title">
              {item.date} · {item.label}
            </div>
            <div className="report-timeline__text">
              {item.content}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function TumorSizeChart({ data }: { data: { labels: string[]; values: number[] } }) {
  if (!data?.labels?.length || !data?.values?.length) {
    return <div className="figma-card__text report-muted-block">暂无肿瘤测量数据（术后或资料未提供）</div>
  }
  if (data.labels.length !== data.values.length) {
    return <div className="figma-card__text report-muted-block">图表数据异常（横纵轴长度不匹配）</div>
  }
  const option = {
    tooltip: { trigger: 'axis' as const },
    grid: { left: 40, right: 16, top: 16, bottom: 28 },
    xAxis: { type: 'category' as const, data: data.labels, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value' as const, name: '毫米', axisLabel: { fontSize: 11 } },
    series: [{
      type: 'line' as const,
      data: data.values,
      smooth: true,
      symbolSize: 6,
      itemStyle: { color: '#0071e3' },
    }],
  }
  return <ReactECharts option={option} className="report-chart" />
}

export default function TabHistory({ data }: { data?: HistoryData }) {
  if (!data) return <div className="empty-state">等待病史分析...</div>

  return (
    <div className="report-tab-content history-tab-content">
      <FigmaReportCard title="患者病史核心原始数据" icon="history" evidence="证据来源：门诊病历 + 住院病历 + 检查报告" tab={TAB}>
        <div className="report-stat-value">问诊次数：{typeof data.visit_count === 'number' ? data.visit_count : (typeof data.visit_count === 'object' ? safeText(data.visit_count) : data.visit_count || '未知')} 次</div>
      </FigmaReportCard>
      <FigmaReportCard title="现病史时间线" icon="history" evidence="证据来源：病程记录 + 影像报告 + 治疗记录" tab={TAB}>
        <TimelineView timeline={normalizeTimeline(data.present_illness?.timeline)} />
      </FigmaReportCard>
      {data.present_illness?.tumor_size_chart && (
        <FigmaReportCard title="肿瘤大小趋势" icon="chart" evidence="证据来源：影像测量记录" tab={TAB}>
          <TumorSizeChart data={data.present_illness.tumor_size_chart} />
        </FigmaReportCard>
      )}
      <HistoryTextCard title="既往史" content={data.past_history} evidence="证据来源：既往病史记录" />
      <HistoryTextCard title="过敏史" content={data.allergy_history} evidence="证据来源：过敏史记录" />
      <HistoryTextCard title="个人史" content={data.personal_history} evidence="证据来源：个人史采集记录" />
      <HistoryTextCard title="家族史" content={data.family_history} evidence="证据来源：家族史采集记录" />
    </div>
  )
}
