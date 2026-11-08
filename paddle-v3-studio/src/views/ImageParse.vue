<template>
  <div class="page">
    <div class="side panel">
      <div class="side-head">
        <el-upload :show-file-list="false" :http-request="doUpload" accept=".png,.jpg,.jpeg,.bmp,.webp">
          <el-button type="primary" :icon="Upload" :loading="uploading" size="small">上传图片</el-button>
        </el-upload>
        <el-input v-model="q" size="small" placeholder="搜索文件名" clearable :prefix-icon="Search" @input="loadDocs" />
      </div>
      <el-scrollbar class="doc-list">
        <div v-for="d in docs" :key="d.id" class="doc-item" :class="{ on: d.id === currentId }" @click="openDoc(d)">
          <div class="doc-name">{{ d.name }}</div>
          <div class="muted">
            {{ d.width }}×{{ d.height }} · {{ formatBytes(d.size) }}
            <el-tag v-if="d.parsed" key="parsed" type="success" size="small" effect="plain">已解析</el-tag>
            <el-tag v-else key="unparsed" size="small" effect="plain">未解析</el-tag>
          </div>
        </div>
        <el-empty v-if="!docs.length" description="暂无上传件" :image-size="60" />
      </el-scrollbar>
    </div>

    <div class="work">
      <template v-if="current">
        <div class="job-bar panel" v-if="job && ['queued', 'running'].includes(job.status)">
          <el-progress :percentage="job.progress" :stroke-width="8" style="flex:1" />
          <span class="muted">{{ stageLabel }}</span>
        </div>
        <el-alert v-if="job?.status === 'failed'" type="error" :closable="false" class="job-bar"
          :title="`解析失败：${job.error?.code} — ${job.error?.message}`" :description="job.error?.hint" />
        <div class="overlay-toggles">
          <span class="muted">框选：</span>
          <el-checkbox v-model="display.show_layout" @change="v => setDisplay('show_layout', v)" size="small">版面区域</el-checkbox>
          <el-checkbox v-model="display.show_ocr" @change="v => setDisplay('show_ocr', v)" size="small">OCR 文本</el-checkbox>
        </div>
        <div class="split">
          <PageViewer :src="api.imageUrl(current.id)" :width="current.width" :height="current.height"
            :layout="result?.layout || []" :ocr="result?.ocr || []"
            :show-layout="display.show_layout" :show-ocr="display.show_ocr"
            :selected="selected" @select="selected = $event" />
          <div class="right panel">
            <el-tabs v-model="tab" class="tabs">
              <el-tab-pane :label="`版面块 (${result?.layout?.length || 0})`" name="layout">
                <el-scrollbar height="100%">
                  <div v-for="(b, i) in result?.layout || []" :key="i" class="card"
                    :class="{ on: selected === 'l' + i }" @click="selected = 'l' + i">
                    <div class="card-head">
                      <el-tag size="small">{{ b.label }}</el-tag>
                      <span class="muted mono">score {{ b.score }}</span>
                    </div>
                    <div class="muted mono">bbox [{{ b.bbox.join(', ') }}]</div>
                  </div>
                  <el-empty v-if="!result?.layout?.length" description="无版面结果（未解析或解析失败）" :image-size="60" />
                </el-scrollbar>
              </el-tab-pane>
              <el-tab-pane :label="`OCR 文本 (${result?.ocr?.length || 0})`" name="ocr">
                <el-scrollbar height="100%">
                  <div class="conf-summary" v-if="result?.ocr?.length">
                    <el-tag type="success" size="small" effect="plain">高 {{ tierCount.high }}</el-tag>
                    <el-tag type="warning" size="small" effect="plain">复核 {{ tierCount.review }}</el-tag>
                    <el-tag type="danger" size="small" effect="plain">低 {{ tierCount.low }}</el-tag>
                    <span class="muted">阈值 ≥{{ cfg.parse.review_confidence }} / ≥{{ cfg.parse.min_confidence }}</span>
                  </div>
                  <div v-for="(o, i) in result?.ocr || []" :key="i" class="card"
                    :class="{ on: selected === 'o' + i }" @click="selected = 'o' + i">
                    <div class="card-head">
                      <span class="ocr-text">{{ o.text }}</span>
                      <el-tag :type="o.tier === 'high' ? 'success' : o.tier === 'review' ? 'warning' : o.tier === 'low' ? 'danger' : 'info'" size="small">
                        {{ o.confidence ?? '—' }} · {{ TIER_LABEL[o.tier] }}
                      </el-tag>
                    </div>
                  </div>
                  <el-empty v-if="!result?.ocr?.length" description="无 OCR 结果" :image-size="60" />
                </el-scrollbar>
              </el-tab-pane>
              <el-tab-pane label="JSON" name="json">
                <el-scrollbar height="100%"><pre class="mono json">{{ jsonText }}</pre></el-scrollbar>
              </el-tab-pane>
            </el-tabs>
            <div class="right-foot">
              <el-button size="small" :icon="Refresh" @click="reparse" :disabled="!!activeJob">重新解析</el-button>
              <el-button size="small" :icon="Delete" type="danger" plain @click="removeDoc">删除</el-button>
              <span class="muted" v-if="result?.timings">推理 {{ result.timings.predictMs }} ms · {{ result.device?.toUpperCase() }}</span>
            </div>
          </div>
        </div>
      </template>
      <el-empty v-else description="上传或选择一张图片开始解析" class="empty panel" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Search, Refresh, Delete } from '@element-plus/icons-vue'
