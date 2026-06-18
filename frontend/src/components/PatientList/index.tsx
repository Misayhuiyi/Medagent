import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import { message } from 'antd'
import { usePatientStore } from '../../store'
import { fetchPatients, fetchPatientFiles } from '../../services/api'
import AddPatientButton from './AddPatientButton'
import type { PatientFile } from '../../types'

interface FileTreeReport {
  name: string
  files: PatientFile[]
}

interface FileTreeEncounter {
  name: string
  reports: FileTreeReport[]
}

const REPORT_ORDER = ['影像报告', '检验报告', '病历', '病理报告']
const REPORT_MATCHERS: Array<[string, RegExp]> = [
  ['影像报告', /影像|CT|PET|MRI|胸部|肺部/i],
  ['检验报告', /检验|血常规|生化|标志物|基因|NGS|实验室/i],
  ['病历', /病历|入院|出院|门诊|会诊|记录|病程/i],
  ['病理报告', /病理|活检|穿刺|免疫组化/i],
]

function formatDate(date: string) {
  if (!date) return ''
  const parts = date.split('-')
  if (parts.length !== 3) return date
  return `${parts[0]}-${Number(parts[1])}-${Number(parts[2])}`
}

function normalizeEncounterName(name: string, fallbackDate?: string, dischargeDate?: string) {
  if (name) return name
  const parts: string[] = []
  if (fallbackDate) parts.push(`入院 ${formatDate(fallbackDate)}`)
  if (dischargeDate && dischargeDate !== fallbackDate) parts.push(`出院 ${formatDate(dischargeDate)}`)
  return parts.length > 0 ? parts.join('  ') : '就诊记录'
}

function normalizeReportName(value: string) {
  return REPORT_MATCHERS.find(([, matcher]) => matcher.test(value))?.[0] || value || '病历'
}

function buildFileTree(files: PatientFile[], fallbackDate?: string, dischargeDate?: string): FileTreeEncounter[] {
  const encounterMap = new Map<string, Map<string, PatientFile[]>>()
  files.forEach((file) => {
    const parts = file.name.split('/').filter(Boolean)
    const hasEncounterLayer = parts.length >= 3 && /时间|入院|门诊|出院|住院|复诊/.test(parts[0])
    const encounterName = normalizeEncounterName(hasEncounterLayer ? parts[0] : '', fallbackDate, dischargeDate)
    const reportName = normalizeReportName(hasEncounterLayer ? parts[1] : parts[0])
    if (!encounterMap.has(encounterName)) {
      encounterMap.set(encounterName, new Map())
    }
    const reportMap = encounterMap.get(encounterName)!
    if (!reportMap.has(reportName)) {
      reportMap.set(reportName, [])
    }
    reportMap.get(reportName)!.push(file)
  })

  return Array.from(encounterMap.entries()).map(([name, reportMap]) => ({
    name,
    reports: Array.from(reportMap.entries())
      .sort(([a], [b]) => {
        const aIndex = REPORT_ORDER.indexOf(a)
        const bIndex = REPORT_ORDER.indexOf(b)
        return (aIndex === -1 ? 99 : aIndex) - (bIndex === -1 ? 99 : bIndex)
      })
      .map(([reportName, reportFiles]) => ({ name: reportName, files: reportFiles })),
  }))
}

function leafName(path: string) {
  const parts = path.split('/').filter(Boolean)
  return parts[parts.length - 1] || path
}

function formatFileLabel(path: string) {
  const name = leafName(path)
  const match = /^(.*?)-\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})(\.pdf)$/i.exec(name)
  if (!match) return name
  return `${match[1]}-\n${match[2]}-${Number(match[3])}-${Number(match[4])}${match[5]}`
}

function TrashIcon() {
  return <img src="/aidoc/icon-delete.png" alt="" width="16" height="16" />
}

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <span className={`tree-chevron ${expanded ? 'is-expanded' : ''}`} aria-hidden="true">
      <svg viewBox="0 0 10 10" focusable="false">
        <path d="M3.2 1.5 6.8 5 3.2 8.5" />
      </svg>
    </span>
  )
}

function SearchIcon() {
  return (
    <span className="search-icon" aria-hidden="true">
      <svg viewBox="0 0 16 16" focusable="false">
        <circle cx="7" cy="7" r="4.2" />
        <path d="M10.2 10.2 13.2 13.2" />
      </svg>
    </span>
  )
}

function CalendarIcon() {
  return <span className="tree-icon tree-icon--calendar" aria-hidden="true"><img src="/aidoc/icon-admission.png" alt="" width="16" height="16" /></span>
}

function ReportCategoryIcon() {
  return <span className="tree-icon tree-icon--category" aria-hidden="true"><img src="/aidoc/icon-medrecord.png" alt="" width="16" height="16" /></span>
}

