import { useEffect, useRef } from 'react'
import type { ChatMessage } from '../../types'
import MessageBubble from './MessageBubble'

interface Props {
  messages: ChatMessage[]
  showThinking?: boolean
}

export default function MessageList({ messages, showThinking = true }: Props) {
  const listRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const userScrolledUp = useRef(false)
  const isAutoScrolling = useRef(false)
  const visibleMessages = messages
  const lastContent = visibleMessages[visibleMessages.length - 1]?.content || ''
  const lastReasoning = visibleMessages[visibleMessages.length - 1]?.reasoning || ''

  const handleScroll = () => {
    if (isAutoScrolling.current) return
    const el = listRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
    userScrolledUp.current = !atBottom
  }

  useEffect(() => {
    if (!userScrolledUp.current) {
      isAutoScrolling.current = true
      bottomRef.current?.scrollIntoView({ behavior: 'instant' })
      requestAnimationFrame(() => { isAutoScrolling.current = false })
    }
  }, [messages.length, lastContent, lastReasoning])

  return (
    <div className="message-list" ref={listRef} onScroll={handleScroll}>
      <div className="message-list__inner">
        {visibleMessages.map((msg, i) => (
          <MessageBubble key={`${msg.timestamp}-${msg.role}-${i}`} role={msg.role} content={msg.content} reasoning={msg.reasoning} showThinking={showThinking} />
        ))}
      </div>
      <div ref={bottomRef} />
    </div>
  )
}
