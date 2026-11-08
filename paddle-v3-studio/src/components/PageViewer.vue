<template>
  <div class="viewer panel">
    <div class="toolbar">
      <el-button-group size="small">
        <el-button :icon="ZoomOut" @click="zoom = Math.max(0.2, zoom - 0.2)" />
        <el-button @click="zoom = 1">{{ Math.round(zoom * 100) }}%</el-button>
        <el-button :icon="ZoomIn" @click="zoom = Math.min(4, zoom + 0.2)" />
        <el-button @click="fit = !fit; zoom = 1">{{ fit ? '原始大小' : '适应窗口' }}</el-button>
      </el-button-group>
      <span class="muted">{{ width }}×{{ height }} px</span>
      <span class="legend">
        <i class="dot" style="background: var(--layout-box)"></i>版面
        <i class="dot" style="background: var(--high)"></i>高置信
        <i class="dot" style="background: var(--review)"></i>需复核
        <i class="dot" style="background: var(--low)"></i>低置信
        <template v-if="marks">
          <i class="dot" style="background: var(--contract-no-box)"></i>合同号
          <i class="dot" style="background: var(--table-box)"></i>明细表格
        </template>
      </span>
    </div>
    <div class="stage" ref="stageRef">
      <div class="canvas" :style="canvasStyle">
        <img :src="src" @load="onLoad" draggable="false" />
        <div class="overlay">
          <template v-if="showLayout">
            <div v-for="(b, i) in layout" :key="'l' + i" class="box layout-box"
              :class="{ active: selected === 'l' + i }" :style="bboxStyle(b.bboxNorm)"
              :title="`${b.label} · ${b.score}`" @click.stop="$emit('select', 'l' + i)">
              <span class="tag">{{ b.label }} {{ (b.score * 100).toFixed(0) }}%</span>
            </div>
          </template>
          <template v-if="showOcr">
            <div v-for="(o, i) in ocr" :key="'o' + i" class="box ocr-box"
              :class="['tier-bg-' + o.tier, { active: selected === 'o' + i }]"
              :style="o.poly ? polyStyle(o.poly, width, height) : bboxStyle(o.bboxNorm)"
              :title="`${o.text} · ${o.confidence ?? '无置信度'}`" @click.stop="$emit('select', 'o' + i)" />
          </template>
          <template v-if="marks">
            <div v-if="marks.contractNo" class="box mark-no" :style="bboxStyle(marks.contractNo.bboxNorm)">
              <span class="tag">合同号 {{ marks.contractNo.number }}</span>
            </div>
            <div v-for="(t, i) in marks.tables" :key="'t' + i" class="box mark-table" :style="bboxStyle(t.bboxNorm)">
              <span class="tag">明细表 {{ t.entries?.length ?? 0 }} 行</span>
            </div>
          </template>
          <div v-if="activeRow" ref="activeRowRef" class="box active-row" :style="bboxStyle(activeRow)">
            <span class="tag">选中明细</span>
          </div>
          <div v-for="(r, i) in reviewRows" :key="'rv' + i" class="box review-row" :style="bboxStyle(r.rowBoxNorm)">
            <el-tooltip placement="top" effect="light" :visible="openReview === i">
              <template #content>
                <div class="review-tip">
                  <div v-for="f in REVIEW_FIELDS" :key="f.key"><b>{{ f.label }}</b>：{{ r.review?.[f.key] ?? '—' }}</div>
                </div>
              </template>
              <span class="review-badge" @mouseenter="openReview = i" @mouseleave="openReview = null"
                @click.stop="openReview = openReview === i ? null : i">审</span>
            </el-tooltip>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import { bboxStyle, polyStyle, REVIEW_FIELDS } from '../utils.js'
import { display } from '../display.js'

const props = defineProps({
  src: String, width: Number, height: Number,
  layout: { type: Array, default: () => [] },
  ocr: { type: Array, default: () => [] },
  marks: { type: Object, default: null },
  showLayout: { type: Boolean, default: true },
  showOcr: { type: Boolean, default: true },
  selected: String,
  activeRow: { type: Array, default: null },
  reviewRows: { type: Array, default: () => [] },
})
defineEmits(['select'])

