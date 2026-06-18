import { Form, Input, InputNumber } from 'antd'
import { useEditStore } from '../../store'
import type { TabName } from '../../types'

interface Props {
  tab: TabName
  data: Record<string, unknown>
}

export default function EditForm({ tab, data }: Props) {
  const updateFormField = useEditStore((s) => s.updateFormField)

  const handleChange = (key: string, value: unknown) => {
    updateFormField(tab, { ...data, [key]: value })
  }

  const renderField = (key: string, value: unknown): React.ReactNode => {
    if (typeof value === 'string') {
      return value.length > 80 ? (
        <Form.Item key={key} label={key}>
          <Input.TextArea
            value={value}
            onChange={(e) => handleChange(key, e.target.value)}
            rows={4}
          />
        </Form.Item>
      ) : (
        <Form.Item key={key} label={key}>
          <Input value={value} onChange={(e) => handleChange(key, e.target.value)} />
        </Form.Item>
      )
    }
    if (typeof value === 'number') {
      return (
        <Form.Item key={key} label={key}>
          <InputNumber value={value} onChange={(v) => handleChange(key, v ?? 0)} style={{ width: '100%' }} />
        </Form.Item>
      )
    }
    if (Array.isArray(value)) {
      return (
        <Form.Item key={key} label={`${key} (${value.length} 项)`}>
          <Input.TextArea
            value={JSON.stringify(value, null, 2)}
            onChange={(e) => {
              try { handleChange(key, JSON.parse(e.target.value)) } catch { /* ignore parse errors */ }
            }}
            rows={Math.min(value.length * 3 + 2, 12)}
          />
        </Form.Item>
      )
    }
    if (typeof value === 'object' && value !== null) {
      return (
        <div key={key} style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 8, color: '#0071e3' }}>{key}</div>
          {Object.entries(value as Record<string, unknown>).map(([k, v]) => renderField(k, v))}
        </div>
      )
    }
    return null
  }

  return (
    <Form layout="vertical" size="small">
      {Object.entries(data).map(([key, value]) => renderField(key, value))}
    </Form>
  )
}
