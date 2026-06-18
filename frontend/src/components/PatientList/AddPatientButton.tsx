import { message } from 'antd'

function AddIcon() {
  return (
    <svg viewBox="0 0 16 16" focusable="false" aria-hidden="true">
      <path d="M8 3v10M3 8h10" />
    </svg>
  )
}

export default function AddPatientButton() {
  return (
    <button
      className="sidebar-add-btn"
      type="button"
      aria-label="上传文件夹或文件"
      onClick={() => message.info('Demo 阶段：请直接将患者文件夹复制到 TempData/patients/ 目录')}
    >
      <AddIcon />
    </button>
  )
}