const zoom = ref((display.default_zoom ?? 60) / 100)
const fit = ref(false)
const stageRef = ref(null)
const activeRowRef = ref(null)
const openReview = ref(null)
const stageW = ref(800)

function scrollToActive() {
  const el = activeRowRef.value, stage = stageRef.value
  if (!el || !stage) return
  const er = el.getBoundingClientRect(), sr = stage.getBoundingClientRect()
  const delta = (er.top - sr.top) - (stage.clientHeight / 2 - er.height / 2)
  stage.scrollTop = Math.max(0, stage.scrollTop + delta)
}

function onLoad() {
  if (stageRef.value) stageW.value = stageRef.value.clientWidth - 24
  nextTick(scrollToActive)
}

watch(() => props.activeRow, () => nextTick(scrollToActive))

const canvasStyle = computed(() => {
  const base = fit.value ? Math.min(1, stageW.value / (props.width || 1)) : 1
  const w = (props.width || 800) * base * zoom.value
  return { width: `${w}px`, height: `${(props.height || 600) * base * zoom.value}px` }
})
</script>

<style scoped>
.viewer { display: flex; flex-direction: column; min-height: 0; flex: 1; }
.toolbar { display: flex; gap: 12px; align-items: center; padding: 8px 10px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.legend { display: inline-flex; gap: 6px; align-items: center; font-size: 12px; color: var(--text-2); margin-left: auto; }
.dot { width: 10px; height: 10px; border-radius: 2px; display: inline-block; margin-left: 6px; }
.stage { flex: 1; overflow: auto; padding: 12px; background: #eceff3; min-height: 300px; }
.canvas { position: relative; margin: 0 auto; box-shadow: 0 1px 6px rgba(0,0,0,.15); }
.canvas img { width: 100%; height: 100%; display: block; user-select: none; }
.overlay { position: absolute; inset: 0; }
.box { position: absolute; cursor: pointer; }
.layout-box { border: 2px solid var(--layout-box); background: rgba(37,99,235,.06); }
.layout-box .tag { position: absolute; top: -18px; left: -2px; background: var(--layout-box); color: #fff; font-size: 10px; padding: 1px 5px; border-radius: 3px; white-space: nowrap; }
.ocr-box { border: 1px solid; }
.tier-bg-high { border-color: var(--high); background: rgba(22,163,74,.08); }
.tier-bg-review { border-color: var(--review); background: rgba(217,119,6,.10); }
.tier-bg-low { border-color: var(--low); background: rgba(220,38,38,.12); }
.tier-bg-none { border-color: var(--text-3); }
.box.active { outline: 2px solid #f59e0b; z-index: 5; }
.mark-no { border: 3px solid var(--contract-no-box); background: rgba(220,38,38,.08); z-index: 6; }
.mark-no .tag { position: absolute; top: -20px; left: -3px; background: var(--contract-no-box); color: #fff; font-size: 11px; padding: 1px 6px; border-radius: 3px; white-space: nowrap; }
.mark-table { border: 3px solid var(--table-box); background: rgba(124,58,237,.05); }
.mark-table .tag { position: absolute; top: -20px; left: -3px; background: var(--table-box); color: #fff; font-size: 11px; padding: 1px 6px; border-radius: 3px; white-space: nowrap; }
.active-row { border: 2px solid #f59e0b; background: rgba(245,158,11,.30); z-index: 9; box-shadow: 0 0 0 2px rgba(245,158,11,.45); pointer-events: none; }
.active-row .tag { position: absolute; top: -20px; left: -2px; background: #f59e0b; color: #fff; font-size: 11px; padding: 1px 6px; border-radius: 3px; white-space: nowrap; }
.review-row { border: 1px dashed var(--match-ok); background: rgba(22,163,74,.06); z-index: 8; pointer-events: none; }
.review-badge { position: absolute; top: -10px; right: -8px; width: 18px; height: 18px; border-radius: 50%; background: var(--match-ok); color: #fff; font-size: 11px; display: flex; align-items: center; justify-content: center; cursor: pointer; pointer-events: auto; box-shadow: 0 0 0 2px #fff; }
.review-tip { line-height: 1.8; font-size: 12px; max-width: 320px; }
.review-tip b { color: var(--brand); margin-right: 4px; }
</style>