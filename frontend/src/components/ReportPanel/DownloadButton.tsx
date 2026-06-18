import { Button, Dropdown, message } from 'antd'
import { getDownloadUrl } from '../../services/api'

interface Props {
  patientId: string
  onGenerate: () => Promise<void>
}

const FORMAT_ITEMS = [
  { key: 'pdf', label: 'PDF 报告', format: 'pdf' as const },
  { key: 'html', label: 'HTML 报告', format: 'html' as const },
  { key: 'md', label: 'Markdown 报告', format: 'md' as const },
]

function GenerateIcon() {
  return (
    <svg viewBox="0 0 16 16" focusable="false" aria-hidden="true">
      <path d="M4 2.2h5.5L12 4.7v9.1H4V2.2Z" />
      <path d="M9.4 2.4v2.4h2.4M5.8 7.4h4.4M5.8 9.8h4.4M5.8 12.2h2.8" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 16 16" focusable="false" aria-hidden="true">
      <path d="M8 2.5v7" />
      <path d="M4.8 6.7 8 9.9l3.2-3.2" />
      <path d="M3 12.8h10" />
    </svg>
  )
}

export default function DownloadButton({ patientId, onGenerate }: Props) {
  const handleDownload = async (format: 'md' | 'html' | 'pdf') => {
    const url = getDownloadUrl(patientId, format)
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error(`下载失败: ${res.status}`)
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `report_${patientId}.${format}`
      a.click()
      setTimeout(() => URL.revokeObjectURL(a.href), 100)
    } catch (err) {
      message.error('下载失败，请重试')
    }
  }

  return (
    <div className="report-actions">
      <Button icon={<GenerateIcon />} onClick={onGenerate}>
        生成报告
      </Button>
      <Dropdown
        menu={{
          items: FORMAT_ITEMS.map((item) => ({
            key: item.key,
            label: item.label,
          })),
          onClick: ({ key }) => handleDownload(key as 'md' | 'html' | 'pdf'),
        }}
        placement="topRight"
      >
        <Button type="primary" icon={<DownloadIcon />}>
          下载报告
        </Button>
      </Dropdown>
    </div>
  )
}
