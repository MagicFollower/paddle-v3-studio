<template>
  <div class="query-builder panel">
    <div class="qb-fields">
      <div v-for="f in fields" :key="f.key" class="qb-field" :style="f.span ? { gridColumn: `span ${f.span}` } : null">
        <label class="qb-label">{{ f.label }}</label>
        <div class="qb-control">
          <el-input v-if="f.type === 'text'" v-model="params[f.key]" :placeholder="f.placeholder || '请输入'"
            clearable @keyup.enter="doSearch" />
          <el-input-number v-else-if="f.type === 'number'" v-model="params[f.key]" :min="f.min" :max="f.max"
            :step="f.step || 1" :placeholder="f.placeholder" controls-position="right" style="width:100%" />
          <el-select v-else-if="f.type === 'select' || f.type === 'api-select' || f.type === 'map-select'"
            v-model="params[f.key]" :placeholder="f.placeholder || '请选择'" clearable filterable style="width:100%">
            <el-option v-for="o in optionsFor(f)" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-select v-else-if="f.type === 'multiselect'" v-model="params[f.key]" multiple clearable filterable
            collapse-tags collapse-tags-tooltip :placeholder="f.placeholder || '请选择'" style="width:100%">
            <el-option v-for="o in optionsFor(f)" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-radio-group v-else-if="f.type === 'radio'" v-model="params[f.key]">
            <el-radio v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</el-radio>
          </el-radio-group>
          <el-checkbox-group v-else-if="f.type === 'checkbox'" v-model="params[f.key]">
            <el-checkbox v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</el-checkbox>
          </el-checkbox-group>
          <el-date-picker v-else-if="f.type === 'daterange'" v-model="params[f.key]" type="daterange"
            value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期"
            style="width:100%" />
          <el-input v-else v-model="params[f.key]" :placeholder="f.placeholder || '请输入'" clearable />
        </div>
      </div>
    </div>
    <div class="qb-actions">
      <slot name="actions-left" />
      <el-button @click="doReset">{{ resetText }}</el-button>
      <el-button type="primary" :icon="Search" @click="doSearch">{{ searchText }}</el-button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'

const props = defineProps({
  fields: { type: Array, default: () => [] },
  modelValue: { type: Object, default: () => ({}) },
  searchText: { type: String, default: '查询' },
  resetText: { type: String, default: '重置' },
})
const emit = defineEmits(['update:modelValue', 'search', 'reset'])

const params = reactive({})
const apiOptions = ref({})

function emptyValue(f) {
  if (f.default !== undefined) return JSON.parse(JSON.stringify(f.default))
  if (f.type === 'multiselect' || f.type === 'checkbox') return []
  if (f.type === 'daterange') return null
  if (f.type === 'number') return undefined
  return ''
}

function initParams() {
  for (const f of props.fields) {
    const cur = props.modelValue?.[f.key]
    params[f.key] = cur !== undefined ? cur : emptyValue(f)
  }
}

function optionsFor(f) {
  if (f.type === 'map-select' && f.map) {
    return Object.entries(f.map).map(([value, label]) => ({ value, label }))
  }
  if (f.type === 'api-select') return apiOptions.value[f.key] || []
  return f.options || []
}

async function loadApiOptions() {
  for (const f of props.fields) {
    if (f.type !== 'api-select' || !f.api?.url) continue
    try {
      const r = await fetch(f.api.url)
      const data = await r.json()
      const list = Array.isArray(data) ? data : (data[f.api.listKey || 'items'] || data.data || [])
      const idKey = f.api.idKey || 'value1'
      const labelKey = f.api.labelKey || 'value2'
      apiOptions.value[f.key] = list.map(it => ({ value: it[idKey], label: it[labelKey] }))
    } catch {
      apiOptions.value[f.key] = []
    }
  }
}

function doSearch() {
  emit('update:modelValue', { ...params })
  emit('search', { ...params })
}

function doReset() {
  for (const f of props.fields) params[f.key] = emptyValue(f)
  emit('update:modelValue', { ...params })
  emit('reset', { ...params })   // 重置只清空条件，不触发查询
}

watch(() => props.modelValue, (v) => {
  if (!v) return
  for (const f of props.fields) {
    if (v[f.key] !== undefined && JSON.stringify(v[f.key]) !== JSON.stringify(params[f.key])) {
      params[f.key] = v[f.key]
    }
  }
}, { deep: true })

watch(() => props.fields, initParams, { deep: true })

onMounted(() => { initParams(); loadApiOptions() })
</script>

<style scoped>
.query-builder { padding: 14px 16px 10px; }
.qb-fields { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px 18px; }
.qb-field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.qb-label { font-size: 12px; color: var(--text-2); }
.qb-control { min-width: 0; }
.qb-actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-top: 12px; }
@media (max-width: 900px) { .qb-fields { grid-template-columns: repeat(2, 1fr); } }
</style>