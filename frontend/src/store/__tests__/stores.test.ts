import { describe, it, expect, beforeEach } from 'vitest'
import { usePatientStore, useChatStore, useReportStore, useEditStore } from '../index'

describe('patientStore', () => {
  beforeEach(() => {
    usePatientStore.setState({
      patients: [],
      selectedId: null,
      files: [],
    })
  })

  it('setPatients replaces patient list', () => {
    const patients = [{ id: '张三-123', name: '张三', date: '2026-03-16', file_count: 2 }]
    usePatientStore.getState().setPatients(patients)
    expect(usePatientStore.getState().patients).toEqual(patients)
  })

  it('selectPatient sets selectedId', () => {
    usePatientStore.getState().selectPatient('张三-123')
    expect(usePatientStore.getState().selectedId).toBe('张三-123')
  })

  it('setFiles replaces files list', () => {
    const files = [{ name: '入院记录.txt', size: 1024, type: 'txt', modified_time: 0 }]
    usePatientStore.getState().setFiles(files)
    expect(usePatientStore.getState().files).toEqual(files)
  })

  it('selectPatient with null clears selection', () => {
    usePatientStore.getState().selectPatient('张三-123')
    usePatientStore.getState().selectPatient(null)
    expect(usePatientStore.getState().selectedId).toBeNull()
  })

  it('setPatients auto-selects first patient when no patient is selected', () => {
    const patients = [
      { id: '张三-123', name: '张三', date: '2026-03-16', file_count: 2 },
      { id: '李四-456', name: '李四', date: '2026-03-17', file_count: 1 },
    ]
    usePatientStore.getState().setPatients(patients)
    expect(usePatientStore.getState().selectedId).toBe('张三-123')
  })

  it('setPatients does not change selection if a patient is already selected', () => {
    const patientsA = [{ id: '张三-123', name: '张三', date: '2026-03-16', file_count: 2 }]
    usePatientStore.getState().setPatients(patientsA)
    usePatientStore.getState().selectPatient('张三-123')

    const patientsB = [
      { id: '张三-123', name: '张三', date: '2026-03-16', file_count: 2 },
      { id: '李四-456', name: '李四', date: '2026-03-17', file_count: 1 },
    ]
    usePatientStore.getState().setPatients(patientsB)
    expect(usePatientStore.getState().selectedId).toBe('张三-123')
  })

  it('setPatients with empty list does not auto-select', () => {
    usePatientStore.getState().setPatients([])
    expect(usePatientStore.getState().selectedId).toBeNull()
  })

  it('auto-selection clears files so useEffect can reload them', () => {
    usePatientStore.getState().setFiles([{ name: 'old.txt', size: 100, type: 'txt', modified_time: 0 }])
    const patients = [{ id: '张三-123', name: '张三', date: '2026-03-16', file_count: 2 }]
    usePatientStore.getState().setPatients(patients)
    expect(usePatientStore.getState().files).toEqual([])
  })
})

describe('chatStore', () => {
  beforeEach(() => {
    useChatStore.setState({
      messages: [],
      isStreaming: false,
      lastEventId: undefined,
    })
  })

  it('addMessage appends a message', () => {
    useChatStore.getState().addMessage({ role: 'user', content: '你好', timestamp: '' })
    expect(useChatStore.getState().messages).toHaveLength(1)
    expect(useChatStore.getState().messages[0].role).toBe('user')
  })

  it('addMessages appends multiple messages', () => {
    useChatStore.getState().addMessages([
      { role: 'user', content: '你好', timestamp: '' },
      { role: 'assistant', content: '你好！', timestamp: '' },
    ])
    expect(useChatStore.getState().messages).toHaveLength(2)
  })

  it('appendToLastMessage appends content to last assistant message', () => {
    useChatStore.getState().addMessage({ role: 'assistant', content: '已', timestamp: '' })
    useChatStore.getState().appendToLastMessage('完成')
    expect(useChatStore.getState().messages[0].content).toBe('已完成')
  })

  it('setStreaming toggles streaming state', () => {
    useChatStore.getState().setStreaming(true)
    expect(useChatStore.getState().isStreaming).toBe(true)
  })

  it('clearMessages empties messages and resets state', () => {
    useChatStore.getState().addMessage({ role: 'user', content: 'hi', timestamp: '' })
    useChatStore.getState().setStreaming(true)
    useChatStore.getState().clearMessages()
    expect(useChatStore.getState().messages).toHaveLength(0)
    expect(useChatStore.getState().isStreaming).toBe(false)
  })
})

describe('reportStore', () => {
  beforeEach(() => {
    useReportStore.setState({
      tabs: {},
      activeTab: 'patient-history',
    })
  })

  it('setTabData stores data for a tab', () => {
    useReportStore.getState().setTabData('patient-history', { visit_count: 3 } as any)
    expect(useReportStore.getState().tabs['patient-history']).toEqual({ visit_count: 3 })
  })

  it('setActiveTab changes active tab', () => {
    useReportStore.getState().setActiveTab('treatment-plan')
    expect(useReportStore.getState().activeTab).toBe('treatment-plan')
  })

  it('clearTabs removes all tab data', () => {
    useReportStore.getState().setTabData('patient-history', { visit_count: 3 } as any)
    useReportStore.getState().clearTabs()
    expect(useReportStore.getState().tabs).toEqual({})
  })

  it('setReportData replaces all tabs at once', () => {
    const report = {
      'patient-history': { visit_count: 3 },
      'patient-overview': { chief_complaint: '肺腺癌' },
    }
    useReportStore.getState().setReportData(report as any)
    expect(useReportStore.getState().tabs).toEqual(report)
  })
})

describe('editStore', () => {
  beforeEach(() => {
    useEditStore.setState({
      isEditing: false,
      formData: {},
    })
  })

  it('startEdit sets isEditing and populates formData', () => {
    const data = { 'patient-history': { visit_count: 3 } }
    useEditStore.getState().startEdit(data as any)
    expect(useEditStore.getState().isEditing).toBe(true)
    expect(useEditStore.getState().formData).toEqual(data)
  })

  it('updateFormField updates a nested field', () => {
    useEditStore.getState().startEdit({ 'patient-history': { visit_count: 3 } } as any)
    useEditStore.getState().updateFormField('patient-history', { visit_count: 5 })
    expect((useEditStore.getState().formData as any)['patient-history'].visit_count).toBe(5)
  })

  it('cancelEdit resets state', () => {
    useEditStore.getState().startEdit({ 'patient-history': { visit_count: 3 } } as any)
    useEditStore.getState().cancelEdit()
    expect(useEditStore.getState().isEditing).toBe(false)
    expect(useEditStore.getState().formData).toEqual({})
  })
})
