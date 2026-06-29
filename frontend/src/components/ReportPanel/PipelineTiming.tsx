import { useEffect, useState } from 'react'

interface StepTiming {
  step: string
  display_name: string
  elapsed_s: number
  status: string
  error: string | null
}

interface PipelineRun {
  patient_id: string
  timestamp: string
  total_elapsed_s: number
  steps: StepTiming[]
  total_files: number
}

export default function PipelineTiming({ patientId }: { patientId: string | null }) {
  const [runs, setRuns] = useState<PipelineRun[]>([])
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!patientId) return
    fetch(`/api/debug/pipeline/${encodeURIComponent(patientId)}?limit=1`)
      .then((res) => res.json())
      .then((data) => setRuns(data.runs || []))
      .catch(() => { /* ignore */ })
  }, [patientId])

  if (runs.length === 0) return null

  const latest = runs[0]
  const totalMin = Math.round(latest.total_elapsed_s / 60)
  const totalSec = Math.round(latest.total_elapsed_s % 60)

  return (
    <div className="pipeline-timing">
      <button
        className="pipeline-timing__toggle"
        type="button"
        onClick={() => setExpanded(!expanded)}
      >
        <span className={`pipeline-timing__chevron ${expanded ? 'is-expanded' : ''}`}>
          <svg viewBox="0 0 10 10" width="10" height="10">
            <path d="M3.2 1.5 6.8 5 3.2 8.5" />
          </svg>
        </span>
        <span>运行详情</span>
        <span className="pipeline-timing__summary">
          共 {latest.steps.length} 步 · 耗时 {totalMin}分{totalSec}秒
        </span>
      </button>
      {expanded && (
        <div className="pipeline-timing__body">
          <div className="pipeline-timing__header">
            <span>生成时间: {latest.timestamp}</span>
            <span>文件数: {latest.total_files}</span>
          </div>
          <div className="pipeline-timing__steps">
            {latest.steps.map((step) => {
              const pct = latest.total_elapsed_s > 0
                ? Math.round((step.elapsed_s / latest.total_elapsed_s) * 100)
                : 0
              const barColor = step.status === 'ok'
                ? '#34c759'
                : step.status === 'fallback'
                  ? '#ff9f0a'
                  : '#ff3b30'
              const stepSec = Math.round(step.elapsed_s)
              const stepMin = Math.floor(stepSec / 60)
              const stepRem = stepSec % 60
              const timeStr = stepMin > 0 ? `${stepMin}分${stepRem}秒` : `${stepRem}秒`
              return (
                <div className="pipeline-timing__step" key={step.step}>
                  <div className="pipeline-timing__step-label">
                    <span className="pipeline-timing__step-name">{step.display_name}</span>
                    <span className="pipeline-timing__step-time">{timeStr}</span>
                    {step.error && <span className="pipeline-timing__step-error">⚠ {step.error}</span>}
                  </div>
                  <div className="pipeline-timing__bar-track">
                    <div
                      className="pipeline-timing__bar-fill"
                      style={{ width: `${pct}%`, background: barColor }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
