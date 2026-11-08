<template>
  <div class="queue-view">
    <QueryBuilder v-model="query" :fields="queryFields" @search="onSearch" @reset="onReset" />
    <div class="queue-toolbar">
      <span class="muted">解析请求按 FIFO 串行执行；排队中与解析中的任务可取消。当前队列 {{ allJobs.length }} 个任务。</span>
      <el-button size="small" :icon="Refresh" @click="fetchQueue">刷新</el-button>
    </div>
    <ContentGrid :columns="columns" :data="paged" :loading="loading" :total="filtered.length"
      v-model:page="page" v-model:page-size="pageSize" :page-sizes="[10, 15, 30, 50]"
      :actions="actions" :action-width="150" row-key="id" empty-text="队列为空（无排队/解析中任务）"
      @page-change="onPageChange">
      <template #name="{ row }">
        <span class="q-name">{{ row.name || row.refId }}</span>
        <span v-if="row.status === 'running'" class="parse-mark running">
          <el-icon class="spin"><Loading /></el-icon>正在解析
        </span>
        <span v-else class="parse-mark queued">
          <el-icon><Clock /></el-icon>排队中
        </span>
      </template>
      <template #type="{ row }">
        <el-tag size="small" :type="row.type === 'contract' ? 'warning' : 'info'" effect="plain">
          {{ row.type === 'contract' ? '合同' : '图片' }}
        </el-tag>
      </template>
      <template #status="{ row }">
        <el-tag size="small" :type="row.status === 'running' ? 'warning' : 'info'">
          {{ row.status === 'running' ? '解析中' : '排队中' }}
        </el-tag>
      </template>
    </ContentGrid>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Loading, Clock } from '@element-plus/icons-vue'
import { api } from '../api.js'
import QueryBuilder from '../components/QueryBuilder.vue'
import ContentGrid from '../components/ContentGrid.vue'

const emit = defineEmits(['open'])

const query = ref({})
const applied = ref({})
const allJobs = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(15)
let timer = null

const queryFields = [
  { key: 'q', label: '文件名（模糊）', type: 'text', placeholder: '文件名关键字' },
  { key: 'status', label: '队列状态', type: 'select', options: [
    { value: 'queued', label: '排队中' }, { value: 'running', label: '解析中' }] },
  { key: 'type', label: '文件类型', type: 'select', options: [
    { value: 'contract', label: '合同 docx/pdf' }, { value: 'image', label: '图片' }] },
]

const columns = [
  { key: 'position', label: '队列#', width: 70, align: 'center' },
  { key: 'name', label: '文件名', minWidth: 220, slot: 'name', showOverflowTooltip: false },
  { key: 'type', label: '类型', width: 80, slot: 'type' },
  { key: 'status', label: '状态', width: 90, slot: 'status' },
  { key: 'progress', label: '进度', width: 80, align: 'center', formatter: (v) => `${v ?? 0}%` },
  { key: 'stage', label: '当前阶段', minWidth: 160,
    formatter: (v, row) => row.stages?.find(s => s.key === v)?.label || v || '—' },
  { key: 'createdAt', label: '提交时间', width: 100,
    formatter: (v) => v ? new Date(v * 1000).toTimeString().slice(0, 8) : '—' },
]

const actions = [
  { label: '详情', type: 'primary', onClick: (row) => emit('open', { type: row.type, id: row.refId }) },
  { label: '取消解析', type: 'danger', onClick: cancel },
]

const filtered = computed(() => {
  const q = applied.value
  return allJobs.value.filter(j => {
    if (q.q && !(j.name || '').toLowerCase().includes(q.q.toLowerCase())) return false
    if (q.status && j.status !== q.status) return false
    if (q.type && j.type !== q.type) return false
    return true
  })
})
const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

async function fetchQueue(silent = false) {
  if (!silent) loading.value = true
  try {
    const r = await api.queue()
    allJobs.value = r.items
  } catch (e) { if (!silent) ElMessage.error(e.message) } finally { if (!silent) loading.value = false }
}

function onSearch(params) { applied.value = params; page.value = 1 }
function onReset() { /* 清空条件但不重查询 */ }
function onPageChange({ page: p, pageSize: s }) { page.value = p; pageSize.value = s }

async function cancel(row) {
  try {
    await ElMessageBox.confirm(`取消「${row.name || row.refId}」的解析？`, '取消解析', { type: 'warning' })
  } catch { return }
  try {
    await api.cancelJob(row.id)
    ElMessage.success('已取消')
    fetchQueue(true)
  } catch (e) { ElMessage.error(e.message) }
}

// ===== 队列轮询机制说明（与 FilesView 的分页轮询不同）=====
// 队列数据来自 GET /api/queue：一次性返回全部 queued+running 任务（非分页、体量小）。
// 这里每 1.5s 拉一次该全量活跃队列；查询过滤与分页均在前端 computed（filtered/paged）完成，
// 不再向后端发送分页请求。任务完成或取消后出队，对应行与「正在解析/排队中」标记自动移除。
// 对比：FilesView 轮询的是后端分页接口 /api/entries（每 2s 一次分页查询）；
// 本视图轮询的是轻量全量队列接口 /api/queue，前端自行切片分页，请求负担更小。
// silent=true 为轮询静默刷新（不置 loading 防闪烁）；组件卸载时清除定时器停止轮询。
onMounted(() => { fetchQueue(); timer = setInterval(() => fetchQueue(true), 1500) })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.queue-view { display: flex; flex-direction: column; gap: 10px; height: 100%; }
.queue-toolbar { display: flex; align-items: center; gap: 12px; justify-content: space-between; }
.q-name { word-break: break-all; }
.parse-mark { display: inline-flex; align-items: center; gap: 3px; margin-left: 6px; font-size: 12px; white-space: nowrap; }
.parse-mark.running { color: var(--review); }
.parse-mark.queued { color: var(--text-3); }
.spin { animation: q-spin 1s linear infinite; }
@keyframes q-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
