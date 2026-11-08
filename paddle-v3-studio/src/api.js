const BASE = ''

async function req(method, path, body, isForm = false) {
  const opt = { method, headers: {} }
  if (body !== undefined) {
    if (isForm) opt.body = body
    else { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body) }
  }
  const r = await fetch(BASE + path, opt)
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try { const j = await r.json(); msg = j.error?.message || j.detail || msg } catch {}
    const e = new Error(msg); e.status = r.status; throw e
  }
  const ct = r.headers.get('content-type') || ''
  return ct.includes('json') ? r.json() : r.text()
}

export const api = {
  health: () => req('GET', '/api/health'),
  overview: () => req('GET', '/api/overview'),
  modelStatus: () => req('GET', '/api/model/status'),
  reprobe: () => req('POST', '/api/model/reprobe', {}),
  schema: () => req('GET', '/api/schema'),
  config: () => req('GET', '/api/config'),
  saveConfig: (patch) => req('POST', '/api/config', patch),
  documents: (q = '', status = '') => req('GET', `/api/documents?q=${encodeURIComponent(q)}&status=${status}`),
  uploadImage: (file) => { const f = new FormData(); f.append('file', file); return req('POST', '/api/documents', f, true) },
  document: (id) => req('GET', `/api/documents/${id}`),
  result: (id) => req('GET', `/api/documents/${id}/result`),
  raw: (id) => req('GET', `/api/documents/${id}/raw`),
  deleteDoc: (id) => req('DELETE', `/api/documents/${id}`),
  favorite: (id, on) => req('POST', `/api/documents/${id}/favorite`, { on }),
  parse: (docId) => req('POST', '/api/parse', { docId }),
  jobs: (refId = '') => req('GET', `/api/jobs?refId=${encodeURIComponent(refId)}`),
  job: (id) => req('GET', `/api/jobs/${id}`),
  contracts: () => req('GET', '/api/contracts'),
  uploadContract: (file) => { const f = new FormData(); f.append('file', file); return req('POST', '/api/contracts/upload', f, true) },
  contract: (id) => req('GET', `/api/contracts/${id}`),
  contractResult: (id) => req('GET', `/api/contracts/${id}/result`),
  deleteContract: (id) => req('DELETE', `/api/contracts/${id}`),
  reparseContract: (id) => req('POST', `/api/contracts/${id}/parse`, {}),
  reverify: (id) => req('POST', `/api/contracts/${id}/reverify`, {}),
  sourceStatus: () => req('GET', '/api/source/status'),
  imageUrl: (id) => `${BASE}/api/documents/${id}/image`,
  contractPageUrl: (id, n) => `${BASE}/api/contracts/${id}/pages/${n}/image`,
}