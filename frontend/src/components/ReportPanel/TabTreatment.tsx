import { useState, type ReactNode } from 'react'
import { Tag } from 'antd'
import { usePatientStore } from '../../store'
import type { TreatmentData, TreatmentPlan, ClinicalTrial } from '../../types'
import FigmaReportCard from './FigmaReportCard'
import TraceModal from './TraceModal'
import { formatClinicalValue } from './textFormat'
import ClinicalText from './ClinicalText'

const TAB = 'treatment-plan'

const STRATEGY_COLORS: Record<string, string> = {
  '维持': '#0071e3',
  '升阶': '#ff9500',
  '降阶': '#34c759',
  '停药': '#ff3b30',
}

function ScoreBar({ label, value, color }: { label: string; value: number; color: string }) {
  const safeValue = Number.isFinite(Number(value)) ? Number(value) : 0
  const normalized = safeValue > 1 ? safeValue / 10 : safeValue
  const pct = Math.min(100, Math.max(0, normalized * 100))
  return (
    <div className="score-row">
      <span className="score-label">{label}</span>
      <div className="score-track">
        <div className="score-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="score-value">{normalized.toFixed(2)}</span>
    </div>
  )
}

function PlanCard({ plan }: { plan: TreatmentPlan }) {
  const patientId = usePatientStore((s) => s.selectedId) || ''
  const [traceOpen, setTraceOpen] = useState(false)

  return (
    <section className="figma-card treatment-plan-card">
      <div className="figma-card__header treatment-plan-card__header">
        <span className="figma-card__icon" aria-hidden="true">
          <svg viewBox="0 0 16 16" focusable="false">
            <path d="M3.2 3.2h9.6v9.6H3.2V3.2Z" />
            <path d="M8 5.1v5.8M5.1 8h5.8" />
          </svg>
        </span>
        <span className="treatment-plan-name">
          {safeText(plan.name) || '未命名方案'}
          <span className="treatment-plan-score"> | 获益评分：{(((Number(plan.efficacy_score) || 0) + (Number(plan.prognosis_score) || 0)) / 2).toFixed(2)}</span>
        </span>
        {plan.strategy && (
          <Tag className="treatment-strategy-tag" color={STRATEGY_COLORS[plan.strategy] || '#8e8e93'}>
            {plan.strategy}
          </Tag>
        )}
      </div>
      <div className="figma-card__body treatment-plan-card__body">
        <div className="score-list">
          <ScoreBar label="疗效" value={plan.efficacy_score} color="#34c759" />
          <ScoreBar label="不良反应" value={plan.adverse_score} color="#ff3b30" />
          <ScoreBar label="预后" value={plan.prognosis_score} color="#0071e3" />
        </div>
        <div className="treatment-plan-detail">
          {plan.reason && <div className="treatment-plan-detail-item"><strong>推荐理由：</strong>{safeText(plan.reason)}</div>}
          {plan.adverse_handling && (
            <div className="treatment-plan-detail-item"><strong>不良反应处理：</strong>{safeText(plan.adverse_handling)}</div>
          )}
        </div>
      </div>
      <div className="figma-card__footer">
        <span className="figma-card__evidence">证据来源：CIP分级标准 + 疗效评估 + 临床获益排序</span>
        <button className="figma-card__trace" type="button" onClick={() => setTraceOpen(true)}>追溯</button>
        <span className="figma-card__level">Ⅰ级</span>
      </div>
      <TraceModal open={traceOpen} question={`${plan.name} 治疗方案`} patientId={patientId} tab={TAB} onClose={() => setTraceOpen(false)} />
    </section>
  )
}

function safeText(v: unknown): string {
  return formatClinicalValue(v)
}

function TreatmentTextCard({ title, content, evidence }: { title: string; content: unknown; evidence: string }) {
  const text = safeText(content)
  if (!text) return null
  return (
    <FigmaReportCard title={title} icon="treatment" evidence={evidence} tab={TAB}>
      <TreatmentRichText text={text} />
    </FigmaReportCard>
  )
}

function TreatmentRichText({ text }: { text: string }) {
  const blocks = splitTreatmentBlocks(text)
  return (
    <div className="clinical-text treatment-rich-text">
      {blocks.map((block, index) => renderTreatmentBlock(block, index))}
    </div>
  )
}

type TreatmentBlock =
  | { type: 'table'; rows: string[][] }
  | { type: 'list'; items: string[] }
  | { type: 'heading'; text: string }
  | { type: 'text'; text: string }

function splitTreatmentBlocks(text: string): TreatmentBlock[] {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const blocks: TreatmentBlock[] = []
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
      if (rows.length) blocks.push({ type: 'table', rows })
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

function renderTreatmentBlock(block: TreatmentBlock, index: number): ReactNode {
  if (block.type === 'heading') {
    return <h4 key={`heading-${index}`} className="treatment-rich-text__heading">{block.text}</h4>
  }
  if (block.type === 'list') {
    return (
      <ul key={`list-${index}`} className="treatment-rich-text__list">
        {block.items.map((item, itemIndex) => <li key={`${item.slice(0, 20)}-${itemIndex}`}><ClinicalText text={item} compact /></li>)}
      </ul>
    )
  }
  if (block.type === 'table') {
    const [header, ...body] = block.rows
    return (
      <div key={`table-${index}`} className="trace-table-wrap treatment-rich-text__table">
        <table>
          <thead>
            <tr>{header.map((cell, cellIndex) => <th key={`${cell}-${cellIndex}`}>{cell}</th>)}</tr>
          </thead>
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}`}>
                {header.map((_, cellIndex) => <td key={`cell-${cellIndex}`}>{row[cellIndex] || ''}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  return <ClinicalText key={`text-${index}`} text={block.text} compact />
}

function TrialCard({ trial }: { trial: ClinicalTrial }) {
  return (
    <div className={`figma-sub-card clinical-trial-card ${trial.match ? 'is-match' : ''}`}>
      <div className="clinical-trial-card__header">
        <span>{trial.name}</span>
        <span>Phase {trial.phase}</span>
      </div>
      <div className="clinical-trial-card__meta">
        {trial.match ? '✓ 匹配' : '✗ 不匹配'} — {trial.criteria}
      </div>
    </div>
  )
}

export default function TabTreatment({ data }: { data?: TreatmentData }) {
  if (!data) return <div className="empty-state">等待治疗方案分析...</div>

  return (
    <div className="report-tab-content treatment-tab-content">
      {data.treatment_plans?.length > 0 && (
        <div className="figma-card-group">
          <div className="figma-card-group__title">治疗方案（按获益评分排序）</div>
          {data.treatment_plans.map((p) => <PlanCard key={p.rank} plan={p} />)}
        </div>
      )}
      <TreatmentTextCard title="不良反应处理方案" content={data.adverse_reaction_plan} evidence="证据来源：CTCAE分级 + CIP处理指南" />
      <TreatmentTextCard title="合并症治疗方案" content={data.comorbidity_plan} evidence="证据来源：合并症记录 + 用药安全规范" />
      {data.clinical_trials?.length > 0 && (
        <FigmaReportCard title="临床试验匹配" icon="treatment" evidence="证据来源：临床试验入排标准 + 患者状态" tab={TAB}>
          {data.clinical_trials.map((t) => <TrialCard key={t.name} trial={t} />)}
        </FigmaReportCard>
      )}
    </div>
  )
}
