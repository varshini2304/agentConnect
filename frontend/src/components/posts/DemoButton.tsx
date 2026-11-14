import { useState } from 'react'
import { LoaderCircle, Play } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { getPost, runDemo } from '../../api/posts'
import { apiErrorMessage } from '../../api/client'
import { Button } from '../common/UI'

export function DemoButton({ compact = false }: { compact?: boolean }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const start = async () => {
    setBusy(true); setError('')
    try {
      const result = await runDemo()
      const detail = await getPost(result.post.id)
      const missingKey = detail.interactions.some(item => item.status === 'failed' && item.error?.startsWith('missing_api_key:'))
      navigate(`/posts/${detail.id}`, { state: { demo: true, created: result.created, missingKey } })
    } catch (reason) { setError(apiErrorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <div className="demo-control"><Button className={compact ? 'button-small' : 'button-primary'} disabled={busy} onClick={start}>{busy ? <LoaderCircle className="spin" size={16} /> : <Play size={16} fill="currentColor" />}<span>{busy ? 'Running workflow…' : 'Run Diwali demo'}</span></Button>{error && <span className="inline-error">{error}</span>}</div>
}
