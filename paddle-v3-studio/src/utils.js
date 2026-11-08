export function bboxStyle(bboxNorm) {
  if (!bboxNorm) return { display: 'none' }
  const [x0, y0, x1, y1] = bboxNorm
  return {
    left: `${x0 / 10}%`, top: `${y0 / 10}%`,
    width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%`,
  }
}

export function polyStyle(poly, width, height) {
  if (!poly || !width || !height) return { display: 'none' }
  const xs = poly.map(p => p[0]), ys = poly.map(p => p[1])
  const x0 = Math.min(...xs), y0 = Math.min(...ys)
  const x1 = Math.max(...xs), y1 = Math.max(...ys)
  return {
    left: `${x0 / width * 100}%`, top: `${y0 / height * 100}%`,
    width: `${(x1 - x0) / width * 100}%`, height: `${(y1 - y0) / height * 100}%`,
  }
}

export const TIER_LABEL = { high: '高置信', review: '需复核', low: '低置信', none: '无置信度' }
export const VERIFY_LABEL = {
  matched: '校验通过', mismatch: '存在不符', not_found: '合同号不存在',
  no_number: '未识别到合同号', source_unreachable: '数据源不可达', pending: '待校验',
}
export const VERIFY_TYPE = {
  matched: 'success', mismatch: 'danger', not_found: 'warning',
  no_number: 'warning', source_unreachable: 'info', pending: 'info',
}

export function formatBytes(n) {
  if (n == null) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

// ===== 合同明细二次解析归一化 =====
// 去除文本中的全部空白字符（空格/制表/换行），如「办公耗材 批次001」→「办公耗材批次001」
export function cleanText(s) {
  return s == null ? '' : String(s).replace(/\s+/g, '')
}
// 数值通用转换：移除千分位逗号与空白（1,000,0000→10000000）；
// 小数点后冗余 0 去除（480.00→480、63.50→63.5）；非纯数值则退回去空白文本
export function cleanNumber(v) {
  if (v == null || v === '') return null
  let s = String(v).replace(/[,，\s]/g, '')
  if (!/^-?\d+(\.\d+)?$/.test(s)) return cleanText(s)
  if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '')
  return s === '' || s === '-' ? null : Number(s)
}
// 回填特殊标记字段（二次处理后可写入 JSON 的审核信息）
export const REVIEW_FIELDS = [
  { key: 'firstReviewer', label: '初审核人' },
  { key: 'firstReviewTime', label: '初审核时间' },
  { key: 'firstRemark', label: '初审备注' },
  { key: 'reviewer', label: '审核人' },
  { key: 'reviewTime', label: '审核时间' },
  { key: 'reviewRemark', label: '审核备注' },
]
export function hasReview(r) {
  return !!r && REVIEW_FIELDS.some(f => r[f.key] != null && r[f.key] !== '')
}