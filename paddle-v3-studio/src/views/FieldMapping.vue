<template>
  <el-scrollbar height="100%">
    <div class="fm">
      <div class="panel block">
        <div class="sec-title">字段映射（中文表头 → 业务英文字段）</div>
        <div class="muted intro">
          声明目标业务字段（英文缩写 + 中文标签 + 常见中文表头别名）。合同解析的「LLM 表头→业务字段映射」阶段
          会用本地大模型把不同合同里 varied 的实际表头识别到这些字段，再确定性地把明细键名重写为英文缩写。
          <b>支持多对一</b>：一个英文字段的多个中文别名（如 itemName ← 品名/物料名称/货物名称）都会映射到它；
          同一表多列命中同一字段时非空优先合并取值。导入兼容字段中心 <span class="mono">{fields:[…]}</span>
          与扁平配对 <span class="mono">{mappings:[{from:中文,to:英文}]}</span> 两种格式（多行指向同一英文自动归并）。
        </div>
        <div class="toolbar">
          <el-button type="primary" size="small" :icon="Plus" @click="addField">添加字段</el-button>
          <el-upload :show-file-list="false" :http-request="doImport" accept=".json,application/json">
            <el-button size="small" :icon="Upload">导入JSON</el-button>
          </el-upload>
          <el-button size="small" :icon="Download" @click="exportJson">导出JSON</el-button>
          <el-button size="small" :icon="CopyDocument" @click="copyJson">复制JSON</el-button>
          <el-button size="small" :icon="RefreshLeft" @click="resetDefault">恢复默认</el-button>
          <el-button type="success" size="small" :icon="Check" :loading="saving" @click="save">保存映射</el-button>
          <span class="muted">共 {{ rows.length }} 个业务字段</span>
        </div>
      </div>

      <div class="panel block">
        <el-table :data="rows" size="small" border>
          <el-table-column label="英文缩写" width="160">
            <template #default="{ row }">
              <el-input v-model="row.field" size="small" placeholder="如 matName" class="mono" />
            </template>
          </el-table-column>
          <el-table-column label="中文标签" width="140">
            <template #default="{ row }">
              <el-input v-model="row.label" size="small" placeholder="如 品名" />
            </template>
          </el-table-column>
          <el-table-column label="中文表头别名（回车添加，点 × 删除）" min-width="320">
            <template #default="{ row }">
              <div class="alias-cell">
                <el-tag v-for="(a, ai) in row.aliases" :key="ai" size="small" closable
                  :disable-transitions="true" @close="row.aliases.splice(ai, 1)">{{ a }}</el-tag>
                <el-input v-model="row._newAlias" size="small" class="alias-input" placeholder="添加别名…"
                  @keyup.enter="addAlias(row)" />
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ $index }">
              <el-button link type="danger" size="small" :icon="Delete" @click="rows.splice($index, 1)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!rows.length" description="暂无字段，点「添加字段」或「导入JSON」" :image-size="60" />
      </div>
    </div>
  </el-scrollbar>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Upload, Download, CopyDocument, RefreshLeft, Check, Delete } from '@element-plus/icons-vue'
import { api } from '../api.js'

const rows = ref([])
const saving = ref(false)

function toRows(mapping) {
  // 兼容两种导入：字段中心 {fields:[...]} 与扁平多对一配对 {mappings:[{from,to,label}]}
  let fields = mapping?.fields
  if (!fields && Array.isArray(mapping?.mappings)) {
    const byField = {}
    for (const p of mapping.mappings) {
      const to = p.to || p.english || p.field
      if (!to) continue
      const slot = byField[to] || (byField[to] = { field: to, label: p.label || '', aliases: [] })
      if (p.label && !slot.label) slot.label = p.label
      const from = p.from || p.chinese || p.alias
      if (from && !slot.aliases.includes(from)) slot.aliases.push(from)
    }
    fields = Object.values(byField)
  }
  return (fields || []).map(f => ({
    field: f.field || '', label: f.label || '', aliases: [...(f.aliases || [])], _newAlias: '',
  }))
}
function buildMapping() {
  return { version: 1, fields: rows.value.map(r => ({ field: r.field.trim(), label: r.label.trim(), aliases: r.aliases.filter(a => a.trim()) })) }
}
function addField() {
  rows.value.push({ field: '', label: '', aliases: [], _newAlias: '' })
}
function addAlias(row) {
  const v = (row._newAlias || '').trim()
  if (v && !row.aliases.includes(v)) row.aliases.push(v)
  row._newAlias = ''
}
async function reload() {
  rows.value = toRows(await api.fieldMapping())
}
async function save() {
  saving.value = true
  try {
    const m = buildMapping()
    await api.validateFieldMapping(m)
    const saved = await api.saveFieldMapping(m)
    rows.value = toRows(saved)
    ElMessage.success('映射已保存（data/field_mapping.json）')
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}
async function doImport({ file }) {
  try {
    const data = JSON.parse(await file.text())
    await api.validateFieldMapping(data)
    rows.value = toRows(data)
    ElMessage.success('已导入映射到编辑器，点「保存映射」落盘')
  } catch (e) { ElMessage.error(`导入失败：${e.message}`) }
}
function exportJson() {
  const blob = new Blob([JSON.stringify(buildMapping(), null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'field_mapping.json'
  a.click()
  URL.revokeObjectURL(a.href)
}
async function copyJson() {
  try {
    await navigator.clipboard.writeText(JSON.stringify(buildMapping(), null, 2))
    ElMessage.success('映射 JSON 已复制')
  } catch { ElMessage.error('复制失败（浏览器不允许写剪贴板）') }
}
async function resetDefault() {
  try {
    await ElMessageBox.confirm('恢复默认映射会覆盖当前编辑器内容并落盘，确认？', '恢复默认', { type: 'warning' })
  } catch { return }
  try { rows.value = toRows(await api.resetFieldMapping()); ElMessage.success('已恢复默认映射') }
  catch (e) { ElMessage.error(e.message) }
}
onMounted(async () => { try { await reload() } catch (e) { ElMessage.error(e.message) } })
</script>

<style scoped>
.fm { max-width: 1000px; margin: 0 auto; display: flex; flex-direction: column; gap: 10px; padding-bottom: 20px; }
.block { padding: 14px 16px; }
.sec-title { font-weight: 600; margin-bottom: 8px; }
.intro { line-height: 1.7; margin-bottom: 10px; }
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.alias-cell { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.alias-input { width: 120px; }
.mono :deep(input) { font-family: Consolas, monospace; }
</style>