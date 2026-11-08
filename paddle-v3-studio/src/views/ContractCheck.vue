<template>
  <div class="page">
    <div class="side panel">
      <div class="side-head">
        <el-upload :show-file-list="false" :http-request="doUpload" accept=".docx,.doc,.pdf">
          <el-button type="primary" :icon="Upload" :loading="uploading" size="small">上传合同 docx/pdf</el-button>
        </el-upload>
        <div class="muted">一个文件 = 一个条目，逐页转图识别</div>
      </div>
      <el-scrollbar class="doc-list">
        <div v-for="c in contracts" :key="c.id" class="doc-item" :class="{ on: c.id === currentId }" @click="openContract(c)">
          <div class="doc-name">{{ c.name }}</div>
          <div class="muted row">
            <span>{{ c.pageCount || '?' }} 页</span>
            <el-tag v-if="c.verifyStatus" :type="VERIFY_TYPE[c.verifyStatus] || 'info'" size="small">
              {{ VERIFY_LABEL[c.verifyStatus] || c.verifyStatus }}
            </el-tag>
            <el-tag v-else-if="c.status === 'parsing'" size="small" type="info">解析中</el-tag>
            <el-tag v-else-if="c.status === 'failed'" size="small" type="danger">失败</el-tag>
          </div>
          <div class="muted mono" v-if="c.contractNo">{{ c.contractNo }}</div>
        </div>
        <el-empty v-if="!contracts.length" description="暂无合同条目" :image-size="60" />
      </el-scrollbar>
    </div>

    <div class="work" v-if="current">
      <div class="job-bar panel" v-if="job && ['queued', 'running'].includes(job.status)">
        <el-progress :percentage="job.progress" :stroke-width="8" style="flex:1" />
        <span class="muted">{{ stageLabel }}</span>
      </div>
      <el-alert v-if="job?.status === 'failed'" type="error" :closable="false" class="job-bar"
        :title="`解析失败：${job.error?.code} — ${job.error?.message}`" :description="job.error?.hint" />

      <div class="head panel">
        <div>
          <b>{{ current.name }}</b>
          <span class="muted"> · {{ current.pageCount }} 页 · {{ current.convert || '' }} · {{ formatBytes(current.size) }}</span>
        </div>
        <div class="row">
          <el-tag v-if="current.verifyStatus" :type="VERIFY_TYPE[current.verifyStatus] || 'info'">
            {{ VERIFY_LABEL[current.verifyStatus] || current.verifyStatus }}
          </el-tag>
          <el-button size="small" :icon="Refresh" @click="reverify" :loading="reverifying">重新校验</el-button>
          <el-button size="small" :icon="Refresh" @click="reparse">重新解析</el-button>
          <el-button size="small" :icon="Delete" type="danger" plain @click="removeContract">删除</el-button>
        </div>
      </div>

      <div class="split" v-if="payload">
        <div class="left">
          <div class="page-tabs">
            <el-radio-group v-model="pageNo" size="small">
              <el-radio-button v-for="p in payload.pages" :key="p.page" :value="p.page">第 {{ p.page }} 页</el-radio-button>
            </el-radio-group>
            <el-checkbox v-model="display.show_contract_no" @change="v => setDisplay('show_contract_no', v)" size="small">合同号</el-checkbox>
            <el-checkbox v-model="display.show_contract_table" @change="v => setDisplay('show_contract_table', v)" size="small">明细表</el-checkbox>
            <el-checkbox v-model="display.show_layout" @change="v => setDisplay('show_layout', v)" size="small">版面</el-checkbox>
            <el-checkbox v-model="display.show_ocr" @change="v => setDisplay('show_ocr', v)" size="small">OCR</el-checkbox>
          </div>
          <PageViewer v-if="pageData" :src="api.contractPageUrl(current.id, pageNo)"
            :width="pageData.width" :height="pageData.height"
            :layout="pageData.layout" :ocr="display.show_ocr ? pageData.ocr : []"
            :marks="marksForPage" :show-layout="display.show_layout" />
        </div>

        <div class="right panel">
          <el-scrollbar height="100%">
            <div class="section">
              <div class="sec-title">合同号</div>
              <template v-if="extracted?.contractNo">
                <div class="no-card">
                  <span class="no-text mono">{{ extracted.contractNo.number }}</span>
                  <el-tag type="danger" size="small" effect="plain">第 {{ extracted.contractNo.page }} 页已标出</el-tag>
                </div>
                <div class="muted">命中行：{{ extracted.contractNo.lineText }}</div>
                <div class="muted" v-if="extracted.contractNo.numberRaw">OCR 原读：{{ extracted.contractNo.numberRaw }}（已归一化）</div>
              </template>
              <el-alert v-else type="warning" :closable="false" title="未识别到合同编号" />
            </div>

            <div class="section" v-if="extracted?.crossPage?.enabled">
              <div class="sec-title">
                跨页合同号校验
                <el-tag v-if="extracted.crossPage.consistent" type="success" size="small">一致</el-tag>
                <el-tag v-else type="danger" size="small">不一致</el-tag>
              </div>
              <div class="muted" style="margin-bottom:6px">
                出现 {{ extracted.crossPage.occurrenceCount }} 次 · 页 [{{ extracted.crossPage.pages.join(', ') }}]
                · 选定方式 {{ extracted.crossPage.chosenBy === 'majority' ? '多数投票' : '首个命中' }}
                <template v-if="extracted.crossPage.preferFirstPage"> · 首页优先</template>
                <template v-if="extracted.crossPage.normalizeConfusables"> · 易混归一化</template>
              </div>
              <div v-if="extracted.crossPage.filtered?.total" class="muted" style="margin-bottom:6px">
                已过滤 {{ extracted.crossPage.filtered.total }} 个候选（置信度 {{ extracted.crossPage.filtered.confidence }} / 格式 {{ extracted.crossPage.filtered.format }}）
              </div>
              <div v-if="!extracted.crossPage.consistent" class="muted" style="color:var(--low)">
                不同编号：{{ extracted.crossPage.distinctNumbers.join(' / ') }}
              </div>
              <div v-for="(o, oi) in extracted.crossPage.occurrences" :key="oi" class="cross-row">
                <el-tag size="small" effect="plain">第 {{ o.page }} 页</el-tag>
                <span class="mono">{{ o.number }}</span>
                <span class="muted">{{ SOURCE_LABEL[o.source] || o.source }}</span>
              </div>
            </div>

            <div class="section">
              <div class="sec-title">合同明细（表格区域提取）</div>
              <div v-for="(t, ti) in extracted?.tables || []" :key="ti" class="table-block">
                <div class="muted">第 {{ t.page }} 页表格 · {{ t.entries.length }} 条明细<span v-if="t.totalRow"> · {{ t.totalRow.text }}</span></div>
                <el-table :data="t.entries" size="small" border max-height="260">
                  <el-table-column prop="name" label="品名" min-width="110" show-overflow-tooltip />
                  <el-table-column prop="spec" label="规格" min-width="80" show-overflow-tooltip />
                  <el-table-column prop="qtyText" label="数量" width="70" />
                  <el-table-column prop="priceText" label="单价" width="80" />
                  <el-table-column prop="amountText" label="金额" width="90" />
                </el-table>
              </div>
              <el-empty v-if="!extracted?.tables?.length" description="未识别到明细表格" :image-size="50" />
            </div>

            <div class="section" v-if="report">
              <div class="sec-title">
                数据源校验
                <el-tag :type="VERIFY_TYPE[report.status] || 'info'" size="small">{{ VERIFY_LABEL[report.status] || report.status }}</el-tag>
              </div>
              <div class="muted mono" style="margin-bottom:6px">{{ report.sourceUrl }}</div>
              <el-alert v-if="report.hint" type="info" :closable="false" :title="report.hint" style="margin-bottom:6px" />
              <div v-for="c in report.checks" :key="c.key" class="check-row">
                <el-icon :color="c.ok ? 'var(--match-ok)' : 'var(--match-bad)'">
                  <CircleCheck v-if="c.ok" /><CircleClose v-else />
                </el-icon>
                <span>{{ c.label }}</span><span class="muted">{{ c.detail }}</span>
              </div>
              <template v-if="report.itemComparison?.length">
                <div class="sec-title" style="margin-top:10px">逐行对照（数据源 ↔ 文件）</div>
                <div v-for="(r, i) in report.itemComparison" :key="i" class="cmp-card" :class="{ bad: !r.fields.every(f => f.ok) }">
                  <div class="cmp-head">
                    <b>{{ r.source?.itemName || r.ocr?.name || '（未知品名）' }}</b>
                    <el-tag :type="r.fields.every(f => f.ok) ? 'success' : 'danger'" size="small">
                      {{ r.fields.every(f => f.ok) ? '一致' : '不符' }}
                    </el-tag>
                  </div>
                  <div v-for="f in r.fields" :key="f.field" class="cmp-field" :class="{ bad: !f.ok }">
                    <span class="fld">{{ FIELD_LABEL[f.field] || f.field }}</span>
                    <span>源 {{ f.source ?? '—' }}</span>
                    <span>文件 {{ f.ocr ?? '—' }}</span>
                    <span class="muted">{{ f.detail }}</span>
                  </div>
                </div>
              </template>
            </div>
          </el-scrollbar>
        </div>
      </div>
      <el-empty v-else-if="current.status === 'parsing'" description="正在转换与识别…" class="panel empty" />
    </div>
    <el-empty v-else description="上传或选择一个合同条目" class="panel empty" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Refresh, Delete, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import { api } from '../api.js'
