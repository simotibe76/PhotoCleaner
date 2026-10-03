import { useEffect, useState } from 'react'
import './App.css'

const API = 'http://127.0.0.1:8000'

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return 'Peso non disponibile'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function formatResolution(file) {
  return file.width && file.height ? `${file.width} × ${file.height}` : 'Risoluzione non disponibile'
}

function previewUrl(file, root) {
  return `${API}/api/preview?path=${encodeURIComponent(file.path)}&root=${encodeURIComponent(root)}`
}

function App() {
  const [status, setStatus] = useState('Connessione...')
  const [folder, setFolder] = useState('')
  const [selecting, setSelecting] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [activeGroup, setActiveGroup] = useState(0)
  const [decisions, setDecisions] = useState({})
  const [showAllGroups, setShowAllGroups] = useState(false)

  useEffect(() => {
    fetch(`${API}/api/status`)
      .then(response => response.json())
      .then(data => setStatus(`${data.app} ${data.version} — ${data.status}`))
      .catch(() => setStatus('Backend non raggiungibile'))
  }, [])

  async function selectFolder() {
    setSelecting(true)
    setError('')
    try {
      const response = await fetch(`${API}/api/select-folder`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Selezione cartella non riuscita')
      if (data.selected) {
        setFolder(data.path)
        setResult(null)
        setDecisions({})
        setActiveGroup(0)
      }
    } catch (err) {
      setError(err.message || 'Errore durante la selezione della cartella')
    } finally {
      setSelecting(false)
    }
  }

  async function scanFolder() {
    if (!folder) return
    setScanning(true)
    setError('')
    setResult(null)
    setDecisions({})
    setActiveGroup(0)
    try {
      const response = await fetch(`${API}/api/scan?path=${encodeURIComponent(folder)}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Scansione non riuscita')
      setResult(data)
    } catch (err) {
      setError(err.message || 'Errore durante la scansione')
    } finally {
      setScanning(false)
    }
  }

  function setDecision(path, decision) {
    setDecisions(previous => {
      const next = { ...previous }
      if (next[path] === decision) delete next[path]
      else next[path] = decision
      return next
    })
  }

  const groups = result?.groups || []
  const visibleGroups = showAllGroups ? groups : groups.slice(0, 30)
  const group = visibleGroups[activeGroup] || null
  const keepCount = Object.values(decisions).filter(value => value === 'keep').length
  const reviewCount = Object.keys(decisions).length

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>PHOTO<span>CLEANER</span></h1>
          <p>Analizzatore locale della libreria fotografica</p>
        </div>
        <div className="online"><i />ONLINE</div>
      </header>

      <main>
        <section className="folder-panel">
          <div className="panel-title">CARTELLA ANALIZZATA</div>
          <div className="folder-path">{folder || 'Nessuna cartella selezionata'}</div>
          <div className="buttons">
            <button onClick={selectFolder} disabled={selecting || scanning}>
              {selecting ? 'SELEZIONE...' : 'SELEZIONA CARTELLA'}
            </button>
            <button className="primary" onClick={scanFolder} disabled={!folder || scanning || selecting}>
              {scanning ? 'SCANSIONE IN CORSO...' : 'AVVIA SCANSIONE'}
            </button>
          </div>
          {error && <div className="error-message">{error}</div>}
        </section>

        <section className="stats">
          <div className="stat"><span className="label">FOTO</span><strong>{result?.photos ?? '—'}</strong></div>
          <div className="stat"><span className="label">VIDEO</span><strong>{result?.videos ?? '—'}</strong></div>
          <div className="stat"><span className="label">JSON</span><strong>{result?.json ?? '—'}</strong></div>
          <div className="stat"><span className="label">GRUPPI DA CONTROLLARE</span><strong>{result?.groups_count ?? '—'}</strong></div>
        </section>

        <section className="analysis">
          <div className="analysis-header">
            <span>CONFRONTO VISIVO</span>
            <span className="backend-status">{status}</span>
          </div>

          {!result && (
            <div className="empty">
              <div className="scan-icon">⌕</div>
              <h2>{scanning ? 'Scansione della libreria in corso...' : 'Nessuna scansione eseguita'}</h2>
              <p>{scanning
                ? 'PhotoCleaner sta leggendo i file. Non verrà modificato nulla.'
                : 'Seleziona una cartella e avvia la scansione. I gruppi suggeriti serviranno solo a individuare le immagini da confrontare.'}</p>
            </div>
          )}

          {result && groups.length === 0 && (
            <div className="empty">
              <div className="scan-icon">✓</div>
              <h2>Scansione completata</h2>
              <p>Non sono stati trovati gruppi candidati in base ai nomi. Le foto non sono state modificate.</p>
            </div>
          )}

          {result && groups.length > 0 && (
            <div className="review-layout">
              <aside className="group-sidebar">
                <div className="sidebar-heading">GRUPPI CANDIDATI <span>{groups.length}</span></div>
                {visibleGroups.map((item, index) => (
                  <button
                    key={`${item.id}-${index}`}
                    className={`group-button ${index === activeGroup ? 'selected' : ''}`}
                    onClick={() => setActiveGroup(index)}
                  >
                    <span className="group-name">{item.label}</span>
                    <span className="group-meta">{item.count} file</span>
                  </button>
                ))}
                {groups.length > 30 && (
                  <button className="show-more" onClick={() => setShowAllGroups(value => !value)}>
                    {showAllGroups ? 'MOSTRA MENO' : `MOSTRA TUTTI (${groups.length})`}
                  </button>
                )}
              </aside>

              <div className="comparison">
                {group ? (
                  <>
                    <div className="comparison-title">
                      <div>
                        <h2>{group.label}</h2>
                        <p>{group.note}</p>
                      </div>
                      <span className="candidate-count">{group.count} FILE</span>
                    </div>
                    <div className="photo-grid">
                      {group.files.map(file => (
                        <article className="photo-card" key={file.path}>
                          <div className="photo-preview">
                            {file.type === 'photo' ? (
                              <img
                                src={previewUrl(file, result.path)}
                                alt={file.filename}
                                loading="lazy"
                                onError={event => {
                                  event.currentTarget.style.display = 'none'
                                  event.currentTarget.parentElement.classList.add('preview-unavailable')
                                }}
                              />
                            ) : (
                              <div className="preview-placeholder"><span>▶</span><small>VIDEO</small></div>
                            )}
                            <span className="type-tag">{file.type === 'photo' ? 'FOTO' : 'VIDEO'}</span>
                          </div>
                          <div className="photo-info">
                            <h3 title={file.filename}>{file.filename}</h3>
                            <p className="relative-path" title={file.relative_path}>{file.relative_path}</p>
                            <div className="detail-row"><span>Risoluzione</span><strong>{formatResolution(file)}</strong></div>
                            <div className="detail-row"><span>Dimensione</span><strong>{formatBytes(file.size_bytes)}</strong></div>
                            <div className="detail-row"><span>Data EXIF</span><strong>{file.taken_at || 'Non disponibile'}</strong></div>
                            <div className="detail-row"><span>GPS</span><strong className={file.gps ? 'gps-yes' : ''}>{file.gps ? 'Presente' : 'Non rilevato'}</strong></div>
                            <div className="hint-tag">{file.hint || 'da confrontare'}</div>
                            <div className="decision-buttons">
                              <button className={decisions[file.path] === 'keep' ? 'decision-active keep' : ''} onClick={() => setDecision(file.path, 'keep')}>
                                {decisions[file.path] === 'keep' ? '✓ DA TENERE' : 'DA TENERE'}
                              </button>
                              <button className={decisions[file.path] === 'review' ? 'decision-active review' : ''} onClick={() => setDecision(file.path, 'review')}>
                                {decisions[file.path] === 'review' ? '✓ RICONTROLLARE' : 'RICONTROLLARE'}
                              </button>
                            </div>
                          </div>
                        </article>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="empty compact"><h2>Seleziona un gruppo</h2></div>
                )}
              </div>
            </div>
          )}
        </section>

        <section className="categories">
          <div><span>JSON ORFANI</span><strong>{result?.orphan_json ?? '—'}</strong></div>
          <div><span>MEDIA SENZA JSON</span><strong>{result?.media_without_json ?? '—'}</strong></div>
          <div><span>SCELTI DA TENERE</span><strong>{keepCount}</strong></div>
          <div><span>CONTRASSEGNATI</span><strong>{reviewCount}</strong></div>
        </section>

        {result && !result.pillow_available && (
          <p className="notice">Per leggere risoluzione e GPS, PhotoCleaner ha bisogno di Pillow. Le anteprime possono comunque funzionare per i formati supportati dal browser.</p>
        )}
        {result && (
          <p className="read-only-note">MODALITÀ SOLA LETTURA — le scelte sono temporanee e restano in questa schermata. Nessun file viene cancellato o spostato.</p>
        )}
      </main>

      <footer>
        <span>PHOTO CLEANER v0.2.0</span>
        <span>LOCAL MODE · NO CLOUD · READ ONLY</span>
      </footer>
    </div>
  )
}

export default App
