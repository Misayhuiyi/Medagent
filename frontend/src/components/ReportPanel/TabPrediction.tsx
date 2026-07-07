import ReactECharts from 'echarts-for-react'
import type { PredictionData, AdversePrediction } from '../../types'
import FigmaReportCard from './FigmaReportCard'
import ClinicalText from './ClinicalText'
import { formatClinicalValue } from './textFormat'
import {
  type MultiSeriesChart,
  describeMultiSeries,
  normalizeMultiSeriesChart,
  normalizePairedSeries,
  parseClinicalNumber,
  sortLabelsWithValues,
} from './chartData'

const TAB = 'efficacy-prediction'

function TextCard({ title, content, evidence }: { title: string; content: unknown; evidence: string }) {
  const text = formatClinicalValue(content)
  if (!text) return null
  return (
    <FigmaReportCard title={title} icon="prediction" tab={TAB} evidence={evidence}>
      <ClinicalText text={text} />
    </FigmaReportCard>
  )
}

function PredictionChart({ data, yName = '毫米' }: { data: MultiSeriesChart; yName?: string }) {
  const labels = Array.isArray(data?.labels) ? data.labels : []
  const series = Array.isArray(data?.series) ? data.series : []
  if (!labels.length || !series.length) return null
  const validSeries = series.filter(s => Array.isArray(s.values) && s.values.length === labels.length && s.values.some((value) => value !== null))
  if (!validSeries.length) return null
  const option = {
    tooltip: {
      trigger: 'axis' as const,
      valueFormatter: (value: unknown) => (typeof value === 'number' ? `${value}${yName === '毫米' ? ' mm' : ''}` : '-'),
    },
    legend: { top: 0 },
    grid: { left: 40, right: 16, top: 30, bottom: 28 },
    xAxis: { type: 'category' as const, data: labels, axisLabel: { fontSize: 11, rotate: labels.length > 5 ? 20 : 0 } },
    yAxis: { type: 'value' as const, name: yName, axisLabel: { fontSize: 11 } },
    series: validSeries.map((s) => ({
      name: s.name,
      type: 'line' as const,
      data: s.values,
      smooth: true,
      connectNulls: false,
      symbolSize: 6,
    })),
  }
  return (
    <>
      <div className="figma-card__text report-chart-summary">{describeMultiSeries({ labels, series: validSeries }, yName === '毫米' ? 'mm' : '')}</div>
      <ReactECharts option={option} className="report-chart report-chart--large" />
    </>
  )
}

function AdverseChart({ pred }: { pred: AdversePrediction }) {
  const rawLabels = Array.isArray(pred.labels) ? pred.labels.map(String) : []
  const sorted = sortLabelsWithValues(rawLabels, rawLabels.map((_, index) => index))
  const labels = sorted.labels
  const grade1 = labels.map((_, index) => parseClinicalNumber(Array.isArray(pred.grade1) ? pred.grade1[sorted.values[index]] : null))
  const grade2 = labels.map((_, index) => parseClinicalNumber(Array.isArray(pred.grade2) ? pred.grade2[sorted.values[index]] : null))
  const grade3 = labels.map((_, index) => parseClinicalNumber(Array.isArray(pred.grade3) ? pred.grade3[sorted.values[index]] : null))
  if (!labels.length) return null
  const allValues = [...grade1, ...grade2, ...grade3].filter((value): value is number => value !== null)
  if (!allValues.length) return null
  const maxVal = Math.max(...allValues, 1)
  const yMax = maxVal > 1 ? Math.ceil(maxVal / 10) * 10 : 1
  const yName = maxVal > 1 ? '概率(%)' : '概率'
  const series = [
    {
      name: '1级', type: 'line' as const, data: grade1,
      smooth: true, connectNulls: false, areaStyle: { opacity: 0.2 }, itemStyle: { color: '#ff9500' },
    },
    {
      name: '2级', type: 'line' as const, data: grade2,
      smooth: true, connectNulls: false, areaStyle: { opacity: 0.2 }, itemStyle: { color: '#ff3b30' },
    },
  ]
  if (grade3.some((value) => value !== null)) {
    series.push({
      name: '3级', type: 'line' as const, data: grade3,
      smooth: true, connectNulls: false, areaStyle: { opacity: 0.18 }, itemStyle: { color: '#b42318' },
    })
  }
  const option = {
    tooltip: {
      trigger: 'axis' as const,
      valueFormatter: (value: unknown) => (typeof value === 'number' ? `${value}${maxVal > 1 ? '%' : ''}` : '-'),
    },
    legend: { top: 0, data: series.map((s) => s.name) },
    grid: { left: 50, right: 16, top: 30, bottom: 28 },
    xAxis: { type: 'category' as const, data: labels, axisLabel: { fontSize: 11, rotate: labels.length > 5 ? 20 : 0 } },
    yAxis: { type: 'value' as const, name: yName, min: 0, max: yMax, axisLabel: { fontSize: 11 } },
    series,
  }
  return (
    <>
      <div className="figma-card__text report-chart-summary">
        {describeMultiSeries({ labels, series: series.map((item) => ({ name: item.name, values: item.data })) }, maxVal > 1 ? '%' : '')}
      </div>
      <ReactECharts option={option} className="report-chart report-chart--large" />
    </>
  )
}

