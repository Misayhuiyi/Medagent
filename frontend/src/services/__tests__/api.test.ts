import { describe, it, expect } from 'vitest'
import { parseSSE } from '../api'

describe('parseSSE', () => {
  it('parses a single complete event', () => {
    const buffer = 'id: 1\nevent: status\ndata: {"state":"reading_files"}\n\n'
    const { remaining, events } = parseSSE(buffer)
    expect(remaining).toBe('')
    expect(events).toHaveLength(1)
    expect(events[0]).toEqual({
      id: 1,
      type: 'status',
      data: { state: 'reading_files' },
    })
  })

  it('parses multiple events', () => {
    const buffer =
      'id: 1\nevent: status\ndata: {"state":"reading_files"}\n\n' +
      'id: 2\nevent: token\ndata: {"content":"已"}\n\n'
    const { events } = parseSSE(buffer)
    expect(events).toHaveLength(2)
    expect(events[0].type).toBe('status')
    expect(events[1].type).toBe('token')
    expect(events[1].data).toEqual({ content: '已' })
  })

  it('returns incomplete block as remaining', () => {
    const buffer = 'id: 1\nevent: status\ndata: {"state":"reading_files"}\n\nid: 2\nevent: done'
    const { remaining, events } = parseSSE(buffer)
    expect(events).toHaveLength(1)
    expect(remaining).toBe('id: 2\nevent: done')
  })

  it('handles empty buffer', () => {
    const { remaining, events } = parseSSE('')
    expect(events).toHaveLength(0)
    expect(remaining).toBe('')
  })

  it('handles tab_ready event with tab and data', () => {
    const buffer =
      'id: 3\nevent: tab_ready\ndata: {"tab":"history","data":{"visit_count":3}}\n\n'
    const { events } = parseSSE(buffer)
    expect(events).toHaveLength(1)
    expect(events[0].type).toBe('tab_ready')
    expect(events[0].data).toEqual({ tab: 'history', data: { visit_count: 3 } })
  })

  it('handles error event', () => {
    const buffer =
      'id: 4\nevent: error\ndata: {"tab":"overview","message":"Skill not found"}\n\n'
    const { events } = parseSSE(buffer)
    expect(events[0].type).toBe('error')
    expect(events[0].data).toEqual({ tab: 'overview', message: 'Skill not found' })
  })

  it('handles done event', () => {
    const buffer = 'id: 5\nevent: done\ndata: {}\n\n'
    const { events } = parseSSE(buffer)
    expect(events[0].type).toBe('done')
  })

  it('skips blocks missing required fields', () => {
    const buffer = 'id: 1\ndata: {"state":"reading_files"}\n\n'
    const { events } = parseSSE(buffer)
    expect(events).toHaveLength(0)
  })

  it('handles Chinese characters in data', () => {
    const buffer =
      'id: 2\nevent: token\ndata: {"content":"已完成患者病史分析\\n"}\n\n'
    const { events } = parseSSE(buffer)
    expect(events[0].data).toEqual({ content: '已完成患者病史分析\n' })
  })
})
