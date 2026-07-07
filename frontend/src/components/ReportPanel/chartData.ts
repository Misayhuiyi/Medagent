export type ChartSeries = { name: string; values: Array<number | null> }

export type MultiSeriesChart = {
  labels: string[]
  series: ChartSeries[]
}

function parseDateValue(label: string): number {
  const normalized = label
    .replace(/[年月.]/g, '-')
    .replace(/[日号]/g, '')
    .replace(/~.*$/, '')
    .trim()
  const timestamp = Date.parse(normalized)
  return Number.isFinite(timestamp) ? timestamp : Number.MAX_SAFE_INTEGER
}

export function sortLabelsWithValues<T>(labels: string[], values: T[]): { labels: string[]; values: T[] } {
  const rows = labels.map((label, index) => ({ label, value: values[index], index }))
  rows.sort((a, b) => {
    const dateDelta = parseDateValue(a.label) - parseDateValue(b.label)
    return dateDelta || a.index - b.index
  })
  return {
    labels: rows.map((row) => row.label),
    values: rows.map((row) => row.value),
  }
}

export function parseClinicalNumber(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === '') return null
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null
  const text = String(raw).trim()
  if (!text || /^(-|--|无|未见|未测|缺失|na|n\/a|null)$/i.test(text)) return null

  const numbers = [...text.matchAll(/-?\d+(?:\.\d+)?/g)].map((m) => Number(m[0])).filter(Number.isFinite)
  if (!numbers.length) return null
  let value = Math.max(...numbers.map(Math.abs))
  if (/cm|厘米/i.test(text) && !/mm|毫米/i.test(text)) value *= 10
  return value
}

function compactSeries(series: ChartSeries[], labels: string[]): ChartSeries[] {
  return series
    .map((item) => ({
      name: item.name || '预测',
      values: labels.map((_, index) => item.values[index] ?? null),
    }))
    .filter((item) => item.values.some((value) => value !== null))
}

export function normalizePointChart(raw: unknown): { labels: string[]; values: Array<number | null> } | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, unknown>
  const labels = Array.isArray(data.labels) ? data.labels.map(String) :
    Array.isArray(data.dates) ? data.dates.map(String) :
    Array.isArray(data.xAxis) ? data.xAxis.map(String) : []
  const valuesRaw = Array.isArray(data.values) ? data.values :
    Array.isArray(data.sizes) ? data.sizes :
    Array.isArray(data.yAxis) ? data.yAxis : []
  if (labels.length && valuesRaw.length) {
    const values = labels.map((_, index) => parseClinicalNumber(valuesRaw[index]))
    if (values.some((value) => value !== null)) return sortLabelsWithValues(labels, values)
  }

  const points = Array.isArray(data.points) ? data.points : Array.isArray(data.data) ? data.data : []
  if (!points.length) return null
  const pointLabels: string[] = []
  const pointValues: Array<number | null> = []
  points.forEach((item) => {
    if (!item || typeof item !== 'object') return
    const p = item as Record<string, unknown>
    const label = String(p.date || p.time || p.label || p.x || '')
    const value = parseClinicalNumber(p.value ?? p.size ?? p.diameter ?? p.long_diameter ?? p.y)
    if (label) {
      pointLabels.push(label)
      pointValues.push(value)
    }
  })
  if (!pointLabels.length || !pointValues.some((value) => value !== null)) return null
  return sortLabelsWithValues(pointLabels, pointValues)
}