function SurvivalCurve({ data }: { data: MultiSeriesChart }) {
  const labels = Array.isArray(data?.labels) ? data.labels : []
  const series = Array.isArray(data?.series) ? data.series : []
  if (!labels.length || !series.length) return null
  const validSeries = series.filter(s => Array.isArray(s.values) && s.values.length === labels.length && s.values.some((value) => value !== null))
  if (!validSeries.length) return null
  const allValues = validSeries.flatMap((s) => s.values).filter((value): value is number => value !== null)
  const maxVal = Math.max(...allValues, 1)
  const yMax = maxVal > 1 ? Math.ceil(maxVal / 10) * 10 : 1
  const yName = maxVal > 1 ? '率(%)' : '概率'
  const option = {
    tooltip: {
      trigger: 'axis' as const,
      valueFormatter: (value: unknown) => (typeof value === 'number' ? `${value}${maxVal > 1 ? '%' : ''}` : '-'),
    },
    legend: { top: 0, data: validSeries.map((s) => s.name) },
    grid: { left: 60, right: 16, top: 30, bottom: 28 },
    xAxis: { type: 'category' as const, data: labels, axisLabel: { fontSize: 11, rotate: labels.length > 5 ? 20 : 0 } },
    yAxis: { type: 'value' as const, name: yName, min: 0, max: yMax, axisLabel: { fontSize: 11 } },
    series: validSeries.map((s, index) => ({
      name: s.name,
      type: 'line' as const,
      data: s.values,
      smooth: true,
      connectNulls: false,
      itemStyle: { color: index === 0 ? '#0071e3' : '#34c759' },
    })),
  }
  return (
    <>
      <div className="figma-card__text report-chart-summary">{describeMultiSeries({ labels, series: validSeries }, maxVal > 1 ? '%' : '')}</div>
      <ReactECharts option={option} className="report-chart report-chart--large" />
    </>
  )
}

export default function TabPrediction({ data }: { data?: PredictionData }) {
  if (!data) return <div className="empty-state">等待疗效预测分析...</div>
  const tumorPrediction = normalizeMultiSeriesChart(data.tumor_prediction, '肿瘤负荷')
  const prognosis = normalizePairedSeries(data.prognosis, 'pfs', 'os', '无进展生存', '总生存')

  return (
    <div className="report-tab-content prediction-tab-content">
      <TextCard title="自适应疗效预测摘要" content={data.adaptive_prediction_summary} evidence="证据来源：疗效趋势 + 当前治疗阶段" />
      <TextCard title="自适应监测计划" content={data.adaptive_monitoring_plan} evidence="证据来源：预测风险 + 随访策略" />
      {tumorPrediction && (
        <FigmaReportCard title="肿瘤趋势预测" icon="prediction" tab={TAB} evidence="证据来源：既往影像测量 + 疗效趋势模型">
          <PredictionChart data={tumorPrediction} />
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
      {prognosis && (
        <FigmaReportCard title="预后生存曲线" icon="chart" tab={TAB} evidence="证据来源：PFS/OS预测模型 + 治疗方案特征">
          <SurvivalCurve data={prognosis} />
        </FigmaReportCard>
      )}
      {data.disclaimer && (
        <FigmaReportCard title="预测说明" icon="file" tab={TAB} evidence="证据来源：模型限制说明" level="Ⅱ级">
          <div className="figma-card__text" style={{ whiteSpace: 'pre-wrap' }}>{formatClinicalValue(data.disclaimer)}</div>
        </FigmaReportCard>
      )}
    </div>
  )
}
