import ReactECharts from 'echarts-for-react'
import type { HistoryData, TimelineItem } from '../../types'
import FigmaReportCard from './FigmaReportCard'
import { formatClinicalValue } from './textFormat'

const TAB = 'patient-history'

const COLOR_MAP: Record<string, string> = {
  green: '#34c759',
  blue: '#0071e3',
  red: '#ff3b30',
}

function safeText(v: unknown): string {
  return formatClinicalValue(v)
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

function normalizeTumorSizeChart(raw: unknown): { labels: string[]; values: number[] } | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, unknown>
  const labels = Array.isArray(data.labels) ? data.labels.map(String) :
    Array.isArray(data.dates) ? data.dates.map(String) :
    Array.isArray(data.xAxis) ? data.xAxis.map(String) : []
  const valuesRaw = Array.isArray(data.values) ? data.values :
    Array.isArray(data.sizes) ? data.sizes :
    Array.isArray(data.yAxis) ? data.yAxis : []
  const values = valuesRaw.map((v) => Number(v)).filter((v) => Number.isFinite(v))
  if (labels.length && values.length === labels.length) return { labels, values }

  const points = Array.isArray(data.points) ? data.points : Array.isArray(data.data) ? data.data : []
  if (Array.isArray(points) && points.length) {
    const pointLabels: string[] = []
    const pointValues: number[] = []
    points.forEach((item) => {
      if (!item || typeof item !== 'object') return
      const p = item as Record<string, unknown>
      const label = String(p.date || p.time || p.label || '')
      const value = Number(p.value ?? p.size ?? p.diameter ?? p.long_diameter)
      if (label && Number.isFinite(value)) {
        pointLabels.push(label)
        pointValues.push(value)
      }
    })
    if (pointLabels.length && pointLabels.length === pointValues.length) {
      return { labels: pointLabels, values: pointValues }
    }
  }
  return null
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
  const presentIllness = data.present_illness as unknown as Record<string, unknown> | undefined
  const timeline = normalizeTimeline(presentIllness?.timeline || (data as unknown as Record<string, unknown>).timeline)
  const tumorChart = normalizeTumorSizeChart(
    presentIllness?.tumor_size_chart ||
    presentIllness?.tumorSizeChart ||
    (data as unknown as Record<string, unknown>).tumor_size_chart ||
    (data as unknown as Record<string, unknown>).tumorSizeChart,
  )

  return (
    <div className="report-tab-content history-tab-content">
      <FigmaReportCard title="患者病史核心原始数据" icon="history" evidence="证据来源：门诊病历 + 住院病历 + 检查报告" tab={TAB}>
        <div className="report-stat-value">问诊次数：{typeof data.visit_count === 'number' ? data.visit_count : (typeof data.visit_count === 'object' ? safeText(data.visit_count) : data.visit_count || '未知')} 次</div>
      </FigmaReportCard>
      <FigmaReportCard title="现病史时间线" icon="history" evidence="证据来源：病程记录 + 影像报告 + 治疗记录" tab={TAB}>
        <TimelineView timeline={timeline} />
      </FigmaReportCard>
      {tumorChart && (
        <FigmaReportCard title="肿瘤大小趋势" icon="chart" evidence="证据来源：影像测量记录" tab={TAB}>
          <TumorSizeChart data={tumorChart} />
        </FigmaReportCard>
      )}
      <HistoryTextCard title="既往史" content={data.past_history} evidence="证据来源：既往病史记录" />
      <HistoryTextCard title="过敏史" content={data.allergy_history} evidence="证据来源：过敏史记录" />
      <HistoryTextCard title="个人史" content={data.personal_history} evidence="证据来源：个人史采集记录" />
      <HistoryTextCard title="家族史" content={data.family_history} evidence="证据来源：家族史采集记录" />
    </div>
  )
}
