import { reactive } from 'vue'
import { api } from './api.js'

export const DEFAULT_COLORS = {
  contract_no: '#dc2626',
  contract_table: '#7c3aed',
  layout: '#2563eb',
  ocr_high: '#16a34a',
  ocr_review: '#d97706',
  ocr_low: '#dc2626',
  match_ok: '#16a34a',
  match_bad: '#dc2626',
}

const VAR_MAP = {
  contract_no: '--contract-no-box',
  contract_table: '--table-box',
  layout: '--layout-box',
  ocr_high: '--high',
  ocr_review: '--review',
  ocr_low: '--low',
  match_ok: '--match-ok',
  match_bad: '--match-bad',
}

export const display = reactive({
  show_contract_no: true,
  show_contract_table: true,
  show_layout: false,
  show_ocr: false,
  colors: { ...DEFAULT_COLORS },
})

export function applyColors(colors) {
  for (const [k, v] of Object.entries(colors || {})) {
    const name = VAR_MAP[k]
    if (name && v) document.documentElement.style.setProperty(name, v)
  }
}

export async function loadDisplay() {
  try {
    const cfg = await api.config()
    const d = cfg.display
    if (d) {
      display.show_contract_no = d.show_contract_no
      display.show_contract_table = d.show_contract_table
      display.show_layout = d.show_layout
      display.show_ocr = d.show_ocr
      display.colors = { ...DEFAULT_COLORS, ...(d.colors || {}) }
      applyColors(display.colors)
    }
  } catch {}
}

// 界面快捷开关：即时更新 UI 并持久化到 data/config.json
export async function setDisplay(key, val) {
  display[key] = val
  try { await api.saveConfig({ display: { [key]: val } }) } catch {}
}