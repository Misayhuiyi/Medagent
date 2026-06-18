import ReactECharts from 'echarts-for-react'
import type { HistoryData, TimelineItem } from '../../types'
import FigmaReportCard from './FigmaReportCard'

const TAB = 'patient-history'

const COLOR_MAP: Record<string, string> = {
  green: '#34c759',
  blue: '#0071e3',
  red: '#ff3b30',
}

function HistoryTextCard({ title, content, evidence }: { title: string; content: string; evidence: string }) {
  if (!content) return null
  return (
    <FigmaReportCard title={title} icon="history" evidence={evidence} tab={TAB}>
      <div className="figma-card__text">{content}</div>
    </FigmaReportCard>
  )
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
        <div className="report-stat-value">问诊次数：{data.visit_count} 次</div>
      </FigmaReportCard>
      <FigmaReportCard title="现病史时间线" icon="history" evidence="证据来源：病程记录 + 影像报告 + 治疗记录" tab={TAB}>
        <TimelineView timeline={data.present_illness?.timeline || []} />
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
