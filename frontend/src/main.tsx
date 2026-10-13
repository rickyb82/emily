import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './lib/auth'
import './styles.css'

// FamilAI dentro un iframe di se stesso (es. un percorso /<app>/ che il proxy non instrada e che quindi serve questa pagina):
// mostriamo un avviso invece di annidare l'interfaccia all'infinito.
let framed = false
try { framed = window.self !== window.top && window.top!.location.origin === window.location.origin } catch { framed = false }

ReactDOM.createRoot(document.getElementById('root')!).render(
  framed ? (
    <div style={{ padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <b>Questa parte di FamilAI non è attiva.</b>
      <p>L'indirizzo <code>{window.location.pathname}</code> è arrivato all'interfaccia di FamilAI invece che all'app prevista: il container
        dell'app non è attivo o il proxy non è stato ricaricato. Dal server: <code>./familai.sh status</code> e <code>./familai.sh update</code>.</p>
    </div>
  ) : (
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
  ),
)
