import { APP_NAME, LOGO } from '../lib/brand'

/** Logo Sirius + nome: nella barra laterale (small) e nelle pagine di accesso (grande). */
export default function Brand({ size = 'small', tagline }: { size?: 'small' | 'large'; tagline?: string }) {
  return (
    <span className={`brand-mark ${size}`}>
      <img src={LOGO} alt="Sirius" className="brand-logo" />
      <span className="brand-name">{APP_NAME}</span>
      {tagline && <small className="muted brand-tagline">{tagline}</small>}
    </span>
  )
}
