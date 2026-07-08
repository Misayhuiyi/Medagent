import type { ReactNode } from 'react'
import type { SemanticHighlight, SemanticHighlightCarrier } from '../../types'

const COLOR_CLASS: Record<SemanticHighlight['color'], string> = {
  red: 'clinical-mark clinical-mark--red',
  blue: 'clinical-mark clinical-mark--blue',
  green: 'clinical-mark clinical-mark--green',
}

const AUTO_TERMS: Record<SemanticHighlight['color'], string[]> = {
  red: [
    '免疫检查点抑制相关肺炎', '免疫相关性肺炎', '肺泡蛋白沉积症', '炎症后肺纤维化',
    '不良反应', '毒副反应', '肺炎', '间质性炎症', '间质性肺病', '肺纤维化',
    'CIP', 'ILD', 'PAP', 'irAE', 'CTCAE', 'G3', '3级',
    '气胸', '咯血', '发热', '感染', '高血糖', '肝功能异常', '风险', '禁忌', '警惕', '恶化',
  ],
  blue: [
    '左肺腺癌', '肺恶性肿瘤', '肿瘤负荷', '原发灶', '靶病灶', '肿瘤', '病灶', '结节',
    '分期', '复发', '进展', '转移', '淋巴结', 'KRAS G12C', 'KRAS', 'TP53', 'PD-L1', 'PDL1', 'TMB', 'RECIST', 'TNM', 'pT', 'cT', 'CT', 'PET-CT',
  ],
  green: [
    '新辅助治疗', '辅助治疗', '维持治疗', '抗血管生成', '靶向治疗', '免疫治疗',
    '治疗', '疗效', '缓解', '缩小', '稳定', '改善', '随访', '复查', '手术',
    '化疗', '培美曲塞', '卡铂', '信迪利单抗', '贝伐珠单抗', '索托拉西布', '阿达格拉西布',
    'DLCO', 'HRCT', 'WLL', 'MRD', 'Ⅰ类', 'ⅡA类', 'ⅡB类', '1类', '2A类', '2B类',
    '康复', '护理', '监测',
  ],
}

export function highlightsFrom(data?: SemanticHighlightCarrier): SemanticHighlight[] {
  return Array.isArray(data?._semantic_highlights) ? data._semantic_highlights : []
}

export function autoHighlights(text: string): SemanticHighlight[] {
  const found: SemanticHighlight[] = []
  for (const [color, terms] of Object.entries(AUTO_TERMS) as Array<[SemanticHighlight['color'], string[]]>) {
    for (const term of terms) {
      if (text.includes(term)) found.push({ text: term, color, reason: color === 'red' ? '不良反应/风险' : color === 'blue' ? '肿瘤负荷' : '治疗及疗效' })
    }
  }
  return found
}

function renderHighlighted(text: string, highlights: SemanticHighlight[]): ReactNode[] {
  if (!text || !highlights.length) return [text]
  const ranges: Array<{ start: number; end: number; color: SemanticHighlight['color']; reason?: string }> = []

  for (const h of highlights) {
    if (!h.text || !h.color) continue
    let from = 0
    while (from < text.length) {
      const start = text.indexOf(h.text, from)
      if (start < 0) break
      ranges.push({ start, end: start + h.text.length, color: h.color, reason: h.reason })
      from = start + h.text.length
    }
  }

  const selected: typeof ranges = []
  const occupied: Array<{ start: number; end: number }> = []
  for (const range of ranges.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start))) {
    if (occupied.some((used) => range.start < used.end && range.end > used.start)) continue
    selected.push(range)
    occupied.push({ start: range.start, end: range.end })
  }
  selected.sort((a, b) => a.start - b.start)

  const nodes: ReactNode[] = []
  let cursor = 0
  selected.forEach((range, index) => {
    if (cursor < range.start) nodes.push(text.slice(cursor, range.start))
    nodes.push(
      <mark key={`${range.start}-${range.end}-${index}`} className={COLOR_CLASS[range.color]} title={range.reason}>
        {text.slice(range.start, range.end)}
      </mark>,
    )
    cursor = range.end
  })
  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

