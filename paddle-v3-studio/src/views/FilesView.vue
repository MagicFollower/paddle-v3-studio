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
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
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
  { key: 'name', label: '文件名', minWidth: 200 },
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

async function fetchEntries() {
  loading.value = true
  try {
    const r = await api.entries(buildParams())
    data.value = r.items
    total.value = r.total
  } catch (e) { ElMessage.error(e.message) } finally { loading.value = false }
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
</script>

<style scoped>
.files-view { display: flex; flex-direction: column; gap: 10px; height: 100%; }
.files-toolbar { display: flex; align-items: center; gap: 12px; }
</style>