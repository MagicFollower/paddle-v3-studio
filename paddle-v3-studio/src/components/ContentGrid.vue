<template>
  <div class="content-grid panel" :class="{ 'cg-fill': fillMode }">
    <div class="cg-table-wrap">
      <el-table :data="data" v-loading="loading" :row-key="rowKey" border stripe size="default"
        :empty-text="emptyText" style="width:100%" :height="fillMode ? '100%' : undefined"
        :max-height="fillMode ? undefined : maxHeight">
        <el-table-column v-if="selectable" type="selection" width="46" />
        <el-table-column v-if="index" type="index" label="#" width="56" align="center" />
        <el-table-column v-for="col in columns" :key="col.key" :prop="col.key" :label="col.label"
          :width="col.width" :min-width="col.minWidth || 100" :align="col.align || 'left'"
          :fixed="col.fixed" :show-overflow-tooltip="col.showOverflowTooltip !== false">
          <template #default="{ row }">
            <slot v-if="col.slot" :name="col.slot" :row="row" />
            <span v-else>{{ col.formatter ? col.formatter(row[col.key], row) : (row[col.key] ?? '—') }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="actions.length" label="操作" :width="actionWidth" fixed="right" align="center">
          <template #default="{ row }">
            <div class="cg-actions">
              <template v-for="act in actions" :key="act.label">
                <el-button v-if="!act.hidden || !act.hidden(row)" size="small" :type="act.type || 'primary'"
                  :link="act.link !== false" :disabled="act.disabled ? act.disabled(row) : false"
                  @click="act.onClick(row)">{{ act.label }}</el-button>
              </template>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div v-if="showPagination" class="cg-pager">
      <el-pagination :current-page="page" :page-size="pageSize" :page-sizes="pageSizes" :total="total"
        layout="total, sizes, prev, pager, next, jumper" background
        @update:current-page="onPage" @update:page-size="onSize" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  columns: { type: Array, default: () => [] },
  data: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 15 },
  showPagination: { type: Boolean, default: true },
  // bottom：Grid 顶满父级下区域、分页器跟随屏幕底部（默认）；inline：分页器跟随数据量
  paginationMode: { type: String, default: 'bottom' },
  pageSizes: { type: Array, default: () => [10, 15, 30, 50, 100, 200] },
  actions: { type: Array, default: () => [] },
  actionWidth: { type: [Number, String], default: 130 },
  rowKey: { type: String, default: 'id' },
  emptyText: { type: String, default: '暂无数据' },
  selectable: { type: Boolean, default: false },
  index: { type: Boolean, default: false },
  maxHeight: { type: [Number, String], default: undefined },
})
const emit = defineEmits(['update:page', 'update:pageSize', 'page-change'])

const fillMode = computed(() => props.paginationMode === 'bottom')

function onPage(p) {
  emit('update:page', p)
  emit('page-change', { page: p, pageSize: props.pageSize })
}
function onSize(s) {
  emit('update:pageSize', s)
  emit('update:page', 1)
  emit('page-change', { page: 1, pageSize: s })
}
</script>

<style scoped>
.content-grid { padding: 10px; display: flex; flex-direction: column; }
.cg-fill { flex: 1; min-height: 0; }
.cg-table-wrap { width: 100%; }
.cg-fill .cg-table-wrap { flex: 1; min-height: 0; }
.cg-actions { display: flex; gap: 4px; justify-content: center; flex-wrap: wrap; }
.cg-pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.cg-fill .cg-pager { flex-shrink: 0; margin-top: 10px; }
</style>