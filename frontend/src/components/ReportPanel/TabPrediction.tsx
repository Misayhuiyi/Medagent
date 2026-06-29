import ReactECharts from 'echarts-for-react'
import type { PredictionData, AdversePrediction } from '../../types'
import FigmaReportCard from './FigmaReportCard'

const TAB = 'efficacy-prediction'

function PredictionChart({ data }: { data: { labels: string[]; series: { name: string; values: number[] }[] } }) {
  const labels = Array.isArray(data?.labels) ? data.labels : []
  const series = Array.isArray(data?.series) ? data.series : []
  if (!labels.length || !series.length) return null
  const validSeries = series.filter(s => Array.isArray(s.values) && s.values.length === labels.length)
  if (!validSeries.length) return null
  const option = {
    tooltip: { trigger: 'axis' as const },
    legend: { top: 0 },
    grid: { left: 40, right: 16, top: 30, bottom: 28 },
    xAxis: { type: 'category' as const, data: labels, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value' as const, name: '毫米', axisLabel: { fontSize: 11 } },
    series: validSeries.map((s) => ({
      name: s.name,
      type: 'line' as const,
      data: s.values,
      smooth: true,
      symbolSize: 6,
    })),
  }
  return <ReactECharts option={option} className="report-chart report-chart--large" />
}

function AdverseChart({ pred }: { pred: AdversePrediction }) {
  const labels = Array.isArray(pred.labels) ? pred.labels : []
  const grade1 = Array.isArray(pred.grade1) ? pred.grade1 : []
  const grade2 = Array.isArray(pred.grade2) ? pred.grade2 : []
  const grade3 = Array.isArray(pred.grade3) ? pred.grade3 : []
  if (!labels.length) return null
  const allValues = [...grade1, ...grade2, ...grade3]
  const maxVal = Math.max(...allValues, 1)
  const yMax = maxVal > 1 ? Math.ceil(maxVal / 10) * 10 : 1
  const yName = maxVal > 1 ? '概率(%)' : '概率'
  const option = {
    tooltip: { trigger: 'axis' as const },
    legend: { top: 0, data: ['1级', '2级'] },
    grid: { left: 50, right: 16, top: 30, bottom: 28 },
    xAxis: { type: 'category' as const, data: labels, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value' as const, name: yName, min: 0, max: yMax, axisLabel: { fontSize: 11 } },
    series: [
      {
        name: '1级', type: 'line' as const, data: grade1,
        smooth: true, areaStyle: { opacity: 0.2 }, itemStyle: { color: '#ff9500' },
      },
      {
        name: '2级', type: 'line' as const, data: grade2,
        smooth: true, areaStyle: { opacity: 0.2 }, itemStyle: { color: '#ff3b30' },
      },
    ],
  }
  return <ReactECharts option={option} className="report-chart report-chart--large" />
}

function SurvivalCurve({ data }: { data: { labels: string[]; pfs: number[]; os: number[] } }) {
  const labels = Array.isArray(data?.labels) ? data.labels : []
  const pfs = Array.isArray(data?.pfs) ? data.pfs : []
  const os = Array.isArray(data?.os) ? data.os : []
  if (!labels.length) return null
  if (pfs.length !== labels.length || os.length !== labels.length) return null
  const allValues = [...pfs, ...os]
  const maxVal = Math.max(...allValues, 1)
  const yMax = maxVal > 1 ? Math.ceil(maxVal / 10) * 10 : 1
  const yName = maxVal > 1 ? '率(%)' : '概率'
  const option = {
    tooltip: { trigger: 'axis' as const },
    legend: { top: 0, data: ['无进展生存', '总生存'] },
    grid: { left: 60, right: 16, top: 30, bottom: 28 },
    xAxis: { type: 'category' as const, data: labels, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value' as const, name: yName, min: 0, max: yMax, axisLabel: { fontSize: 11 } },
    series: [
      { name: '无进展生存', type: 'line' as const, data: pfs, smooth: true, itemStyle: { color: '#0071e3' } },
      { name: '总生存', type: 'line' as const, data: os, smooth: true, itemStyle: { color: '#34c759' } },
    ],
  }
  return <ReactECharts option={option} className="report-chart report-chart--large" />
}

export default function TabPrediction({ data }: { data?: PredictionData }) {
  if (!data) return <div className="empty-state">等待疗效预测分析...</div>

  return (
    <div className="report-tab-content prediction-tab-content">
      {data.tumor_prediction && (
        <FigmaReportCard title="肿瘤趋势预测" icon="prediction" tab={TAB} evidence="证据来源：既往影像测量 + 疗效趋势模型">
          <PredictionChart data={data.tumor_prediction} />
        </FigmaReportCard>
      )}
      {data.adverse_prediction?.map((pred) => (
        <FigmaReportCard
          key={pred.name}
          title={`不良反应预测 — ${pred.name}`}
          icon="prediction"
          evidence="证据来源：CTCAE分级 + 既往不良反应记录"
        >
          <AdverseChart pred={pred} />
        </FigmaReportCard>
      ))}
      {data.prognosis && (
        <FigmaReportCard title="预后生存曲线" icon="chart" tab={TAB} evidence="证据来源：PFS/OS预测模型 + 治疗方案特征">
          <SurvivalCurve data={data.prognosis} />
        </FigmaReportCard>
      )}
      {data.disclaimer && (
        <FigmaReportCard title="预测说明" icon="file" tab={TAB} evidence="证据来源：模型限制说明" level="Ⅱ级">
          <div className="figma-card__text" style={{ whiteSpace: 'pre-wrap' }}>{typeof data.disclaimer === 'string' ? data.disclaimer : JSON.stringify(data.disclaimer, null, 2)}</div>
        </FigmaReportCard>
      )}
    </div>
  )
}
