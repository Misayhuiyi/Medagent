import { useState } from 'react'
import { Button, Dropdown } from 'antd'
import { useChatStore } from '../../store'
import { getDownloadUrl } from '../../services/api'

interface DownloadButtonProps {
  patientId: string
  onGenerate: () => Promise<void>
}

export default function DownloadButton({ patientId, onGenerate }: DownloadButtonProps) {
  const isStreaming = useChatStore((s) => s.isStreaming)
  const [generating, setGenerating] = useState(false)

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
            label: (
              <a
                href={getDownloadUrl(patientId, format)}
                download
                style={{ textDecoration: 'none', color: 'inherit' }}
              >
                {label}
              </a>
            ),
          })),
        }}
        trigger={['click']}
      >
        <Button size="small">下载报告</Button>
      </Dropdown>
    </div>
  )
}
