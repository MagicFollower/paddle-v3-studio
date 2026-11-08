<template>
  <div class="files-view">
    <QueryBuilder v-model="query" :fields="queryFields" @search="onSearch" @reset="onReset" />
    <div class="files-toolbar">
      <el-upload :show-file-list="false" :http-request="doUpload" multiple
        accept=".png,.jpg,.jpeg,.bmp,.webp,.docx,.doc,.pdf">
        <el-button type="primary" :icon="Upload" :loading="uploading" :disabled="uploading">上传文件</el-button>
      </el-upload>
      <span class="muted">支持图片 png/jpg/bmp/webp 与合同 docx/doc/pdf，上传后自动解析</span>
    </div>
    <ContentGrid :columns="columns" :data="data" :loading="loading" :total="total"
      v-model:page="page" v-model:page-size="pageSize" :page-sizes="[10, 15, 30, 50, 100, 200]"
      :actions="actions" :action-width="140" index @page-change="onPageChange">
      <template #name="{ row }">
        <span class="f-name">{{ row.name }}</span>
        <span v-if="row.parsing" class="parse-mark">
          <el-icon class="spin"><Loading /></el-icon>正在解析
        </span>
      </template>
      <template #type="{ row }">
        <el-tag size="small" :type="row.type === 'contract' ? 'warning' : 'info'" effect="plain">
          {{ row.type === 'contract' ? '合同' : '图片' }}
        </el-tag>
      </template>
      <template #parsed="{ row }">
        <el-tag size="small" :type="row.parsed ? 'success' : 'info'" effect="plain">
          {{ row.parsed ? '已解析' : '未解析' }}
        </el-tag>
      </template>
      <template #verify="{ row }">
        <el-tag v-if="row.verifyStatus" size="small" :type="VERIFY_TYPE[row.verifyStatus] || 'info'">
          {{ VERIFY_LABEL[row.verifyStatus] || row.verifyStatus }}
        </el-tag>
        <span v-else class="muted">—</span>
      </template>
    </ContentGrid>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Loading } from '@element-plus/icons-vue'
import { api } from '../api.js'
import { formatBytes, VERIFY_LABEL, VERIFY_TYPE } from '../utils.js'
import QueryBuilder from '../components/QueryBuilder.vue'
import ContentGrid from '../components/ContentGrid.vue'

const emit = defineEmits(['open'])

const query = ref({})
const data = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(15)
const loading = ref(false)
const uploading = ref(false)

const queryFields = [
  { key: 'uploadDate', label: '上传时间范围', type: 'daterange' },
  { key: 'q', label: '合同号（模糊）', type: 'text', placeholder: '合同号关键字' },
  { key: 'type', label: '文件类型', type: 'select', options: [
    { value: 'contract', label: '合同 docx/pdf' }, { value: 'image', label: '图片' }] },
  { key: 'parsed', label: '解析状态', type: 'select', options: [
    { value: 'true', label: '已解析' }, { value: 'false', label: '未解析' }] },
  { key: 'verify', label: '校验结果（多选）', type: 'multiselect', options: [
    { value: 'matched', label: '完全匹配的合同' },
    { value: 'mismatch', label: '不匹配条目的合同' },
    { value: 'not_found', label: '合同号不存在' },
    { value: 'no_number', label: '未识别合同号' },
    { value: 'source_unreachable', label: '数据源不可达' }] },
]

const columns = [
  { key: 'name', label: '文件名', minWidth: 200, slot: 'name', showOverflowTooltip: false },
  { key: 'ext', label: '扩展名', width: 80 },
  { key: 'size', label: '大小', width: 100, formatter: (v) => formatBytes(v) },
  { key: 'pageCount', label: '页数', width: 70, align: 'center' },
  { key: 'type', label: '类型', width: 90, slot: 'type' },
  { key: 'parsed', label: '解析状态', width: 100, slot: 'parsed' },
  { key: 'contractNo', label: '合同号', minWidth: 130,
    headerTip: '此合同号为从上传文件中 OCR 解析识别得出，非手工录入；如存在误识别，以文件原件为准。' },
  { key: 'verifyStatus', label: '校验', width: 130, slot: 'verify' },
  { key: 'uploadedAt', label: '上传时间', width: 170, formatter: (v) => v ? v.replace('T', ' ').slice(0, 19) : '—' },
]