import { display, setDisplay } from '../display.js'
import { formatBytes, VERIFY_LABEL, VERIFY_TYPE } from '../utils.js'
import PageViewer from '../components/PageViewer.vue'

const FIELD_LABEL = { name: '品名', quantity: '数量', unitPrice: '单价', amount: '金额' }
const SOURCE_LABEL = { 'same-line': '单行', 'next-line': '多行(下行)', 'split-line': '多行(折行)' }

const contracts = ref([])
const currentId = ref(null)
const current = ref(null)
const payload = ref(null)
const job = ref(null)
const pageNo = ref(1)
const uploading = ref(false)
const reverifying = ref(false)
let poll = null

const extracted = computed(() => payload.value?.extracted)
const report = computed(() => payload.value?.report)
const pageData = computed(() => payload.value?.pages?.find(p => p.page === pageNo.value))
const marksForPage = computed(() => {
  if (!extracted.value) return null
  const no = extracted.value.contractNo
  return {
    contractNo: display.show_contract_no && no && no.page === pageNo.value ? no : null,
    tables: display.show_contract_table
      ? (extracted.value.tables || []).filter(t => t.page === pageNo.value) : [],
  }
})
const stageLabel = computed(() => {
  const s = job.value?.stages?.find(x => x.key === job.value?.stage)
  return s?.label || job.value?.stage || ''
})

