import { useState, useRef, useEffect } from 'react'

interface Props {
  onSend: (message: string) => void
  disabled: boolean
}

function AttachIcon() {
  return (
    <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
      <path d="M12 19V5" />
      <path d="M6.5 10.5 12 5l5.5 5.5" />
    </svg>
  )
}

function getTextareaMaxHeight(element: HTMLTextAreaElement) {
  const value = getComputedStyle(element).getPropertyValue('--aidoc-chat-input-max-height')
  return Number.parseFloat(value) || 120
}

export default function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  useEffect(() => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, getTextareaMaxHeight(el))}px`
    }
  }, [value])

  return (
    <div className="chat-input-area">
      <button className="chat-input-addon" type="button" aria-label="添加附件" disabled={disabled}>
        <AttachIcon />
      </button>
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入消息"
        rows={1}
        disabled={disabled}
      />
      <button
        className="chat-input-send"
        type="button"
        onClick={handleSend}
        disabled={disabled || !value.trim()}
      >
        <SendIcon />
      </button>
    </div>
  )
}