export function normalizeMultiSeriesChart(raw: unknown, fallbackName = '预测'): MultiSeriesChart | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, unknown>
  const labels = Array.isArray(data.labels) ? data.labels.map(String) :
    Array.isArray(data.dates) ? data.dates.map(String) :
    Array.isArray(data.xAxis) ? data.xAxis.map(String) : []
  const rawSeries = Array.isArray(data.series) ? data.series : []

  if (labels.length && rawSeries.length) {
    const series = rawSeries
      .map((item) => {
        if (!item || typeof item !== 'object') return null
        const s = item as Record<string, unknown>
        const valuesRaw = Array.isArray(s.values) ? s.values : Array.isArray(s.data) ? s.data : []
        const values = labels.map((_, index) => parseClinicalNumber(valuesRaw[index]))
        return values.some((value) => value !== null)
          ? { name: String(s.name || s.label || fallbackName), values }
          : null
      })
      .filter(Boolean) as ChartSeries[]
    if (series.length) {
      const sorted = sortLabelsWithValues(labels, labels.map((_, index) => index))
      return {
        labels: sorted.labels,
        series: compactSeries(
          series.map((item) => ({ ...item, values: sorted.values.map((oldIndex) => item.values[oldIndex] ?? null) })),
          sorted.labels,
        ),
      }
    }
  }

  const pointChart = normalizePointChart(raw)
  if (pointChart) return { labels: pointChart.labels, series: [{ name: String(data.name || fallbackName), values: pointChart.values }] }
  return null
}

export function normalizePairedSeries(
  raw: unknown,
  keyA: string,
  keyB: string,
  labelA: string,
  labelB: string,
): MultiSeriesChart | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, unknown>
  const labels = Array.isArray(data.labels) ? data.labels.map(String) :
    Array.isArray(data.dates) ? data.dates.map(String) :
    Array.isArray(data.xAxis) ? data.xAxis.map(String) : []
  if (!labels.length) return null
  const valuesA: unknown[] = Array.isArray(data[keyA]) ? data[keyA] as unknown[] : Array.isArray(data[keyA.toUpperCase()]) ? data[keyA.toUpperCase()] as unknown[] : []
  const valuesB: unknown[] = Array.isArray(data[keyB]) ? data[keyB] as unknown[] : Array.isArray(data[keyB.toUpperCase()]) ? data[keyB.toUpperCase()] as unknown[] : []
  const series = [
    { name: labelA, values: labels.map((_, index) => parseClinicalNumber(valuesA[index])) },
    { name: labelB, values: labels.map((_, index) => parseClinicalNumber(valuesB[index])) },
  ]
  const sorted = sortLabelsWithValues(labels, labels.map((_, index) => index))
  return {
    labels: sorted.labels,
    series: compactSeries(
      series.map((item) => ({ ...item, values: sorted.values.map((oldIndex) => item.values[oldIndex] ?? null) })),
      sorted.labels,
    ),
  }
}

export function describeSingleSeries(labels: string[], values: Array<number | null>, unit = ''): string {
  const points = labels
    .map((label, index) => ({ label, value: values[index] }))
    .filter((point): point is { label: string; value: number } => point.value !== null)
  if (!points.length) return '当前资料未提供可连续比较的数据点。'
  if (points.length === 1) return `${points[0].label}：${points[0].value}${unit}，暂缺连续时间点，无法判断趋势。`
  const first = points[0]
  const last = points[points.length - 1]
  const delta = last.value - first.value
  const pct = first.value ? (delta / first.value) * 100 : 0
  const direction = delta < 0 ? '下降' : delta > 0 ? '上升' : '基本稳定'
  const missing = values.filter((value) => value === null).length
  const missingText = missing ? `；另有 ${missing} 个时间点缺失数值，曲线中已断开显示` : ''
  return `${first.label} 至 ${last.label}：由 ${first.value}${unit} ${direction}至 ${last.value}${unit}，变化 ${delta >= 0 ? '+' : ''}${delta.toFixed(1)}${unit}（${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%）${missingText}。`
}

export function describeMultiSeries(chart: MultiSeriesChart, unit = ''): string {
  const lines = chart.series
    .map((series) => `${series.name}：${describeSingleSeries(chart.labels, series.values, unit)}`)
    .filter(Boolean)
  return lines.join('\n')
}
