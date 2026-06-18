import { useChatStore } from '../../store'
import MarkdownRenderer from '../common/MarkdownRenderer'
function formatTime(s: number) { return s < 60 ? `${s}s` : `${Math.floor(s/60)}m${s%60}s` }

interface Props {
  role: 'user' | 'assistant' | 'status'
  content: string
  reasoning?: string
  showThinking?: boolean
}

function MessageAvatar({ role }: { role: 'user' | 'assistant' }) {
  if (role === 'user') {
    return (
      <span className="message-avatar message-avatar--user" aria-hidden="true">
        <img src="/aidoc/patient-avatar.png" alt="" />
      </span>
    )
  }

  return (
    <span className="message-avatar message-avatar--assistant" aria-hidden="true">
      <img src="/aidoc/ai-doctor-avatar.png" alt="" />
    </span>
  )
}

export default function MessageBubble({ role, content, reasoning, showThinking = true }: Props) {
  const thinkingTime = useChatStore((s) => s.thinkingTime)
  const isStreaming = useChatStore((s) => s.isStreaming)

  if (role === 'status') {
    const displayText = isStreaming
      ? `thinking ${formatTime(thinkingTime)}`
      : thinkingTime > 0
        ? `完成思考（耗时 ${formatTime(thinkingTime)}）`
        : content
    return (
      <div className="message-row message-row--status">
        <div className="message-bubble message-bubble--assistant message-bubble--status">
          <div className="message-bubble__content">{displayText}</div>
          <span className="message-status-icon" aria-hidden="true">
            <svg viewBox="0 0 12 12" focusable="false">
              <path d="M3 6h6M6 3v6" />
            </svg>
          </span>
        </div>
      </div>
    )
  }

  const rowClassName = role === 'assistant' ? 'message-row message-row--assistant' : 'message-row message-row--user'
  const bubbleClassName = role === 'assistant' ? 'message-bubble message-bubble--assistant' : 'message-bubble message-bubble--user'

  return (
    <div className={rowClassName}>
      <MessageAvatar role={role} />
      <div className={bubbleClassName}>
        <div className="message-bubble__content">
          {role === 'assistant' ? (
            <>
              {reasoning && showThinking && (
                <div className="reasoning-block">
                  <div className="reasoning-content">{reasoning}</div>
                </div>
              )}
              {reasoning && !showThinking && isStreaming && (
                <div className="reasoning-block reasoning-block--compact">正在思考中...</div>
              )}
              <MarkdownRenderer content={content} />
            </>
          ) : (
            content
          )}
        </div>
      </div>
    </div>
  )
}