const actions = [
  { label: '详情', type: 'primary', onClick: (row) => emit('open', { type: row.type, id: row.id }) },
  { label: '删除', type: 'danger', onClick: removeEntry },
]

function buildParams() {
  const p = { page: page.value, pageSize: pageSize.value }
  const q = query.value
  if (q.q) p.q = q.q
  if (q.type) p.type = q.type
  if (q.parsed) p.parsed = q.parsed
  if (q.verify?.length) p.verify = q.verify
  if (q.uploadDate?.length === 2) { p.dateFrom = q.uploadDate[0]; p.dateTo = q.uploadDate[1] }
  return p
}

// ===== 「正在解析」标记自动消失的轮询机制说明 =====
// 本 Grid 的数据来自后端分页接口 GET /api/entries（携带当前 page/pageSize/过滤条件）。
// 因此只要列表中仍存在 parsing=true 的条目，syncPoll 就每 2s 调一次 fetchEntries(true)，
// 也就是每 2s 向后端重发一次「分页查询」请求，并用返回结果整表替换 data：
// 解析状态与文件名后的「正在解析」标记由此跟随后端实时刷新，解析完成后标记自动消失。
// 代价：解析期间每 2s 产生一个分页请求（请求数 ≈ 解析时长 / 2s），属用简单轮询换实时性的取舍；
// 若需降低请求量，可改为轮询轻量状态接口（如 /api/queue）仅在 parsing 集合变化时才重查分页，
// 或改用 SSE/WebSocket 推送；当前实现优先保证简单与一致。
// 当所有条目解析结束（anyParsing=false）时清除定时器、停止轮询，不再发送任何请求。
let pollTimer = null
function syncPoll() {
  const anyParsing = data.value.some(d => d.parsing)
  if (anyParsing && !pollTimer) pollTimer = setInterval(() => fetchEntries(true), 2000)
  else if (!anyParsing && pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// silent=true 表示由轮询触发的静默刷新：复用同一条后端分页查询，但不置 loading，
// 避免每 2s 的轮询造成表格 loading 遮罩闪烁；手动查询/翻页/上传仍走 silent=false。
async function fetchEntries(silent = false) {
  if (!silent) loading.value = true
  try {
    const r = await api.entries(buildParams())
    data.value = r.items
    total.value = r.total
    syncPoll()
  } catch (e) { if (!silent) ElMessage.error(e.message) } finally { if (!silent) loading.value = false }
}

function onSearch(params) {
  query.value = params
  page.value = 1
  fetchEntries()
}
function onReset() { /* QueryBuilder 已清空条件；按要求不触发重查询 */ }
function onPageChange({ page: p, pageSize: s }) {
  page.value = p
  pageSize.value = s
  fetchEntries()
}

async function removeEntry(row) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.name}」？解析产物将一并清除。`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    if (row.type === 'contract') await api.deleteContract(row.id)
    else await api.deleteDoc(row.id)
    ElMessage.success('已删除')
    fetchEntries()
  } catch (e) { ElMessage.error(e.message) }
}

async function doUpload({ file }) {
  uploading.value = true
  try {
    const ext = (file.name.split('.').pop() || '').toLowerCase()
    let r
    if (['png', 'jpg', 'jpeg', 'bmp', 'webp'].includes(ext)) r = await api.uploadImage(file)
    else if (['docx', 'doc', 'pdf'].includes(ext)) r = await api.uploadContract(file)
    else { ElMessage.error(`不支持的文件类型：.${ext}`); return }
    ElMessage.success(r?.autoParsed
      ? `「${file.name}」上传成功，已开始解析`
      : `「${file.name}」上传成功（自动解析已关闭，请在详情页手动解析）`)
    fetchEntries()
  } catch (e) { ElMessage.error(e.message) } finally { uploading.value = false }
}

onMounted(fetchEntries)
onUnmounted(() => clearInterval(pollTimer))
</script>

<style scoped>
.files-view { display: flex; flex-direction: column; gap: 10px; height: 100%; }
.files-toolbar { display: flex; align-items: center; gap: 12px; }
.f-name { word-break: break-all; }
.parse-mark { display: inline-flex; align-items: center; gap: 3px; margin-left: 6px; font-size: 12px; color: var(--review); white-space: nowrap; }
.spin { animation: f-spin 1s linear infinite; }
@keyframes f-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>