import { api } from '../api.js'
import { display, setDisplay } from '../display.js'
import { formatBytes, TIER_LABEL } from '../utils.js'
import PageViewer from '../components/PageViewer.vue'

const docs = ref([])
const q = ref('')
const currentId = ref(null)
const current = ref(null)
const result = ref(null)
const job = ref(null)
const selected = ref(null)
const tab = ref('layout')
const uploading = ref(false)
const cfg = reactive({ parse: { review_confidence: 0.9, min_confidence: 0.7 } })
let poll = null

const activeJob = computed(() => job.value && ['queued', 'running'].includes(job.value.status))
const stageLabel = computed(() => {
  const s = job.value?.stages?.find(x => x.key === job.value?.stage)
  return s?.label || job.value?.stage || ''
})
const tierCount = computed(() => {
  const c = { high: 0, review: 0, low: 0 }
  for (const o of result.value?.ocr || []) if (c[o.tier] !== undefined) c[o.tier]++
  return c
})
const jsonText = computed(() => result.value ? JSON.stringify(result.value, null, 2) : '')

async function loadDocs() {
  try { docs.value = (await api.documents(q.value)).items } catch { docs.value = [] }
}
async function loadCfg() {
  try { Object.assign(cfg, await api.config()) } catch {}
}

async function doUpload({ file }) {
  uploading.value = true
  try {
    const r = await api.uploadImage(file)
    ElMessage.success('上传成功，已开始解析')
    await loadDocs()
    await openDoc({ id: r.id })
  } catch (e) { ElMessage.error(e.message) } finally { uploading.value = false }
}

async function openDoc(d) {
  currentId.value = d.id
  selected.value = null
  result.value = null
  job.value = null
  try {
    current.value = await api.document(d.id)
    if (current.value.parsed) result.value = await api.result(d.id)
    const jobs = (await api.jobs(d.id)).items
    job.value = jobs[0] || null
    watchJob()
  } catch (e) { ElMessage.error(e.message) }
}

function watchJob() {
  clearInterval(poll)
  poll = setInterval(async () => {
    if (!currentId.value) return
    try {
      const jobs = (await api.jobs(currentId.value)).items
      const j = jobs[0]
      if (!j) return
      job.value = j
      if (j.status === 'done') {
        clearInterval(poll)
        result.value = await api.result(currentId.value)
        current.value.parsed = true
        await loadDocs()
      } else if (j.status === 'failed') {
        clearInterval(poll)
        await loadDocs()
      }
    } catch {}
  }, 1200)
}

async function reparse() {
  try {
    await api.parse(currentId.value)
    result.value = null
    watchJob()
  } catch (e) { ElMessage.error(e.message) }
}

async function removeDoc() {
  try {
    await ElMessageBox.confirm(`删除 ${current.value.name}？产物一并清除`, '删除确认', { type: 'warning' })
    await api.deleteDoc(currentId.value)
    current.value = null; currentId.value = null; result.value = null
    await loadDocs()
  } catch {}
}

onMounted(async () => { await loadCfg(); await loadDocs() })
onUnmounted(() => clearInterval(poll))
</script>

<style scoped>
.page { display: flex; gap: 10px; height: 100%; min-height: 0; }
.side { width: 250px; display: flex; flex-direction: column; flex-shrink: 0; }
.side-head { padding: 10px; display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--border); }
.doc-list { flex: 1; }
.doc-item { padding: 9px 12px; border-bottom: 1px solid var(--border); cursor: pointer; }
.doc-item.on { background: #eff6ff; border-left: 3px solid var(--brand); }
.doc-name { font-size: 13px; word-break: break-all; margin-bottom: 3px; }
.work { flex: 1; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.job-bar { padding: 8px 12px; display: flex; gap: 12px; align-items: center; }
.overlay-toggles { display: flex; gap: 12px; align-items: center; padding: 2px 4px; }
.split { flex: 1; display: flex; gap: 10px; min-height: 0; }
.right { width: 380px; flex-shrink: 0; display: flex; flex-direction: column; }
.tabs { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 0 10px; }
.tabs :deep(.el-tabs__content) { flex: 1; min-height: 0; }
.tabs :deep(.el-tab-pane) { height: 100%; }
.card { border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; cursor: pointer; }
.card.on { border-color: var(--brand); background: #eff6ff; }
.card-head { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.ocr-text { font-size: 13px; word-break: break-all; }
.conf-summary { display: flex; gap: 6px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.json { white-space: pre-wrap; word-break: break-all; padding: 4px; }
.right-foot { border-top: 1px solid var(--border); padding: 8px 10px; display: flex; gap: 8px; align-items: center; }
.empty { flex: 1; display: flex; align-items: center; justify-content: center; }
</style>