async function loadContracts() {
  try { contracts.value = (await api.contracts()).items } catch { contracts.value = [] }
}

async function doUpload({ file }) {
  uploading.value = true
  try {
    const r = await api.uploadContract(file)
    ElMessage.success('合同已上传，开始逐页解析')
    await loadContracts()
    await openContract({ id: r.id })
  } catch (e) { ElMessage.error(e.message) } finally { uploading.value = false }
}

async function openContract(c) {
  currentId.value = c.id
  payload.value = null
  job.value = null
  pageNo.value = 1
  try {
    current.value = await api.contract(c.id)
    if (current.value.status === 'parsed') payload.value = await api.contractResult(c.id)
    job.value = (await api.jobs(c.id)).items[0] || null
    watchJob()
  } catch (e) { ElMessage.error(e.message) }
}

function watchJob() {
  clearInterval(poll)
  poll = setInterval(async () => {
    if (!currentId.value) return
    try {
      const j = (await api.jobs(currentId.value)).items[0]
      if (!j) return
      job.value = j
      current.value = await api.contract(currentId.value)
      if (j.status === 'done') {
        clearInterval(poll)
        payload.value = await api.contractResult(currentId.value)
        await loadContracts()
      } else if (j.status === 'failed') {
        clearInterval(poll)
        await loadContracts()
      }
    } catch {}
  }, 1500)
}

