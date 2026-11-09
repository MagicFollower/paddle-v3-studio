<template>
  <el-scrollbar height="100%">
    <div class="settings">
      <div class="panel block">
        <div class="sec-title">计算设备</div>
        <el-alert v-if="dev?.fallback" type="warning" :closable="false" show-icon
          title="GPU 不可用，已降级到 CPU" :description="dev.reason" style="margin-bottom:10px" />
        <el-alert v-else-if="dev?.device === 'gpu'" type="success" :closable="false" show-icon
          :title="`正在使用 GPU：${dev.device_name}`" style="margin-bottom:10px" />
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="请求设备">{{ dev?.requested || '-' }}</el-descriptions-item>
          <el-descriptions-item label="实际设备">{{ dev?.device?.toUpperCase() || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Paddle 版本">{{ dev?.paddle_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="CUDA 编译">{{ dev?.cuda_compiled ? '是' : '否（CPU 构建）' }}</el-descriptions-item>
          <el-descriptions-item label="降级原因" :span="2">{{ dev?.reason || '无' }}</el-descriptions-item>
        </el-descriptions>
        <div style="margin-top:10px">
          <el-button size="small" :icon="Refresh" :loading="probing" @click="reprobe">重新探测设备</el-button>
          <span class="muted">切换设备或模型后自动重建流水线；GPU 自检为真实张量运算</span>
        </div>
      </div>

      <div class="panel block">
        <div class="sec-title">离线模型库（ASCII 路径 MODEL-V3）</div>
        <el-table :data="modelRows" size="small" border>
          <el-table-column prop="key" label="用途" width="140" />
          <el-table-column prop="name" label="模型" />
          <el-table-column label="本地状态" width="120">
            <template #default="{ row }">
              <el-tag :type="row.present ? 'success' : 'danger'" size="small">
                {{ row.present ? '已就位' : '缺失' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div class="muted" style="margin-top:6px">
          运行时零联网：模型缺失直接报 MODEL_MISSING。预下载：scripts\setup.cmd（仅安装阶段联网）。
          模型库在 ASCII 路径 MODEL-V3（Paddle 引擎读不了中文路径）。
          paddleocr {{ status?.paddleocrVersion || '' }} · 流水线 {{ status?.pipeline || '' }}
        </div>
      </div>

      <div class="panel block">
        <div class="sec-title">合同数据源（Spring Boot 2.7.18）</div>
        <div class="row">
          <el-tag :type="source?.reachable ? 'success' : 'danger'">
            {{ source?.reachable ? '在线' : '不可达' }}
          </el-tag>
          <span class="mono muted">{{ cfgForm.contract?.source_url }}</span>
          <el-button size="small" :icon="Refresh" :loading="testing" @click="testSource">测试连接</el-button>
        </div>
        <div class="muted" v-if="source && !source.reachable" style="margin-top:6px">{{ source.hint }} · {{ source.error }}</div>
      </div>

      <div class="panel block">
        <div class="sec-title">LLM 字段映射（API 端点接入）</div>
        <div class="row" style="flex-wrap:wrap">
          <el-tag :type="llm?.enabled ? 'success' : 'info'" size="small">{{ llm?.enabled ? '映射阶段已启用' : '映射阶段已关闭' }}</el-tag>
          <el-tag :type="llm?.reachable ? 'success' : 'danger'" size="small">{{ llm?.reachable ? '端点可达' : '端点不可达' }}</el-tag>
          <el-tag :type="llm?.modelPresent ? 'success' : (llm?.modelPresent === false ? 'danger' : 'info')" size="small">
            {{ llm?.modelPresent ? '模型已暴露' : (llm?.modelPresent === false ? '模型未暴露' : '模型名未核对') }}
          </el-tag>
          <el-tag v-if="llm?.apiKeySet" size="small" type="info">已设 API Key</el-tag>
          <el-button size="small" :icon="Refresh" :loading="llmProbing" @click="checkLlm">检测 LLM 可用性</el-button>
        </div>
        <div class="muted mono" style="margin-top:6px;word-break:break-all">{{ llm?.endpoint }} · model={{ llm?.model }}</div>
        <div class="muted" v-if="llm?.reason" style="margin-top:4px">{{ llm.reason }}</div>
        <div class="muted" style="margin-top:4px">
          后端以客户端方式调用 OpenAI 兼容端点，<b>启动不拉起模型</b>。本地模型双击 <span class="mono">llm-server.cmd</span>
          手动启动（默认 http://127.0.0.1:9931）；也可在下方「LLM 字段映射」分组填写远程/第三方端点 + 模型名 + API Key。
          启用 LLM 时纳入解析前门控；表头→业务字段对应关系在左侧「字段映射」页编辑。
        </div>
      </div>

      <div class="panel block">
        <div class="sec-title">模型可用性总览（解析前需全部通过）</div>
        <div class="row" style="margin-bottom:8px;flex-wrap:wrap">
          <el-button size="small" :icon="Refresh" :loading="modelsProbing" @click="checkAllModels">检测所有模型</el-button>
          <el-tag :type="models?.ok ? 'success' : 'danger'" size="small">
            {{ models?.ok ? '全部可用，允许解析' : '存在不可用模型，解析将被拒绝' }}
          </el-tag>
        </div>
        <el-table :data="models?.models || []" size="small" border>
          <el-table-column prop="name" label="模型" min-width="180" show-overflow-tooltip />
          <el-table-column label="类型" width="110">
            <template #default="{ row }">{{ row.kind === 'llm' ? 'LLM 端点' : 'Paddle 本地' }}</template>
          </el-table-column>
          <el-table-column label="必需" width="70" align="center">
            <template #default="{ row }">{{ row.required ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.available ? 'success' : (row.required ? 'danger' : 'info')" size="small">
                {{ row.available ? '可用' : '不可用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="说明" min-width="220" show-overflow-tooltip />
        </el-table>
        <el-alert v-if="models && !models.ok" type="error" :closable="false" show-icon style="margin-top:8px"
          :title="'解析门控未通过：' + (models.errors || []).join('；')" />
      </div>

      <div class="panel block" v-for="g in schema?.groups || []" :key="g.key">
        <div class="sec-title">{{ g.label }}</div>
        <el-form label-width="230px" size="small">
          <el-form-item v-for="f in g.fields" :key="f.key" :label="f.label">
            <div class="field-row">
              <el-switch v-if="f.type === 'bool'" v-model="cfgForm[g.key][f.key]" />
              <el-input-number v-else-if="f.type === 'number'" v-model="cfgForm[g.key][f.key]"
                :min="f.min" :max="f.max" :step="f.step || 1" />
              <el-select v-else-if="f.type === 'enum'" v-model="cfgForm[g.key][f.key]" style="width:160px">
                <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
              </el-select>
              <div v-else-if="f.type === 'colors'" class="color-grid">
                <div v-for="c in f.options" :key="c.key" class="color-row">
                  <span class="color-label">{{ c.label }}</span>
                  <el-color-picker v-model="cfgForm[g.key].colors[c.key]" size="small" />
                  <span class="mono color-hex">{{ cfgForm[g.key].colors[c.key] }}</span>
                  <el-button size="small" text type="primary" @click="cfgForm[g.key].colors[c.key] = c.default">还原</el-button>
                </div>
              </div>
              <el-input v-else-if="f.type === 'textarea'" v-model="cfgForm[g.key][f.key]" type="textarea"
                :rows="f.rows || 6" style="width:560px;max-width:100%" />
              <el-input v-else v-model="cfgForm[g.key][f.key]" style="width:320px" />
              <el-button v-if="f.default !== undefined" size="small" text type="primary"
                @click="cfgForm[g.key][f.key] = f.default">还原默认</el-button>
              <el-tooltip v-if="f.help" placement="top" effect="light" :show-after="150" popper-class="help-popper">
                <template #content>
                  <div class="help-tip">
                    <div v-for="(v, k) in f.help" :key="k" class="help-line"><b>{{ k }}</b> {{ v }}</div>
                  </div>
                </template>
                <el-icon class="help-icon"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
          </el-form-item>
        </el-form>
      </div>

      <div class="foot">
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
        <el-button @click="reload">还原</el-button>
        <span class="muted">保存后立即生效（流水线下次解析重建）</span>
      </div>
    </div>
  </el-scrollbar>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, QuestionFilled } from '@element-plus/icons-vue'
import { api } from '../api.js'
import { applyColors, loadDisplay } from '../display.js'

const schema = ref(null)
const status = ref(null)
const source = ref(null)
const llm = ref(null)
const models = ref(null)
const cfgForm = reactive({ parse: {}, model: {}, contract: {} })
const saving = ref(false)
const probing = ref(false)
const testing = ref(false)
const llmProbing = ref(false)
const modelsProbing = ref(false)

const dev = computed(() => status.value?.device)
const modelRows = computed(() => {
  const labels = { layout_model: '版面检测', det_model: '文本检测', rec_model: '文本识别', table_model: '表格识别' }
  return Object.entries(status.value?.models || {}).map(([key, v]) => ({ key: labels[key] || key, ...v }))
})

async function reload() {
  const [s, st, cfg] = await Promise.all([api.schema(), api.modelStatus(), api.config()])
  schema.value = s
  status.value = st
  for (const g of Object.keys(cfgForm)) delete cfgForm[g]
  Object.assign(cfgForm, JSON.parse(JSON.stringify(cfg)))
  try { llm.value = await api.llmStatus() } catch { llm.value = null }
  try { models.value = await api.modelsAvailability() } catch { models.value = null }
}

async function checkLlm() {
  llmProbing.value = true
  try {
    const av = await api.llmCheck()
    llm.value = { ...(llm.value || {}), ...av, available: av.available }
    ElMessage[av.available ? 'success' : 'warning'](
      av.available ? `LLM 端点可用：${av.endpoint}（${av.model}）` : `LLM 不可用：${av.reason || ''}`)
  } catch (e) { ElMessage.error(e.message) } finally { llmProbing.value = false }
}

async function checkAllModels() {
  modelsProbing.value = true
  try {
    models.value = await api.modelsAvailability()
    ElMessage[models.value.ok ? 'success' : 'error'](
      models.value.ok ? '所有模型可用，允许解析' : `解析门控未通过：${(models.value.errors || []).join('；')}`)
  } catch (e) { ElMessage.error(e.message) } finally { modelsProbing.value = false }
}

async function checkSource() {
  try { source.value = await api.sourceStatus() } catch (e) { source.value = { reachable: false, error: e.message } }
}

async function testSource() {
  testing.value = true
  try {
    await checkSource()
    if (source.value?.reachable) ElMessage.success('合同数据源连接成功')
    else ElMessage.error(`合同数据源连接失败：${source.value?.error || '不可达'}（先启动 contract-source）`)
  } finally { testing.value = false }
}

async function reprobe() {
  probing.value = true
  try {
    const r = await api.reprobe()
    status.value = await api.modelStatus()
    ElMessage[r.device.device === 'gpu' ? 'success' : 'warning'](
      r.device.device === 'gpu' ? `GPU 可用：${r.device.device_name}` : `当前走 CPU：${r.device.reason || ''}`)
  } catch (e) { ElMessage.error(e.message) } finally { probing.value = false }
}

async function save() {
  saving.value = true
  try {
    await api.saveConfig(cfgForm)
    ElMessage.success('配置已保存（data/config.json）')
    await loadDisplay()
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
  // 状态刷新放在按钮复位之后，不阻塞保存（设备变化时此处会懒重探）
  try { status.value = await api.modelStatus() } catch {}
  checkSource()
}

// 配色编辑即时预览（保存后由 loadDisplay 以盘上值为准）
watch(() => cfgForm.display?.colors, (colors) => { if (colors) applyColors(colors) }, { deep: true })

onMounted(async () => {
  try { await reload(); await checkSource() } catch (e) { ElMessage.error(e.message) }
})
</script>

<style scoped>
.settings { max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; gap: 10px; padding-bottom: 20px; }
.block { padding: 14px 16px; }
.sec-title { font-weight: 600; margin-bottom: 10px; }
.row { display: flex; gap: 10px; align-items: center; }
.foot { display: flex; gap: 10px; align-items: center; padding: 4px 2px; }
.field-row { display: flex; align-items: center; gap: 8px; }
.help-icon { color: var(--text-3); cursor: help; font-size: 16px; }
.help-icon:hover { color: var(--brand); }
.help-tip { max-width: 360px; line-height: 1.7; font-size: 12px; }
.help-line { margin-bottom: 4px; }
.help-line b { color: var(--brand); margin-right: 4px; }
.color-grid { display: flex; flex-direction: column; gap: 6px; }
.color-row { display: flex; align-items: center; gap: 8px; }
.color-label { width: 110px; font-size: 12px; color: var(--text-2); }
.color-hex { width: 70px; color: var(--text-3); }
</style>