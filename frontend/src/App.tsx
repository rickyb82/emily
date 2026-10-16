import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './lib/auth'
import Login from './pages/Login'
import KidLogin from './pages/KidLogin'
import Enroll from './pages/Enroll'
import Reset from './pages/Reset'
import Shell from './components/Shell'
import Chat from './pages/Chat'
import Projects from './pages/Projects'
import Admin from './pages/Admin'
import Settings from './pages/Settings'
import Documents from './pages/Documents'
import Editor from './pages/Editor'
import Mail from './pages/Mail'
import Remote from './pages/Remote'
import Cover from './pages/Cover'
import Quote from './pages/Quote'

export default function App() {
  const { me, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <div className="center muted">Caricamento…</div>

  if (!me) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/kids" element={<KidLogin />} />
        <Route path="/forgot" element={<Reset />} />
        <Route path="/reset" element={<Reset />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: loc.pathname }} />} />
      </Routes>
    )
  }
  // adulto loggato con password ma senza passkey verificata/registrata
  if (me.mfa_required) {
    return (
      <Routes>
        <Route path="/reset" element={<Reset />} />
        <Route path="/enroll" element={<Enroll />} />
        <Route path="*" element={<Navigate to="/enroll" replace />} />
      </Routes>
    )
  }
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Chat />} />
        <Route path="/c/:id" element={<Chat />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/:id" element={<Projects />} />
        {me.user.role !== 'child' && <Route path="/settings" element={<Settings />} />}
        {me.user.role !== 'child' && <Route path="/documents" element={<Documents />} />}
        {me.user.role !== 'child' && <Route path="/editor" element={<Editor />} />}
        {me.user.role !== 'child' && <Route path="/mail" element={<Mail />} />}
        {me.user.role !== 'child' && <Route path="/remote" element={<Remote />} />}
        {me.user.role !== 'child' && <Route path="/cover" element={<Cover />} />}
        {me.user.role !== 'child' && <Route path="/quotes" element={<Quote />} />}
        {me.user.role === 'admin' && <Route path="/admin/*" element={<Admin />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
