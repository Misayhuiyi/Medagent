export default function TopBar() {
  return (
    <div className="topbar">
      <div className="aidoc-brand" aria-label="AI Doctor">
        <span className="aidoc-logo-crop" aria-hidden="true">
          <img src="/aidoc/aidoc-tip.svg" alt="" />
        </span>
        <span className="aidoc-brand-badge">智能体</span>
      </div>
    </div>
  )
}
