import { create } from 'zustand'
import type { ReportData, TabName } from '../types'

interface EditState {
  isEditing: boolean
  formData: Partial<ReportData>
  startEdit: (data: Partial<ReportData>) => void
  updateFormField: (tab: TabName, data: unknown) => void
  cancelEdit: () => void
  saveEdit: () => Partial<ReportData>
}

export const useEditStore = create<EditState>((set, get) => ({
  isEditing: false,
  formData: {},

  startEdit: (data) => set({ isEditing: true, formData: JSON.parse(JSON.stringify(data)) }),

  updateFormField: (tab, data) =>
    set((state) => ({ formData: { ...state.formData, [tab]: data } })),

  cancelEdit: () => set({ isEditing: false, formData: {} }),

  saveEdit: () => {
    const { formData } = get()
    set({ isEditing: false })
    return formData
  },
}))