function ImagingReportIcon() {
  return <span className="tree-icon tree-icon--category" aria-hidden="true"><img src="/aidoc/icon-imaging.png" alt="" width="16" height="16" /></span>
}

function LabReportIcon() {
  return <span className="tree-icon tree-icon--category" aria-hidden="true"><img src="/aidoc/icon-labtest.png" alt="" width="16" height="16" /></span>
}

function MedicalRecordIcon() {
  return <span className="tree-icon tree-icon--category" aria-hidden="true"><img src="/aidoc/icon-medrecord.png" alt="" width="16" height="16" /></span>
}

function PathologyReportIcon() {
  return <span className="tree-icon tree-icon--category" aria-hidden="true"><img src="/aidoc/icon-pathology.png" alt="" width="16" height="16" /></span>
}

function ReportIcon({ name }: { name: string }) {
  if (name.includes('影像')) return <ImagingReportIcon />
  if (name.includes('检验')) return <LabReportIcon />
  if (name.includes('病理')) return <PathologyReportIcon />
  if (name.includes('病历')) return <MedicalRecordIcon />
  return <ReportCategoryIcon />
}

function PdfIcon() {
  return <span className="file-icon" aria-hidden="true"><img src="/aidoc/icon-pdf.png" alt="" width="12" height="14" /></span>
}

function PatientIcon() {
  return (
    <span className="aidoc-patient-icon" aria-hidden="true">
      <svg viewBox="0 0 18 18" focusable="false">
        <path d="M9 9.2a4.3 4.3 0 1 0 0-8.6 4.3 4.3 0 0 0 0 8.6Z" />
        <path d="M1.6 17.4c.35-3.85 3.48-6.75 7.4-6.75s7.05 2.9 7.4 6.75H1.6Z" />
      </svg>
    </span>
  )
}

