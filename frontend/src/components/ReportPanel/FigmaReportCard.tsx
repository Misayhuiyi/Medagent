import { useState, type ReactNode } from 'react'
import { usePatientStore } from '../../store'
import TraceModal from './TraceModal'

type IconType = 'history' | 'overview' | 'treatment' | 'prediction' | 'care' | 'chart' | 'file'

const ICON_PATHS: Record<IconType, ReactNode> = {
  history: (
    <>
      <path d="M3 2.5h9.8v11H3v-11Z" />
      <path d="M5 5.2h5.8M5 7.8h5.8M5 10.4h3.2" />
    </>
  ),
  overview: (
    <>
      <path d="M8 2.2a3 3 0 1 1 0 6 3 3 0 0 1 0-6Z" />
      <path d="M2.8 13.8c.5-2.8 2.6-4.5 5.2-4.5s4.7 1.7 5.2 4.5" />
    </>
  ),
  treatment: (
    <>
      <path d="M3.2 3.2h9.6v9.6H3.2V3.2Z" />
      <path d="M8 5.1v5.8M5.1 8h5.8" />
    </>
  ),
  prediction: (
    <>
      <path d="M2.8 12.8h10.4" />
      <path d="M3.6 10.4 6.2 7.8l2 1.7 3.7-4.8" />
      <path d="M10.8 4.7h1.4v1.4" />
    </>
  ),
  care: (
    <>
      <path d="M8 13.2S3.3 10.4 3.3 6.6A2.4 2.4 0 0 1 7.5 5a2.4 2.4 0 0 1 4.2 1.6c0 3.8-3.7 6.6-3.7 6.6Z" />
    </>
  ),
  chart: (
    <>
      <path d="M3 12.8h10" />
      <path d="M4.4 10.8V7.4M8 10.8V4.2M11.6 10.8V6.2" />
    </>
  ),
  file: (
    <>
      <path d="M3.4 2.2h6.8l2.4 2.5v9.1H3.4V2.2Z" />
      <path d="M10.1 2.4v2.4h2.3M5.2 7.4h5.6M5.2 9.8h5.6M5.2 12.2h3.5" />
    </>
  ),
}

function CardIcon({ type }: { type: IconType }) {
  return (
    <span className="figma-card__icon" aria-hidden="true">
      <svg viewBox="0 0 16 16" focusable="false">
        {ICON_PATHS[type]}
      </svg>
    </span>
  )
}

export interface FigmaReportCardProps {
  title: ReactNode
  children: ReactNode
  evidence?: string
  level?: string
  icon?: IconType
  className?: string
  tab?: string
}

export default function FigmaReportCard({
  title,
  children,
  evidence = '证据来源：患者病历 + 检查报告 + 当前问诊记录',
  level = 'Ⅰ级',
  icon = 'file',
  className = '',
  tab = '',
}: FigmaReportCardProps) {
  const patientId = usePatientStore((s) => s.selectedId) || ''
  const [traceOpen, setTraceOpen] = useState(false)
  const traceQuestion = `${title} ${evidence}`.slice(0, 200)

  return (
    <section className={`figma-card is-expanded ${className}`.trim()}>
      <div className="figma-card__header">
        <CardIcon type={icon} />
        <div className="figma-card__title">{title}</div>
      </div>
      <div className="figma-card__body">
        {children}
      </div>
      <div className="figma-card__footer">
        <span className="figma-card__evidence">{evidence}</span>
        <button className="figma-card__trace" type="button" onClick={() => setTraceOpen(true)}>追溯</button>
        <span className="figma-card__level">{level}</span>
      </div>
      <TraceModal open={traceOpen} question={traceQuestion} patientId={patientId} tab={tab} onClose={() => setTraceOpen(false)} />
    </section>
  )
}