async function reverify() {
  reverifying.value = true
  try {
    const r = await api.reverify(currentId.value)
    if (payload.value) payload.value.report = r
    current.value.verifyStatus = r.status
    ElMessage[r.status === 'matched' ? 'success' : 'warning'](`校验结果：${VERIFY_LABEL[r.status] || r.status}`)
    await loadContracts()
  } catch (e) { ElMessage.error(e.message) } finally { reverifying.value = false }
}

async function reparse() {
  try {
    await api.reparseContract(currentId.value)
    payload.value = null
    current.value.status = 'parsing'
    watchJob()
  } catch (e) { ElMessage.error(e.message) }
}

async function removeContract() {
  try {
    await ElMessageBox.confirm(`删除合同条目 ${current.value.name}？`, '删除确认', { type: 'warning' })
    await api.deleteContract(currentId.value)
    current.value = null; currentId.value = null; payload.value = null
    await loadContracts()
  } catch {}
}

onMounted(loadContracts)
onUnmounted(() => clearInterval(poll))
</script>

<style scoped>
.page { display: flex; gap: 10px; height: 100%; min-height: 0; }
.side { width: 260px; display: flex; flex-direction: column; flex-shrink: 0; }
.side-head { padding: 10px; display: flex; flex-direction: column; gap: 6px; border-bottom: 1px solid var(--border); }
.doc-list { flex: 1; }
.doc-item { padding: 9px 12px; border-bottom: 1px solid var(--border); cursor: pointer; }
.doc-item.on { background: #eff6ff; border-left: 3px solid var(--brand); }
.doc-name { font-size: 13px; word-break: break-all; margin-bottom: 3px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.work { flex: 1; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.job-bar { padding: 8px 12px; display: flex; gap: 12px; align-items: center; }
.head { padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
.split { flex: 1; display: flex; gap: 10px; min-height: 0; }
.left { flex: 1; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.page-tabs { display: flex; gap: 10px; align-items: center; }
.right { width: 430px; flex-shrink: 0; padding: 10px; }
.section { margin-bottom: 16px; }
.sec-title { font-weight: 600; font-size: 13px; margin-bottom: 6px; display: flex; gap: 8px; align-items: center; }
.no-card { display: flex; gap: 10px; align-items: center; margin-bottom: 4px; }
.no-text { font-size: 18px; font-weight: 700; color: var(--contract-no-box); }
.table-block { margin-bottom: 10px; }
.check-row { display: flex; gap: 6px; align-items: center; font-size: 13px; padding: 3px 0; flex-wrap: wrap; }
.cross-row { display: flex; gap: 8px; align-items: center; font-size: 12px; padding: 2px 0; }
.cmp-card { border: 1px solid var(--border); border-radius: 6px; padding: 8px; margin-bottom: 6px; }
.cmp-card.bad { border-color: var(--match-bad); background: #fef2f2; }
.cmp-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; font-size: 13px; }
.cmp-field { display: flex; gap: 10px; font-size: 12px; padding: 2px 0; flex-wrap: wrap; }
.cmp-field.bad { color: var(--low); }
.cmp-field .fld { width: 36px; color: var(--text-3); }
.empty { flex: 1; display: flex; align-items: center; justify-content: center; }
</style>