export default function PatientList() {
  const patients = usePatientStore((s) => s.patients)
  const selectedId = usePatientStore((s) => s.selectedId)
  const files = usePatientStore((s) => s.files)
  const setPatients = usePatientStore((s) => s.setPatients)
  const selectPatient = usePatientStore((s) => s.selectPatient)
  const removePatient = usePatientStore((s) => s.removePatient)
  const setFiles = usePatientStore((s) => s.setFiles)
  const [keyword, setKeyword] = useState('')
  const [expandedPatients, setExpandedPatients] = useState<Set<string>>(new Set())
  const [expandedEncounters, setExpandedEncounters] = useState<Set<string>>(new Set())
  const [expandedReports, setExpandedReports] = useState<Set<string>>(new Set())
  const [selectedFile, setSelectedFile] = useState('')

  useEffect(() => {
    fetchPatients().then(setPatients).catch(console.error)
  }, [setPatients])

  useEffect(() => {
    if (!selectedId) {
      setFiles([])
      return
    }
    setExpandedPatients((prev) => new Set(prev).add(selectedId))
    fetchPatientFiles(selectedId)
      .then((nextFiles) => {
        setFiles(nextFiles)
        setSelectedFile(nextFiles[0]?.name ?? '')
      })
      .catch(console.error)
  }, [selectedId, setFiles])

  const selectedPatient = patients.find((patient) => patient.id === selectedId)
  const tree = useMemo(() => buildFileTree(files, selectedPatient?.date, selectedPatient?.discharge_date), [files, selectedPatient?.date, selectedPatient?.discharge_date])

  // 就诊记录: 每次入院为一个条目
  const encounterList = useMemo(() => {
    if (selectedPatient?.encounters && selectedPatient.encounters.length > 0) {
      return selectedPatient.encounters.map((enc) => ({
        name: `入院时间 ${formatDate(enc.admission)}`,
        reports: tree[0]?.reports || [],
      }))
    }
    return tree
  }, [selectedPatient?.encounters, tree])
  const filteredPatients = useMemo(() => {
    const text = keyword.trim().toLowerCase()
    if (!text) return patients
    return patients.filter((patient) =>
      patient.name.toLowerCase().includes(text) || patient.id.toLowerCase().includes(text),
    )
  }, [keyword, patients])

  const handleSelect = useCallback((id: string) => {
    selectPatient(id)
    setExpandedPatients(new Set([id]))
    setExpandedEncounters(new Set())
    setExpandedReports(new Set())
  }, [selectPatient])

  const toggleSet = useCallback((setter: Dispatch<SetStateAction<Set<string>>>, key: string) => {
    setter((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  return (
    <aside className="left-panel">
      <div className="sidebar-body">
        <button className="consult-entry" type="button" onClick={() => message.info('请在中间对话框发送分析请求')}>
          <span className="consult-icon" aria-hidden="true">
            <img src="/aidoc/icon-consult.png" alt="" width="28" height="28" />
          </span>
          <span>AI问诊</span>
        </button>

        <div className="patient-toolbar">
          <span>患者管理</span>
          <AddPatientButton />
        </div>

        <label className="search-wrap">
          <SearchIcon />
          <input
            className="search-input"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索患者ID/姓名"
          />
        </label>

        <div className="patient-tree-list">
          {filteredPatients.length === 0 && <div className="tree-empty">暂无患者数据</div>}
          {filteredPatients.map((patient) => {
            const active = patient.id === selectedId
            const expanded = expandedPatients.has(patient.id)
            return (
              <div className="patient-item" key={patient.id}>
                <div className="patient-row">
                  <button
                    className={`tree-node patient-node ${active ? 'is-active' : ''}`}
                    type="button"
                    onClick={() => {
                      if (active) {
                        toggleSet(setExpandedPatients, patient.id)
                      } else {
                        handleSelect(patient.id)
                      }
                    }}
                  >
                    <ChevronIcon expanded={expanded} />
                    <PatientIcon />
                    <span className="tree-label">{patient.name}</span>
                  </button>
                  <button
                    className="patient-delete-btn"
                    type="button"
                    disabled={patients.length <= 1}
                    title="从当前列表移除"
                    onClick={(event) => {
                      event.stopPropagation()
                      removePatient(patient.id)
                    }}
                  >
                    <TrashIcon />
                  </button>
                </div>

                {active && expanded && encounterList.map((encounter) => {
                  const encounterKey = `${patient.id}:${encounter.name}`
                  const encounterExpanded = expandedEncounters.has(encounterKey)
                  const encounterActive = encounter.reports?.some((report: FileTreeReport) =>
                    report.files.some((file) => file.name === selectedFile),
                  )
                  return (
                    <div className="encounter-item" key={encounterKey}>
                      <button
                        className={`tree-node encounter-node ${encounterActive ? 'is-active' : ''}`}
                        type="button"
                        onClick={() => toggleSet(setExpandedEncounters, encounterKey)}
                      >
                        <ChevronIcon expanded={encounterExpanded} />
                        <CalendarIcon />
                        <span className="tree-label">{encounter.name}</span>
                      </button>
                      {encounterExpanded && encounter.reports?.map((report: FileTreeReport) => {
                        const reportKey = `${encounterKey}:${report.name}`
                        const reportExpanded = expandedReports.has(reportKey)
                        const reportActive = report.files.some((file) => file.name === selectedFile)
                        return (
                          <div className="report-item" key={reportKey}>
                            <button
                              className={`tree-node report-node ${reportActive ? 'is-active' : ''}`}
                              type="button"
                              onClick={() => toggleSet(setExpandedReports, reportKey)}
                            >
                              <ChevronIcon expanded={reportExpanded} />
                              <ReportIcon name={report.name} />
                              <span className="tree-label">{report.name}</span>
                            </button>
                            {reportExpanded && report.files.map((file) => (
                              <button
                                className={`tree-node file-node ${selectedFile === file.name ? 'is-active' : ''}`}
                                key={file.name}
                                type="button"
                                title={file.name}
                                onClick={() => setSelectedFile(file.name)}
                              >
                                <PdfIcon />
                                <span className="tree-label file-label">{formatFileLabel(file.name)}</span>
                              </button>
                            ))}
                          </div>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>

        <div className="sidebar-logos" aria-label="合作机构标识">
          <div className="sidebar-logo-row">
            <img className="sidebar-logo-mark" src="/aidoc/ui-svg-06.svg" alt="广州呼吸健康研究院标识" />
            <div className="sidebar-logo-texts">
              <img className="sidebar-logo-cn" src="/aidoc/ui-svg-07.svg" alt="广州呼吸健康研究院" />
              <img className="sidebar-logo-en" src="/aidoc/ui-svg-08.svg" alt="GUANGZHOU INSTITUTE OF RESPIRATORY HEALTH" />
            </div>
          </div>
          <div className="sidebar-logo-row">
            <img className="sidebar-logo-mark" src="/aidoc/ui-svg-09.svg" alt="广州医科大学附属第一医院标识" />
            <div className="sidebar-logo-texts">
              <img className="sidebar-logo-cn" src="/aidoc/ui-svg-10.svg" alt="广州医科大学附属第一医院" />
              <img className="sidebar-logo-en" src="/aidoc/ui-svg-11.svg" alt="THE FIRST AFFILIATED HOSPITAL OF GUANGZHOU MEDICAL UNIVERSITY" />
            </div>
          </div>
          <div className="sidebar-logo-row">
            <img className="sidebar-logo-mark" src="/aidoc/ui-svg-12.svg" alt="广州实验室标识" />
            <div className="sidebar-logo-texts">
              <img className="sidebar-logo-cn" src="/aidoc/ui-svg-13.svg" alt="广州实验室" />
              <img className="sidebar-logo-en sidebar-logo-en-short" src="/aidoc/ui-svg-14.svg" alt="Guangzhou Laboratory" />
            </div>
          </div>
        </div>
      </div>
    </aside>
  )
}
