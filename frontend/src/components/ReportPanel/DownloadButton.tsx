import { useState } from 'react'
import { Button, Dropdown, message } from 'antd'
import { useChatStore, usePatientStore } from '../../store'
import { getDownloadUrl } from '../../services/api'

interface DownloadButtonProps {
  patientId: string
  onGenerate: () => Promise<void>
}

function filenameFromDisposition(res: Response, fallback: string): string {
  const contentDisposition = res.headers.get('Content-Disposition') || ''
  const match = contentDisposition.match(/filename\*=UTF-8''([^;\n]+)/) ||
    contentDisposition.match(/filename="?([^";\n]+)"?/)
  try {
    return match ? decodeURIComponent(match[1]) : fallback
  } catch {
    return fallback
  }
}

async function downloadReport(patientId: string, format: 'md' | 'html' | 'pdf', visitDate?: string) {
  const loading = message.loading('正在准备下载...', 0)
  try {
    const res = await fetch(getDownloadUrl(patientId, format, visitDate))
    if (!res.ok) throw new Error(`download failed: ${res.status}`)
    const blob = await res.blob()
    const filename = filenameFromDisposition(res, `${patientId}.${format}`)
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(href), 1000)
  } catch (err) {
    console.error('Failed to download report:', err)
    message.error('下载失败，请稍后重试')
  } finally {
    loading()
  }
}

export default function DownloadButton({ patientId, onGenerate }: DownloadButtonProps) {
  const isStreaming = useChatStore((s) => s.isStreaming)
  const selectedEncounter = usePatientStore((s) => s.selectedEncounter)
  const [generating, setGenerating] = useState(false)
  const visitDate = selectedEncounter?.admission || ''

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      await onGenerate()
    } finally {
      setGenerating(false)
    }
  }

  const formats: Array<{ label: string; format: 'md' | 'html' | 'pdf' }> = [
    { label: '下载 PDF', format: 'pdf' },
    { label: '下载 Markdown', format: 'md' },
    { label: '下载 HTML', format: 'html' },
  ]

  return (
    <div className="report-footer-actions" style={{ display: 'flex', gap: 8 }}>
      <Button
        type="primary"
        size="small"
        loading={generating || isStreaming}
        disabled={isStreaming}
        onClick={handleGenerate}
      >
        {generating ? '生成中...' : '生成报告'}
      </Button>
      <Dropdown
        menu={{
          items: formats.map(({ label, format }) => ({
            key: format,
            label,
            onClick: () => downloadReport(patientId, format, visitDate),
          })),
        }}
        trigger={['click']}
      >
        <Button size="small">下载报告</Button>
      </Dropdown>
    </div>
  )
}
