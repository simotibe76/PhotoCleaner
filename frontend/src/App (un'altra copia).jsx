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

const SUSPECT_CATEGORIES = [
  ['whatsapp', 'WHATSAPP'],
  ['screenshot', 'SCREENSHOT'],
  ['piccola_senza_exif', 'PICCOLE SENZA EXIF'],
]

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
  const [view, setView] = useState('groups')
  const [sus, setSus] = useState({ items: [], total: 0 })
  const [susSummary, setSusSummary] = useState(null)
  const [susCategory, setSusCategory] = useState('whatsapp')
  const [susLoading, setSusLoading] = useState(false)
  const [selected, setSelected] = useState({})
  const [quarantine, setQuarantine] = useState({ count: 0, size_bytes: 0, items: [] })
  const [busy, setBusy] = useState(false)
  const [info, setInfo] = useState('')

  useEffect(() => {
    fetch(`${API}/api/status`)
      .then(response => response.json())
      .then(data => setStatus(`${data.app} ${data.version} — ${data.status}`))
      .catch(() => setStatus('Backend non raggiungibile'))
  }, [])

  useEffect(() => {
    loadQuarantine()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!result) return
    if (view === 'suspects') loadSuspects(susCategory)
    if (view === 'quarantine') loadQuarantine()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, susCategory, result])

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
        setSelected({})
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
    setInfo('')
    setResult(null)
    setDecisions({})
    setSelected({})
    setSusSummary(null)
    setSus({ items: [], total: 0 })
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

  async function loadSuspects(category, append = false) {
    if (!result) return
    setSusLoading(true)
    setError('')
    try {
      const offset = append ? sus.items.length : 0
      const url = `${API}/api/suspects?path=${encodeURIComponent(result.path)}&category=${category}&offset=${offset}&limit=120`
      const response = await fetch(url)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Caricamento dei sospetti non riuscito')
      setSus(previous => ({ items: append ? [...previous.items, ...data.items] : data.items, total: data.total }))
      setSusSummary(data.summary)
    } catch (err) {
      setError(err.message || 'Errore nel caricamento dei sospetti')
    } finally {
      setSusLoading(false)
    }
  }

  async function loadQuarantine() {
    try {
      const response = await fetch(`${API}/api/quarantine`)
      const data = await response.json()
      if (response.ok) setQuarantine(data)
    } catch {
      // backend non raggiungibile: lo stato è già mostrato in alto
    }
  }

  function toggleSelected(file) {
    if (decisions[file.path] === 'keep') return
    setSelected(previous => {
      const next = { ...previous }
      if (next[file.path]) delete next[file.path]
      else next[file.path] = true
      return next
    })
  }

  function markKeep(file) {
    setDecision(file.path, 'keep')
    setSelected(previous => {
      const next = { ...previous }
      delete next[file.path]
      return next
    })
  }

  function selectVisible() {
    const next = {}
    sus.items.forEach(file => {
      if (decisions[file.path] !== 'keep') next[file.path] = true
    })
    setSelected(next)
  }

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Operazione non riuscita')
    return data
  }

  async function moveToQuarantine() {
    const paths = Object.keys(selected).filter(path => decisions[path] !== 'keep')
    if (!paths.length || !result) return
    const message = `Spostare ${paths.length} file in quarantena?\n\nNon vengono cancellati: restano in data/quarantena e puoi ripristinarli.`
    if (!window.confirm(message)) return
    setBusy(true)
    setError('')
    setInfo('')
    try {
      const data = await postJson(`${API}/api/quarantine`, { root: result.path, paths })
      const failed = data.failed.length ? `, ${data.failed.length} non riusciti` : ''
      setInfo(`${data.moved} file spostati in quarantena${failed}.`)
      setSelected({})
      await loadSuspects(susCategory)
      await loadQuarantine()
    } catch (err) {
      setError(err.message || 'Errore durante lo spostamento')
    } finally {
      setBusy(false)
    }
  }

  async function restore(ids, all = false) {
    if (all && !window.confirm('Ripristinare tutti i file della quarantena nella posizione originale?')) return
    setBusy(true)
    setError('')
    setInfo('')
    try {
      const data = await postJson(`${API}/api/quarantine/restore`, { ids, all })
      const failed = data.failed.length ? `, ${data.failed.length} non riusciti` : ''
      setInfo(`${data.restored} file ripristinati${failed}. Riavvia la scansione per rivederli tra i sospetti.`)
      await loadQuarantine()
    } catch (err) {
      setError(err.message || 'Errore durante il ripristino')
    } finally {
      setBusy(false)
    }
  }

  const counts = susSummary || result?.suspects_summary || {}
  const suspectTotal = Object.values(counts).reduce((sum, entry) => sum + entry.count, 0)
  const selectedCount = Object.keys(selected).filter(path => decisions[path] !== 'keep').length
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
            <div className="tabs">
              <button className={`tab ${view === 'groups' ? 'active' : ''}`} onClick={() => setView('groups')}>CONFRONTO VISIVO</button>
              <button className={`tab ${view === 'suspects' ? 'active' : ''}`} onClick={() => setView('suspects')} disabled={!result}>
                SOSPETTI{result ? ` (${suspectTotal})` : ''}
              </button>
              <button className={`tab ${view === 'quarantine' ? 'active' : ''}`} onClick={() => setView('quarantine')}>
                QUARANTENA ({quarantine.count})
              </button>
            </div>
            <span className="backend-status">{status}</span>
          </div>

          {!result && view !== 'quarantine' && (
            <div className="empty">
              <div className="scan-icon">⌕</div>
              <h2>{scanning ? 'Scansione della libreria in corso...' : 'Nessuna scansione eseguita'}</h2>
              <p>{scanning
                ? 'PhotoCleaner sta leggendo i file. Non verrà modificato nulla.'
                : 'Seleziona una cartella e avvia la scansione. I gruppi suggeriti serviranno solo a individuare le immagini da confrontare.'}</p>
            </div>
          )}

          {result && view === 'groups' && groups.length === 0 && (
            <div className="empty">
              <div className="scan-icon">✓</div>
              <h2>Scansione completata</h2>
              <p>Non sono stati trovati gruppi candidati in base ai nomi. Le foto non sono state modificate.</p>
            </div>
          )}

          {result && view === 'groups' && groups.length > 0 && (
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

          {result && view === 'suspects' && (
            <div className="suspects">
              <div className="suspect-toolbar">
                <div className="button-group">
                  {SUSPECT_CATEGORIES.map(([key, label]) => (
                    <button
                      key={key}
                      className={`tab ${susCategory === key ? 'active' : ''}`}
                      onClick={() => { setSusCategory(key); setSelected({}) }}
                    >
                      {label} ({counts[key]?.count ?? 0})
                    </button>
                  ))}
                </div>
                <div className="button-group">
                  <button onClick={selectVisible} disabled={busy || !sus.items.length}>SELEZIONA VISIBILI</button>
                  <button onClick={() => setSelected({})} disabled={!selectedCount}>DESELEZIONA</button>
                  <button className="danger" onClick={moveToQuarantine} disabled={busy || !selectedCount}>
                    {busy ? 'SPOSTAMENTO...' : `SPOSTA IN QUARANTENA (${selectedCount})`}
                  </button>
                </div>
              </div>
              {info && <p className="info-message">{info}</p>}
              <p className="notice">
                Sono suggerimenti, non certezze: WhatsApp contiene anche foto vere. Le foto segnate DA TENERE non vengono mai spostate.
                {counts[susCategory] ? ` Categoria: ${formatBytes(counts[susCategory].size_bytes)} in totale.` : ''}
              </p>

              {!susLoading && sus.items.length === 0 && (
                <div className="empty compact"><h2>Nessun file in questa categoria</h2></div>
              )}
              <div className="photo-grid compact">
                {sus.items.map(file => {
                  const isSelected = Boolean(selected[file.path])
                  const isKeep = decisions[file.path] === 'keep'
                  return (
                    <article className={`photo-card ${isSelected ? 'selected' : ''}`} key={file.path}>
                      <div className="photo-preview" onClick={() => toggleSelected(file)}>
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
                        <div className="hint-tag">{file.reasons.join(' · ')}</div>
                        <div className="decision-buttons">
                          <button className={isSelected ? 'decision-active remove' : ''} onClick={() => toggleSelected(file)}>
                            {isSelected ? '✓ SELEZIONATA' : 'SELEZIONA'}
                          </button>
                          <button className={isKeep ? 'decision-active keep' : ''} onClick={() => markKeep(file)}>
                            {isKeep ? '✓ DA TENERE' : 'DA TENERE'}
                          </button>
                        </div>
                      </div>
                    </article>
                  )
                })}
              </div>
              {sus.items.length < sus.total && (
                <button className="show-more" onClick={() => loadSuspects(susCategory, true)} disabled={susLoading}>
                  {susLoading ? 'CARICAMENTO...' : `CARICA ALTRI (${sus.total - sus.items.length})`}
                </button>
              )}
            </div>
          )}

          {view === 'quarantine' && (
            <div className="suspects">
              <div className="suspect-toolbar">
                <span className="backend-status">{quarantine.count} file in quarantena · {formatBytes(quarantine.size_bytes)}</span>
                <button onClick={() => restore([], true)} disabled={busy || !quarantine.count}>RIPRISTINA TUTTO</button>
              </div>
              {info && <p className="info-message">{info}</p>}
              <p className="notice">I file sono nella cartella data/quarantena del progetto, con la stessa struttura di cartelle. Per cancellarli davvero, elimina quella cartella a mano quando sei sicuro.</p>
              {quarantine.items.map(item => (
                <div className="quarantine-row" key={item.id}>
                  <span title={item.relative_path}>{item.relative_path}</span>
                  <button onClick={() => restore([item.id])} disabled={busy}>RIPRISTINA</button>
                </div>
              ))}
              {quarantine.count > quarantine.items.length && (
                <p className="relative-path">Mostrati i {quarantine.items.length} più recenti.</p>
              )}
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
          <p className="read-only-note">NESSUN FILE VIENE CANCELLATO DEFINITIVAMENTE — la quarantena è reversibile. Le scelte DA TENERE e RICONTROLLARE restano solo in questa schermata.</p>
        )}
      </main>

      <footer>
        <span>PHOTO CLEANER v0.4.0</span>
        <span>LOCAL MODE · NO CLOUD</span>
      </footer>
    </div>
  )
}

export default App
