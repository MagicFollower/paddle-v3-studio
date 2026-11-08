<template>
  <el-container class="shell">
    <el-header class="topbar panel">
      <div class="brand">
        <span class="logo">V3</span>
        <div>
          <div class="title">Paddle V3 版面分析与 OCR 工作台</div>
          <div class="muted">PP-DocLayoutV3 · PP-OCRv5 · SLANeXt · 离线模型</div>
        </div>
      </div>
      <div class="status">
        <el-tooltip :content="deviceTip" placement="bottom">
          <el-tag :type="deviceTagType" size="small" effect="plain">{{ deviceLabel }}</el-tag>
        </el-tooltip>
        <el-tag :type="dead ? 'danger' : 'success'" size="small" effect="plain">
          {{ dead ? '后端不可达' : '后端在线' }}
        </el-tag>
        <el-button size="small" text :icon="Refresh" @click="refresh">刷新</el-button>
      </div>
    </el-header>
    <el-container class="body">
      <el-aside width="168px" class="nav panel">
        <el-menu :default-active="view" @select="view = $event">
          <el-menu-item index="images"><el-icon><Picture /></el-icon>图片解析</el-menu-item>
          <el-menu-item index="contracts"><el-icon><Document /></el-icon>合同校验</el-menu-item>
          <el-menu-item index="settings"><el-icon><Setting /></el-icon>系统设置</el-menu-item>
        </el-menu>
        <div class="nav-foot muted">
          上传 → 版面检测 → OCR<br />置信度三档 → 合同对照校验
        </div>
      </el-aside>
      <el-main class="main">
        <ImageParse v-if="view === 'images'" />
        <ContractCheck v-else-if="view === 'contracts'" />
        <SettingsView v-else />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Picture, Document, Setting, Refresh } from '@element-plus/icons-vue'
import { api } from './api.js'
import { loadDisplay } from './display.js'
import ImageParse from './views/ImageParse.vue'
import ContractCheck from './views/ContractCheck.vue'
import SettingsView from './views/SettingsView.vue'

const view = ref('images')
const dead = ref(false)
const modelStatus = ref(null)
let timer = null

const deviceLabel = computed(() => {
  const d = modelStatus.value?.device
  if (!d) return '设备未知'
  if (d.device === 'gpu') return `GPU · ${d.device_name || ''}`
  return d.fallback ? 'CPU（GPU 降级）' : 'CPU'
})
const deviceTagType = computed(() => {
  const d = modelStatus.value?.device
  if (!d) return 'info'
  if (d.device === 'gpu') return 'success'
  return d.fallback ? 'warning' : 'info'
})
const deviceTip = computed(() => {
  const d = modelStatus.value?.device
  if (!d) return '尚未探测'
  return d.reason || `Paddle ${d.paddle_version || ''} · 请求 ${d.requested}`
})

async function refresh() {
  try {
    await api.health()
    dead.value = false
    modelStatus.value = await api.modelStatus()
  } catch {
    dead.value = true
  }
}

onMounted(() => { refresh(); loadDisplay(); timer = setInterval(refresh, 15000) })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.shell { height: 100%; }
.topbar { display: flex; align-items: center; justify-content: space-between; height: 60px; margin: 10px 10px 0; padding: 0 16px; }
.brand { display: flex; gap: 10px; align-items: center; }
.logo { background: var(--brand); color: #fff; border-radius: 8px; font-weight: 700; padding: 6px 9px; font-size: 15px; }
.title { font-weight: 600; font-size: 15px; }
.status { display: flex; gap: 8px; align-items: center; }
.body { padding: 10px; gap: 10px; min-height: 0; }
.nav { padding: 6px 0; display: flex; flex-direction: column; }
.nav .el-menu { border-right: none; }
.nav-foot { margin-top: auto; padding: 12px; line-height: 1.7; }
.main { padding: 0; min-width: 0; display: flex; flex-direction: column; }
</style>