import { create } from 'zustand'
import type { Patient, PatientFile } from '../types'

interface PatientState {
  patients: Patient[]
  selectedId: string | null
  files: PatientFile[]
  setPatients: (patients: Patient[]) => void
  selectPatient: (id: string | null) => void
  removePatient: (id: string) => void
  setFiles: (files: PatientFile[]) => void
}

export const usePatientStore = create<PatientState>((set) => ({
  patients: [],
  selectedId: null,
  files: [],
  setPatients: (patients) => set((state) => {
    const autoSelect = state.selectedId == null && patients.length > 0
    const selectedStillExists = state.selectedId != null && patients.some((patient) => patient.id === state.selectedId)
    return {
      patients,
      selectedId: autoSelect ? patients[0].id : selectedStillExists ? state.selectedId : patients[0]?.id ?? null,
      files: autoSelect || !selectedStillExists ? [] : state.files,
    }
  }),
  selectPatient: (id) => set({ selectedId: id, files: [] }),
  removePatient: (id) => set((state) => {
    const patients = state.patients.filter((patient) => patient.id !== id)
    const removingSelected = state.selectedId === id
    return {
      patients,
      selectedId: removingSelected ? patients[0]?.id ?? null : state.selectedId,
      files: removingSelected ? [] : state.files,
    }
  }),
  setFiles: (files) => set({ files }),
}))
