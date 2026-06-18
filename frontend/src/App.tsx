import './aidoc.css'
import TopBar from './components/TopBar'
import PatientList from './components/PatientList'
import ChatPanel from './components/ChatPanel'
import ReportPanel from './components/ReportPanel'

function App() {
  return (
    <div className="aidoc-stage">
      <div className="app-shell aidoc-v2">
        <TopBar />
        <main className="workspace">
          <PatientList />
          <ChatPanel />
          <ReportPanel />
        </main>
      </div>
    </div>
  )
}

export default App