export default function ClinicalText({
  text,
  highlights = [],
  compact = false,
}: {
  text?: string | number | null
  highlights?: SemanticHighlight[]
  compact?: boolean
}) {
  const value = text == null ? '' : String(text).trim()
  if (!value) return null
  const effectiveHighlights = highlights.length ? highlights : autoHighlights(value)

  return (
    <div className={compact ? 'clinical-text clinical-text--compact' : 'clinical-text'}>
      {renderClinicalBlocks(value, effectiveHighlights)}
    </div>
  )
}

type ClinicalBlock =
  | { type: 'table'; rows: string[][] }
  | { type: 'trend-chart'; rows: string[][] }
  | { type: 'risk-chart'; rows: string[][] }
  | { type: 'heatmap'; rows: string[][] }
  | { type: 'list'; items: string[] }
  | { type: 'heading'; text: string }
  | { type: 'text'; text: string }

function renderClinicalBlocks(value: string, highlights: SemanticHighlight[]) {
  const blocks = splitClinicalBlocks(value)
  return blocks.map((block, index) => {
    if (block.type === 'heading') {
      return <h4 key={`heading-${index}`} className="clinical-text__heading">{renderHighlighted(block.text, highlights)}</h4>
    }
    if (block.type === 'list') {
      return (
        <ul key={`list-${index}`} className="clinical-text__list">
          {block.items.map((item, itemIndex) => <li key={`${item.slice(0, 20)}-${itemIndex}`}>{renderHighlighted(item, highlights)}</li>)}
        </ul>
      )
    }
    if (block.type === 'table') {
      const [header, ...body] = block.rows
      return (
        <div key={`table-${index}`} className="trace-table-wrap clinical-text__table">
          <table>
            <thead>
              <tr>{header.map((cell, cellIndex) => <th key={`${cell}-${cellIndex}`}>{renderHighlighted(cell, highlights)}</th>)}</tr>
            </thead>
            <tbody>
              {body.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {header.map((_, cellIndex) => <td key={`cell-${cellIndex}`}>{renderHighlighted(row[cellIndex] || '', highlights)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }
    if (block.type === 'trend-chart') {
      return <TrendChartBlock key={`trend-${index}`} rows={block.rows} highlights={highlights} />
    }
    if (block.type === 'risk-chart') {
      return <RiskChartBlock key={`risk-${index}`} rows={block.rows} highlights={highlights} />
    }
    if (block.type === 'heatmap') {
      return <HeatmapBlock key={`heat-${index}`} rows={block.rows} highlights={highlights} />
    }
    return <p key={`${block.text.slice(0, 24)}-${index}`}>{renderHighlighted(block.text, highlights)}</p>
  })
}

function splitClinicalBlocks(value: string): ClinicalBlock[] {
  const lines = value.replace(/\r\n/g, '\n').split('\n')
  const blocks: ClinicalBlock[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i].trim()
    if (!line) {
      i += 1
      continue
    }
    if (isMarkdownTableStart(lines, i)) {
      const tableLines: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i].trim())
        i += 1
      }
      const rows = tableLines
        .filter((row) => !/^\|[-: |]+\|$/.test(row))
        .map((row) => row.replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim()))
        .filter((row) => row.some(Boolean))
      if (rows.length) blocks.push(tableRowsToBlock(rows))
      continue
    }
    if (/^#{1,4}\s+/.test(line)) {
      blocks.push({ type: 'heading', text: line.replace(/^#{1,4}\s+/, '') })
      i += 1
      continue
    }
    if (/^[-*]\s+/.test(line) || /^\d+[.、]\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length) {
        const itemLine = lines[i].trim()
        if (!/^[-*]\s+/.test(itemLine) && !/^\d+[.、]\s+/.test(itemLine)) break
        items.push(itemLine.replace(/^[-*]\s+/, '').replace(/^\d+[.、]\s+/, ''))
        i += 1
      }
      blocks.push({ type: 'list', items })
      continue
    }
    blocks.push({ type: 'text', text: line })
    i += 1
  }
  return blocks
}

function isMarkdownTableStart(lines: string[], index: number) {
  const current = lines[index]?.trim() || ''
  const next = lines[index + 1]?.trim() || ''
  return current.startsWith('|') && current.endsWith('|') && /^\|[-: |]+\|$/.test(next)
}

function tableRowsToBlock(rows: string[][]): ClinicalBlock {
  const header = rows[0] || []
  const has = (name: string) => header.includes(name)
  if (has('时间点') && has('指标') && has('数值') && has('单位')) return { type: 'trend-chart', rows }
  if (has('不良反应') && has('预测概率') && has('风险等级')) return { type: 'risk-chart', rows }
  if (header[0] === '不良反应' && header.includes('T1') && header.includes('等级说明')) return { type: 'heatmap', rows }
  return { type: 'table', rows }
}

function tableCell(row: string[], header: string[], name: string) {
  const index = header.indexOf(name)
  return index >= 0 ? row[index] || '' : ''
}

function clinicalNumber(value: string) {
  const match = String(value || '').match(/-?\d+(?:\.\d+)?/)
  return match ? Number(match[0]) : null
}

function TrendChartBlock({ rows, highlights }: { rows: string[][]; highlights: SemanticHighlight[] }) {
  const [header, ...body] = rows
  const grouped = new Map<string, Array<{ label: string; value: number; unit: string; trend: string; note: string }>>()
  body.forEach((row, index) => {
    const metric = tableCell(row, header, '指标') || '指标'
    const value = clinicalNumber(tableCell(row, header, '数值'))
    if (value === null) return
    const point = {
      label: tableCell(row, header, '时间点') || `T${index + 1}`,
      value,
      unit: tableCell(row, header, '单位'),
      trend: tableCell(row, header, '变化趋势'),
      note: tableCell(row, header, '临床解释'),
    }
    grouped.set(metric, [...(grouped.get(metric) || []), point])
  })
  const [metric, points] = [...grouped.entries()].sort((a, b) => b[1].length - a[1].length)[0] || []
  if (!metric || !points || points.length < 2) {
    return <DataTable rows={rows} highlights={highlights} />
  }
  const width = 640
  const height = 250
  const left = 54
  const right = 20
  const top = 24
  const bottom = 44
  const plotW = width - left - right
  const plotH = height - top - bottom
  const values = points.map((point) => point.value)
  let min = Math.min(...values)
  let max = Math.max(...values)
  if (Math.abs(max - min) < 0.0001) {
    max += 1
    min -= 1
  }
  const pad = (max - min) * 0.12
  min -= pad
  max += pad
  const xy = (index: number, value: number) => {
    const x = left + (plotW * index) / Math.max(points.length - 1, 1)
    const y = top + plotH - ((value - min) / (max - min)) * plotH
    return { x, y }
  }
  const polyline = points.map((point, index) => {
    const { x, y } = xy(index, point.value)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const first = points[0]
  const last = points[points.length - 1]
  const delta = last.value - first.value
  const direction = delta > 0 ? '上升' : delta < 0 ? '下降' : '稳定'
  const unit = points.find((point) => point.unit)?.unit || ''
  const summary = `${metric}：${first.label} ${first.value}${unit}，${last.label} ${last.value}${unit}，总体${direction} ${Math.abs(delta).toFixed(delta % 1 ? 1 : 0)}${unit}。`
  return (
    <div className="clinical-chart clinical-chart--trend">
      <div className="clinical-chart__summary">{renderHighlighted(summary, highlights)}</div>
      <svg className="clinical-chart__svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${metric}趋势图`}>
        {[0, 1, 2, 3, 4].map((line) => (
          <line key={line} className="clinical-chart__grid" x1={left} y1={top + (plotH * line) / 4} x2={width - right} y2={top + (plotH * line) / 4} />
        ))}
        <line className="clinical-chart__axis" x1={left} y1={top} x2={left} y2={height - bottom} />
        <line className="clinical-chart__axis" x1={left} y1={height - bottom} x2={width - right} y2={height - bottom} />
        <polyline className="clinical-chart__line" points={polyline} />
        {points.map((point, index) => {
          const { x, y } = xy(index, point.value)
          return (
            <g key={`${point.label}-${index}`}>
              <circle className="clinical-chart__dot" cx={x} cy={y} r="4" />
              <text x={x} y={height - 20} textAnchor="middle">{point.label}</text>
              <text x={x} y={y - 8} textAnchor="middle">{point.value}{unit}</text>
            </g>
          )
        })}
        <text className="clinical-chart__axis-title" x="10" y="17">{metric} / {unit}</text>
      </svg>
      <DataTable rows={[['时间点', '数值', '趋势', '临床解释'], ...points.map((point) => [point.label, `${point.value}${point.unit}`, point.trend, point.note])]} highlights={highlights} compact />
    </div>
  )
}

function RiskChartBlock({ rows, highlights }: { rows: string[][]; highlights: SemanticHighlight[] }) {
  const [header, ...body] = rows
  return (
    <div className="clinical-chart clinical-chart--risk">
      {body.map((row, index) => {
        const name = tableCell(row, header, '不良反应')
        const probability = tableCell(row, header, '预测概率')
        const risk = tableCell(row, header, '风险等级')
        const monitor = tableCell(row, header, '监测建议') || tableCell(row, header, '处理建议')
        const value = Math.max(0, Math.min(100, clinicalNumber(probability) || 0))
        const level = risk.includes('高') || value >= 30 ? 'high' : risk.includes('中') || value >= 10 ? 'medium' : 'low'
        return (
          <div key={`${name}-${index}`} className={`clinical-risk clinical-risk--${level}`}>
            <span>{renderHighlighted(name, highlights)}</span>
            <b>{probability}</b>
            <i><em style={{ width: `${value}%` }} /></i>
            <strong>{renderHighlighted(risk, highlights)}</strong>
            <small>{renderHighlighted(monitor, highlights)}</small>
          </div>
        )
      })}
      <DataTable rows={rows} highlights={highlights} compact />
    </div>
  )
}

function HeatmapBlock({ rows, highlights }: { rows: string[][]; highlights: SemanticHighlight[] }) {
  const [header, ...body] = rows
  const timeCols = header.filter((cell) => /^T\d+$/.test(cell))
  return (
    <div className="clinical-chart clinical-chart--heatmap">
      <div className="clinical-heatmap__legend"><span>0 无</span><span>1 轻度</span><span>2 中度</span><span>3 重度</span><span>4 危重</span></div>
      {body.map((row, index) => (
        <div key={`heat-${index}`} className="clinical-heatmap__row" style={{ gridTemplateColumns: `96px repeat(${timeCols.length}, minmax(38px, 1fr))` }}>
          <strong>{renderHighlighted(tableCell(row, header, '不良反应'), highlights)}</strong>
          {timeCols.map((col) => {
            const value = tableCell(row, header, col)
            const grade = Math.max(0, Math.min(4, clinicalNumber(value) || 0))
            return <span key={col} className={`clinical-heatmap__cell clinical-heatmap__cell--g${grade}`}>{value || '-'}</span>
          })}
        </div>
      ))}
      <DataTable rows={rows} highlights={highlights} compact />
    </div>
  )
}

function DataTable({ rows, highlights, compact = false }: { rows: string[][]; highlights: SemanticHighlight[]; compact?: boolean }) {
  const [header, ...body] = rows
  return (
    <div className={compact ? 'trace-table-wrap clinical-text__table clinical-text__table--compact' : 'trace-table-wrap clinical-text__table'}>
      <table>
        <thead>
          <tr>{header.map((cell, cellIndex) => <th key={`${cell}-${cellIndex}`}>{renderHighlighted(cell, highlights)}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {header.map((_, cellIndex) => <td key={`cell-${cellIndex}`}>{renderHighlighted(row[cellIndex] || '', highlights)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
