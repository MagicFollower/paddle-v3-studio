<template>
  <div class="page" ref="pageEl">
    <div class="side panel">
      <div class="side-head">
        <el-upload :show-file-list="false" :http-request="doUpload" accept=".docx,.doc,.pdf">
          <el-button type="primary" :icon="Upload" :loading="uploading" :disabled="busy" size="small">上传合同 docx/pdf</el-button>
        </el-upload>
        <div class="muted">一个文件 = 一个条目，逐页转图识别</div>
      </div>
      <el-scrollbar class="doc-list">
        <div v-for="c in contracts" :key="c.id" class="doc-item" :data-id="c.id" :class="{ on: c.id === currentId }" @click="openContract(c)">
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
          <el-button size="small" :icon="Refresh" @click="reverify" :loading="reverifying" :disabled="busy">重新校验</el-button>
          <el-tooltip placement="top" effect="light">
            <template #content>
              <div class="help-tip">
                <div class="help-line"><b>作用</b> 只重跑「对照数据源」校验，不重新转图与 OCR 推理。</div>
                <div class="help-line"><b>流程</b> 读取已解析产物 extracted → 调数据源 API 取合同与明细 → 合同号/逐行数量单价金额比对 → 更新校验报告。</div>
                <div class="help-line"><b>适用</b> 数据源补录或修改后快速复校，秒级完成。</div>
              </div>
            </template>
            <el-icon class="help-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
          <el-button size="small" :icon="Refresh" @click="reparse" :disabled="busy">{{ current.status === 'parsed' ? '重新解析' : '解析' }}</el-button>
          <el-tooltip placement="top" effect="light">
            <template #content>
              <div class="help-tip">
                <div class="help-line"><b>作用</b> 重新执行完整解析与校验全流程。</div>
                <div class="help-line"><b>流程</b> 转图(convert) → 逐页 V3 推理(predict) → 合同号与明细提取(extract) → 对照数据源校验(verify) → 产物落盘(persist)。</div>
                <div class="help-line"><b>适用</b> 文件本身或解析/识别参数变化后，需重新 OCR 时使用。</div>
              </div>
            </template>
            <el-icon class="help-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
          <el-button size="small" :icon="MagicStick" @click="runLlmMap" :loading="llmMapping" :disabled="busy || !payload">LLM映射</el-button>
          <el-tooltip placement="top" effect="light">
            <template #content>
              <div class="help-tip">
                <div class="help-line"><b>作用</b> 用本地离线大模型把明细中文表头识别为「字段映射」页配置的业务英文字段，输出新 Json。</div>
                <div class="help-line"><b>流程</b> 读已解析 extracted → llama serve（GPU 优先，无则 CPU）识别表头 → 确定性重写键名 → 存 mapped。</div>
                <div class="help-line"><b>适用</b> 映射配置或模型变化后单独重跑，不必重新 OCR。结果见「业务字段(LLM)」tab。</div>
              </div>
            </template>
            <el-icon class="help-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
          <el-button size="small" :icon="Delete" type="danger" plain @click="removeContract" :disabled="busy">删除</el-button>
        </div>
      </div>

      <div class="split" v-if="payload" ref="splitRef">
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
            :marks="marksForPage" :show-layout="display.show_layout"
            :selected="selected" :active-row="activeRowForPage" :review-rows="reviewRowsForPage"
            @select="id => selected = id" />
        </div>

        <div class="splitter" title="拖动调整右栏宽度" @mousedown="startDrag"></div>
        <div class="right panel" :style="{ width: rightWidth + 'px' }">
          <el-tabs v-model="rtab" class="rtabs">
          <el-tab-pane label="校验详情" name="detail">
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
              <div class="hint-block">
                流程：先精确判别表格规范性 → <b>规则表格</b>（标准/合并表头/分节）走启发式精确解析；
                <b>不规则表格</b>（键值对/转置/无表头）动态调用 <b>4B LLM 规范化</b>为标准行列，再<b>复用正规解析</b>
                （规范化无效时回退结构理解兜底）。下方按表标注实际路径与形态，可审计规范化结果。
              </div>
              <div v-for="(t, ti) in extracted?.tables || []" :key="ti" class="table-block" :class="{ irregular: t.regular === false }">
                <div class="table-meta">
                  <span class="muted">第 {{ t.page }} 页表格 · {{ t.entries.length }} 条明细<span v-if="t.totalRow"> · {{ t.totalRow.text }}</span></span>
                  <el-tag size="small" :type="t.method === 'heuristic' ? 'success' : 'warning'" effect="dark">
                    {{ METHOD_LABEL[t.method] || t.method }}
                  </el-tag>
                  <el-tag size="small" effect="plain">{{ LAYOUT_LABEL[t.layout] || t.layout || '标准表' }}</el-tag>
                  <el-tag size="small" :type="t.regular === false ? 'danger' : 'info'" effect="plain">
                    {{ t.regular === false ? '不规则' : '规则' }}
                  </el-tag>
                </div>
                <div v-if="t.regular === false" class="irregular-hint">
                  不规则表格（{{ (t.regularityReasons || []).join('；') }}）→ {{ t.method === 'llm-normalize' ? '经 4B 规范化为标准行列后复用正规解析' : '经 4B 结构理解兜底抽取' }}，结果供人工复核。
                </div>
                <el-table :data="t.entries" size="small" border max-height="260" highlight-current-row
                  :row-class-name="rawRowClass" :cell-class-name="cellClass" @row-click="(row) => selectEntry(t, row)">
                  <el-table-column prop="name" label="品名" min-width="110" show-overflow-tooltip />
                  <el-table-column prop="spec" label="规格" min-width="80" show-overflow-tooltip />
                  <el-table-column prop="qtyText" label="数量" width="70" />
                  <el-table-column prop="priceText" label="单价" width="80" />
                  <el-table-column prop="amountText" label="金额" width="90" />
                </el-table>
                <el-collapse v-if="t.normalizedHtml" class="norm-audit">
                  <el-collapse-item title="查看 4B 规范化后的标准表格（审计中间产物）">
                    <table class="norm-table">
                      <tr v-for="(row, ri) in normalizedGrid(t.normalizedHtml)" :key="ri">
                        <component :is="ri === 0 ? 'th' : 'td'" v-for="(c, ci) in row" :key="ci">{{ c }}</component>
                      </tr>
                    </table>
                  </el-collapse-item>
                </el-collapse>
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
                <div v-for="(r, i) in report.itemComparison" :key="i" class="cmp-card"
                  :class="{ bad: !r.fields.every(f => f.ok), clickable: !!r.ocr }"
                  :title="r.ocr ? '点击跳转到页面中该条目' : ''" @click="r.ocr && jumpToEntry(r.ocr)">
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
          </el-tab-pane>
          <el-tab-pane :label="`OCR文本 (${pageData?.ocr?.length || 0})`" name="ocr">
            <el-scrollbar height="100%">
              <div class="conf-summary" v-if="pageData?.ocr?.length">
                <el-tag type="success" size="small" effect="plain">高 {{ tierCount.high }}</el-tag>
                <el-tag type="warning" size="small" effect="plain">复核 {{ tierCount.review }}</el-tag>
                <el-tag type="danger" size="small" effect="plain">低 {{ tierCount.low }}</el-tag>
                <span class="muted">第 {{ pageNo }} 页 · 共 {{ pageData.ocr.length }} 行</span>
              </div>
              <div v-for="(o, i) in pageData?.ocr || []" :key="i" class="ocr-card"
                :class="{ on: selected === 'o' + i }" @click="selectOcr(i)">
                <span class="ocr-text">{{ o.text }}</span>
                <el-tag :type="o.tier === 'high' ? 'success' : o.tier === 'review' ? 'warning' : o.tier === 'low' ? 'danger' : 'info'" size="small">
                  {{ o.confidence ?? '—' }}
                </el-tag>
              </div>
              <el-empty v-if="!pageData?.ocr?.length" description="本页无 OCR 结果" :image-size="60" />
            </el-scrollbar>
          </el-tab-pane>
          <el-tab-pane label="合同明细" name="items">
            <el-scrollbar height="100%">
              <div class="items-bar">
                <el-button size="small" :icon="CopyDocument" @click="copyJson">复制为Json</el-button>
                <el-upload :show-file-list="false" :http-request="doImportReview" accept=".json,application/json">
                  <el-button size="small" :icon="Upload">导入Json</el-button>
                </el-upload>
                <el-tag v-if="reviewData" size="small" type="warning" effect="plain">已导入回填Json</el-tag>
              </div>
              <div class="sec-title">合同号（归一化）</div>
              <div class="mono no-text">{{ normalizedNo?.number || '—' }}</div>
              <div class="sec-title" style="margin-top:10px">明细（归一化：去空白/去逗号/去冗余0）</div>
              <el-table :data="normalizedEntries" size="small" border max-height="340" highlight-current-row
                :cell-class-name="cellClass" :row-class-name="normRowClass" @row-click="(row) => jumpToEntry(row)">
                <el-table-column prop="name" label="品名" min-width="110" show-overflow-tooltip />
                <el-table-column prop="spec" label="规格" min-width="80" show-overflow-tooltip />
                <el-table-column prop="unit" label="单位" width="60" />
                <el-table-column prop="qty" label="数量" width="70" />
                <el-table-column prop="price" label="单价" width="80" />
                <el-table-column prop="amount" label="金额" width="90" />
                <el-table-column v-if="anyReview" label="审核标记" width="90" align="center">
                  <template #default="{ row }">
                    <el-tooltip v-if="hasReview(row.review)" placement="top" effect="light">
                      <template #content>
                        <div class="help-tip">
                          <div v-for="f in REVIEW_FIELDS" :key="f.key">{{ f.label }}：{{ row.review?.[f.key] ?? '—' }}</div>
                        </div>
                      </template>
                      <el-tag size="small" type="warning">已审核</el-tag>
                    </el-tooltip>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-if="!normalizedEntries.length" description="暂无明细（未解析或无表格）" :image-size="50" />
            </el-scrollbar>
          </el-tab-pane>
          <el-tab-pane :label="`错误明细清单 (${errorEntries.length})`" name="errors">
            <el-scrollbar height="100%">
              <el-table :data="errorEntries" size="small" border>
                <el-table-column prop="name" label="品名" width="110" show-overflow-tooltip />
                <el-table-column prop="page" label="页" width="50" align="center" />
                <el-table-column label="错误字段" width="180" show-overflow-tooltip>
                  <template #default="{ row }"><span class="err-detail">{{ errDetail(row) }}</span></template>
                </el-table-column>
                <el-table-column label="初审" width="70">
                  <template #default="{ row }">{{ row.review?.firstReviewer || '—' }}</template>
                </el-table-column>
                <el-table-column label="审核" width="70">
                  <template #default="{ row }">{{ row.review?.reviewer || '—' }}</template>
                </el-table-column>
                <el-table-column label="操作" :width="opColWidth" align="center">
                  <template #default="{ row }">
                    <el-button link type="primary" size="small" @click="jumpToEntry(row)">跳转</el-button>
                    <el-button link type="warning" size="small" :disabled="firstBtnDisabled(row)" @click="onFirstClick(row)">{{ firstBtnLabel(row) }}</el-button>
                    <el-button link type="success" size="small" :disabled="auditBtnDisabled(row)"
                      :class="{ 'audit-disabled': auditBtnDisabled(row) }" @click="onAuditClick(row)">{{ auditBtnLabel(row) }}</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-if="!errorEntries.length" description="无错误明细（全部与数据源一致）" :image-size="50" />
            </el-scrollbar>
          </el-tab-pane>
          <el-tab-pane label="业务字段(LLM)" name="llm">
            <el-scrollbar height="100%">
              <div class="items-bar">
                <el-button size="small" :icon="CopyDocument" @click="copyMappedJson" :disabled="!mappedData">复制为Json</el-button>
                <el-button size="small" :icon="MagicStick" @click="runLlmMap" :loading="llmMapping" :disabled="busy">重新映射</el-button>
                <el-tag v-if="mappedData?.status === 'ok'" size="small" type="success" effect="plain">
                  {{ mappedData.method === 'llm' ? 'LLM 映射' : '映射' }} · {{ mappedData.engine || '' }} · {{ mappedData.entryCount }} 条
                </el-tag>
                <el-tag v-else-if="mappedData?.status === 'skipped'" size="small" type="warning" effect="plain">已跳过</el-tag>
              </div>
              <el-alert v-if="mappedData?.status === 'skipped'" type="warning" :closable="false" show-icon
                :title="mappedData.reason || '尚未运行 LLM 映射'" :description="mappedData.hint || '点上方「重新映射」启动本地大模型转换。'" style="margin-bottom:10px" />
              <template v-if="mappedData?.status === 'ok'">
                <div class="sec-title">表头 → 业务字段（模型识别）</div>
                <div class="header-map">
                  <span v-for="(fld, h) in mappedData.headerMap" :key="h" class="hm-item">
                    <span class="hm-h">{{ h }}</span><span class="hm-arrow">→</span><span class="mono hm-f">{{ fld }}</span>
                  </span>
                  <span v-if="!Object.keys(mappedData.headerMap || {}).length" class="muted">无</span>
                </div>
                <div class="sec-title" style="margin-top:10px">业务字段明细（英文缩写键名）</div>
                <el-table :data="mappedData.entries" size="small" border max-height="360" highlight-current-row
                  @row-click="(row) => jumpToEntry(row)">
                  <el-table-column v-for="f in mappedData.fields" :key="f.field" :prop="f.field" :label="`${f.label} (${f.field})`"
                    min-width="100" show-overflow-tooltip />
                  <el-table-column prop="page" label="页" width="50" align="center" />
                </el-table>
                <el-empty v-if="!mappedData.entries?.length" description="无明细条目" :image-size="50" />
              </template>
              <el-empty v-else-if="!mappedData" description="尚未运行 LLM 映射 · 点「重新映射」开始" :image-size="50" />
            </el-scrollbar>
          </el-tab-pane>
          </el-tabs>
        </div>
      </div>
      <el-empty v-else-if="current.status === 'parsing'" description="正在转换与识别…" class="panel empty" />
      <el-empty v-else-if="current.status === 'uploaded'" description="尚未解析（自动解析已关闭）· 点击右上角「解析」开始识别" class="panel empty" />
      <el-empty v-else-if="current.status === 'failed'" description="解析失败 · 点击右上角「解析」重试" class="panel empty" />
    </div>
    <el-empty v-else description="上传或选择一个合同条目" class="panel empty" />
    <el-dialog v-model="reviewDialog" :title="reviewMode === 'first' ? '初审回填' : '审核回填'" width="420px">
      <el-form label-width="90px">
        <template v-if="reviewMode === 'first'">
          <el-form-item label="初审核人"><el-input v-model="reviewForm.firstReviewer" placeholder="必填" /></el-form-item>
          <el-form-item label="初审核时间"><el-input v-model="reviewForm.firstReviewTime" /></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="审核人"><el-input v-model="reviewForm.reviewer" placeholder="必填" /></el-form-item>
          <el-form-item label="审核时间"><el-input v-model="reviewForm.reviewTime" /></el-form-item>
        </template>
        <el-form-item v-if="reviewMode === 'first'" label="初审备注"><el-input v-model="reviewForm.firstRemark" type="textarea" :rows="2" /></el-form-item>
        <el-form-item v-else label="审核备注"><el-input v-model="reviewForm.reviewRemark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmReview">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Refresh, Delete, CircleCheck, CircleClose, QuestionFilled, CopyDocument, MagicStick } from '@element-plus/icons-vue'
import { api } from '../api.js'
import { display, setDisplay } from '../display.js'
import { formatBytes, VERIFY_LABEL, VERIFY_TYPE, cleanText, cleanNumber, REVIEW_FIELDS, hasReview } from '../utils.js'
import PageViewer from '../components/PageViewer.vue'

const FIELD_LABEL = { itemName: '品名', name: '品名', quantity: '数量', unitPrice: '单价', amount: '金额' }
const LAYOUT_LABEL = { standard: '标准表', 'merged-header': '合并表头/分节', transposed: '转置表', 'key-value': '键值对表', headerless: '无表头', empty: '空表' }
const METHOD_LABEL = { heuristic: '启发式精确解析', 'llm-normalize': '4B 规范化→复用解析', 'llm-table': '4B 结构理解兜底' }
// 安全地把规范化 HTML 解析为纯文本二维表（DOMParser textContent，杜绝 XSS），供审计视图渲染
function normalizedGrid(html) {
  if (!html) return []
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    return [...doc.querySelectorAll('tr')].map(tr => [...tr.querySelectorAll('td,th')].map(td => td.textContent.trim()))
  } catch { return [] }
}
const SOURCE_LABEL = { 'same-line': '单行', 'next-line': '多行(下行)', 'split-line': '多行(折行)' }

const contracts = ref([])
const currentId = ref(null)
const current = ref(null)
const payload = ref(null)
const job = ref(null)
const pageNo = ref(1)
const uploading = ref(false)
const reverifying = ref(false)
const llmMapping = ref(false)
const rtab = ref('detail')
const selected = ref(null)
const activeEntry = ref(null)
const reviewData = ref(null)
let poll = null

// 右栏宽度拖拽调整（持久化到 localStorage）
const splitRef = ref(null)
const rightWidth = ref(Number(localStorage.getItem('ccRightWidth')) || 430)
function startDrag(e) {
  e.preventDefault()
  const move = (ev) => {
    const rect = splitRef.value?.getBoundingClientRect()
    if (!rect) return
    rightWidth.value = Math.max(320, Math.min(rect.width - 320, rect.right - ev.clientX))
  }
  const up = () => {
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
    localStorage.setItem('ccRightWidth', String(Math.round(rightWidth.value)))
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}
// 错误清单最后一列(操作)宽度 = 右栏宽 - 内边距/边框 - 其余固定列(480)，随拖拽自适应；下限 170
const opColWidth = computed(() => Math.max(170, rightWidth.value - 22 - 480))

const extracted = computed(() => payload.value?.extracted)
const report = computed(() => payload.value?.report)
const mappedData = computed(() => payload.value?.mapped || null)
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
const activeRowForPage = computed(() =>
  activeEntry.value && activeEntry.value.page === pageNo.value ? activeEntry.value.box : null)
const tierCount = computed(() => {
  const c = { high: 0, review: 0, low: 0, none: 0 }
  for (const o of pageData.value?.ocr || []) if (c[o.tier] !== undefined) c[o.tier]++
  return c
})
// 合同明细二次解析：优先用导入的回填 JSON（含特殊标记），否则由解析产物归一化生成
const detailJson = computed(() => {
  if (reviewData.value && Array.isArray(reviewData.value.entries)) return reviewData.value
  const ex = extracted.value
  if (!ex) return null
  const entries = []
  for (const t of ex.tables || []) {
    for (const e of t.entries || []) {
      entries.push({
        no: cleanText(e.no), name: cleanText(e.name), spec: cleanText(e.spec), unit: cleanText(e.unit),
        qty: cleanNumber(e.qtyText ?? e.qty), price: cleanNumber(e.priceText ?? e.price),
        amount: cleanNumber(e.amountText ?? e.amount),
        page: t.page, rowBoxNorm: e.rowBoxNorm || null, tableBboxNorm: t.bboxNorm || null,
      })
    }
  }
  const no = ex.contractNo || {}
  return {
    contractId: currentId.value,
    contractNo: { number: cleanText(no.number), page: no.page ?? null, bbox: no.bbox || null, bboxNorm: no.bboxNorm || null },
    entries,
  }
})
const normalizedEntries = computed(() => detailJson.value?.entries || [])
const normalizedNo = computed(() => detailJson.value?.contractNo || null)
const anyReview = computed(() => normalizedEntries.value.some(e => hasReview(e.review)))
const reviewRowsForPage = computed(() => normalizedEntries.value
  .filter(e => e.page === pageNo.value && e.rowBoxNorm && hasReview(e.review))
  .map(e => ({ rowBoxNorm: e.rowBoxNorm, review: e.review, name: e.name })))
const stageLabel = computed(() => {
  const s = job.value?.stages?.find(x => x.key === job.value?.stage)
  return s?.label || job.value?.stage || ''
})
const busy = computed(() =>
  (!!job.value && ['queued', 'running'].includes(job.value.status))
  || current.value?.status === 'parsing'
  || uploading.value)

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
  activeEntry.value = null
  selected.value = null
  reviewData.value = null
  try {
    current.value = await api.contract(c.id)
    if (current.value.status === 'parsed') payload.value = await api.contractResult(c.id)
    const rv = await api.contractReview(c.id)
    reviewData.value = (rv && Array.isArray(rv.entries)) ? rv : null
    job.value = (await api.jobs(c.id)).items[0] || null
    watchJob()
  } catch (e) { ElMessage.error(e.message) }
}

function watchJob() {
  clearInterval(poll)
  const self = setInterval(async () => {
    if (poll !== self) { clearInterval(self); return }   // 已被新轮询取代
    if (!currentId.value) return
    try {
      const j = (await api.jobs(currentId.value)).items[0]
      if (!j || poll !== self) return
      job.value = j
      current.value = await api.contract(currentId.value)
      if (poll !== self) return
      if (j.status === 'done') {
        clearInterval(self)
        payload.value = await api.contractResult(currentId.value)
        await loadContracts()
      } else if (j.status === 'failed') {
        clearInterval(self)
        await loadContracts()
      }
    } catch {}
  }, 1500)
  poll = self
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
    const r = await api.reparseContract(currentId.value)
    payload.value = null
    current.value.status = 'parsing'
    job.value = { id: r.jobId, status: 'queued', progress: 0, stages: [] }
    watchJob()
  } catch (e) { ElMessage.error(e.message) }
}

async function runLlmMap() {
  if (!currentId.value || !payload.value) return
  llmMapping.value = true
  try {
    const r = await api.llmMapContract(currentId.value)
    payload.value = { ...payload.value, mapped: r }
    rtab.value = 'llm'
    if (r.status === 'ok') ElMessage.success(`LLM 映射完成：${r.entryCount} 条（${(r.device || '').toUpperCase()}）`)
    else ElMessage.warning(`映射跳过：${r.reason || ''}`)
  } catch (e) { ElMessage.error(e.message) } finally { llmMapping.value = false }
}

async function copyMappedJson() {
  if (!mappedData.value) { ElMessage.warning('暂无可复制的映射结果'); return }
  try {
    await navigator.clipboard.writeText(JSON.stringify(mappedData.value, null, 2))
    ElMessage.success('业务字段 Json 已复制')
  } catch { ElMessage.error('复制失败（浏览器不允许写剪贴板）') }
}

async function removeContract() {
  try {
    await ElMessageBox.confirm(`删除合同条目 ${current.value.name}？`, '删除确认', { type: 'warning' })
    await api.deleteContract(currentId.value)
    current.value = null; currentId.value = null; payload.value = null
    await loadContracts()
  } catch {}
}

function estimateRowBox(t, idx) {
  const b = t.bboxNorm
  if (!b || idx == null || !t.entries?.length) return null
  const first = (extracted.value?.tables || [])[0]
  const hasHeader = !first || t.page === first.page   // 首块表格带表头，跨页续表不带
  const rows = t.entries.length + (hasHeader ? 1 : 0)
  const h = (b[3] - b[1]) / rows
  const off = hasHeader ? 1 : 0
  return [b[0], b[1] + (idx + off) * h, b[2], b[1] + (idx + off + 1) * h]
}

function selectEntry(t, row) {
  const idx = t.entries.indexOf(row)
  if (idx < 0) return
  pageNo.value = t.page
  activeEntry.value = { page: t.page, box: row.rowBoxNorm || estimateRowBox(t, idx), key: `${t.page}-${idx}` }
}

// ===== 校验错误红标 + 跳转 =====
// itemComparison 按数据源顺序排列（非明细顺序），但每个匹配行带 row.ocr（原始条目，含 page/rowBoxNorm），
// 故以「page+行坐标」为键把对照行映射回明细条目（归一化条目保留 rowBoxNorm，键不变）。
const CMP_FIELD_BY_PROP = {
  name: 'itemName', qtyText: 'quantity', qty: 'quantity',
  priceText: 'unitPrice', price: 'unitPrice', amountText: 'amount', amount: 'amount',
}
function entryKey(e) {
  return `${e.page}|${e.rowBoxNorm ? e.rowBoxNorm.join(',') : (e.no ?? e.name)}`
}
const cmpByKey = computed(() => {
  const m = {}
  for (const r of report.value?.itemComparison || []) if (r.ocr) m[entryKey(r.ocr)] = r
  return m
})
function badFields(e) {
  const r = cmpByKey.value[entryKey(e)]
  return r ? r.fields.filter(f => !f.ok).map(f => f.field) : []
}
function isRowBad(e) {
  const r = cmpByKey.value[entryKey(e)]
  return !!r && (!r.matched || r.fields.some(f => !f.ok))
}
function cellClass({ row, column }) {
  const f = CMP_FIELD_BY_PROP[column.property]
  return f && badFields(row).includes(f) ? 'cell-bad' : ''
}
function rawRowClass({ row }) {
  return 'entry-row' + (isRowBad(row) ? ' row-bad' : '')
}
function normRowClass({ row }) {
  return isRowBad(row) ? 'row-bad' : ''
}
function jumpToEntry(e) {
  if (!e || e.page == null) return
  pageNo.value = e.page
  let box = e.rowBoxNorm
  if (!box) {
    const t = (extracted.value?.tables || []).find(x => x.page === e.page)
    if (t) box = estimateRowBox(t, t.entries.findIndex(x => entryKey(x) === entryKey(e)))
  }
  activeEntry.value = { page: e.page, box, key: entryKey(e) }
}

// ===== 错误明细清单 + 初审/审核回填 =====
const errorEntries = computed(() => normalizedEntries.value.filter(e => isRowBad(e)))
function errDetail(e) {
  const r = cmpByKey.value[entryKey(e)]
  if (!r) return '未匹配'
  const bad = r.fields.filter(f => !f.ok)
  return bad.map(f => `${FIELD_LABEL[f.field] || f.field}: 源${f.source ?? '—'}/文件${f.ocr ?? '—'}`).join('；') || '未匹配数据源'
}
function hasFirstReview(e) {
  return !!(e.review && (e.review.firstReviewer || e.review.firstReviewTime))
}
function hasFinalReview(e) {
  return !!(e.review && (e.review.reviewer || e.review.reviewTime))
}
// 按钮状态机：未初审→[初审][审核置灰]；初审后→[取消初审][审核]；审核后→[初审禁用][取消审核]
function firstBtnLabel(e) { return hasFirstReview(e) ? '取消初审' : '初审' }
function firstBtnDisabled(e) { return hasFinalReview(e) }
function auditBtnLabel(e) { return hasFinalReview(e) ? '取消审核' : '审核' }
function auditBtnDisabled(e) { return !hasFirstReview(e) }
function onFirstClick(e) { hasFirstReview(e) ? cancelReview(e, 'first') : openReview(e, 'first') }
function onAuditClick(e) { hasFinalReview(e) ? cancelReview(e, 'final') : openReview(e, 'final') }
async function removeReviewFields(key, keys) {
  const base = JSON.parse(JSON.stringify(detailJson.value || { contractId: currentId.value, entries: [] }))
  const t = (base.entries || []).find(e => entryKey(e) === key)
  if (t && t.review) {
    for (const k of keys) delete t.review[k]
    if (!Object.keys(t.review).length) delete t.review
  }
  await api.saveContractReview(currentId.value, base)
  reviewData.value = base
}
async function cancelReview(e, mode) {
  const label = mode === 'first' ? '初审' : '审核'
  try {
    await ElMessageBox.confirm(`确认取消该条目的${label}标记？`, '取消确认', { type: 'warning' })
  } catch { return }
  try {
    const keys = mode === 'first'
      ? ['firstReviewer', 'firstReviewTime', 'firstRemark']
      : ['reviewer', 'reviewTime', 'reviewRemark']
    await removeReviewFields(entryKey(e), keys)
    ElMessage.success(`已取消${label}`)
  } catch (err) { ElMessage.error(err.message) }
}
const reviewDialog = ref(false)
const reviewMode = ref('first')
const reviewTarget = ref(null)
const reviewForm = ref({})
function nowStr() {
  const d = new Date(), p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function openReview(row, mode) {
  reviewTarget.value = entryKey(row)
  reviewMode.value = mode
  reviewForm.value = mode === 'first'
    ? { firstReviewer: row.review?.firstReviewer || '', firstReviewTime: row.review?.firstReviewTime || nowStr(), firstRemark: row.review?.firstRemark || '' }
    : { reviewer: row.review?.reviewer || '', reviewTime: row.review?.reviewTime || nowStr(), reviewRemark: row.review?.reviewRemark || '' }
  reviewDialog.value = true
}
async function saveReviewMarkers(key, fields) {
  const base = JSON.parse(JSON.stringify(detailJson.value || { contractId: currentId.value, entries: [] }))
  const target = (base.entries || []).find(e => entryKey(e) === key)
  if (target) target.review = { ...(target.review || {}), ...fields }
  await api.saveContractReview(currentId.value, base)
  reviewData.value = base
}
async function confirmReview() {
  const personKey = reviewMode.value === 'first' ? 'firstReviewer' : 'reviewer'
  if (!reviewForm.value[personKey]) { ElMessage.warning(reviewMode.value === 'first' ? '请填写初审核人' : '请填写审核人'); return }
  try {
    await ElMessageBox.confirm(`确认将${reviewMode.value === 'first' ? '初审' : '审核'}标记回填到合同明细 Json？`, '二次确认', { type: 'warning' })
  } catch { return }
  try {
    await saveReviewMarkers(reviewTarget.value, { ...reviewForm.value })
    reviewDialog.value = false
    ElMessage.success('已回填审核标记')
  } catch (e) { ElMessage.error(e.message) }
}

function selectOcr(i) {
  selected.value = 'o' + i
  if (!display.show_ocr) display.show_ocr = true
}

async function copyJson() {
  if (!detailJson.value) { ElMessage.warning('暂无可复制的明细'); return }
  try {
    await navigator.clipboard.writeText(JSON.stringify(detailJson.value, null, 2))
    ElMessage.success('合同明细 Json 已复制（含位置信息）')
  } catch { ElMessage.error('复制失败（浏览器不允许写剪贴板）') }
}

async function doImportReview({ file }) {
  try {
    const data = JSON.parse(await file.text())
    if (!data || !Array.isArray(data.entries)) { ElMessage.error('Json 需含 entries 数组'); return }
    await api.saveContractReview(currentId.value, data)
    reviewData.value = data
    ElMessage.success('已导入回填 Json，特殊标记已显示')
  } catch (e) { ElMessage.error(`导入失败：${e.message}`) }
}

onMounted(loadContracts)
onUnmounted(() => clearInterval(poll))

const props = defineProps({ autoOpenId: { type: String, default: null } })
const emit = defineEmits(['opened'])
const pageEl = ref(null)

function scrollToCurrent() {
  const el = pageEl.value?.querySelector(`.doc-item[data-id="${currentId.value}"]`)
  if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

watch(() => props.autoOpenId, async (id) => {
  if (!id) return
  await openContract({ id })
  await loadContracts()
  await nextTick()
  scrollToCurrent()
  emit('opened')
}, { immediate: true })
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
.splitter { width: 6px; flex-shrink: 0; cursor: col-resize; background: transparent; border-radius: 3px; }
.splitter:hover, .splitter:active { background: var(--border); }
.err-detail { color: var(--match-bad); font-size: 12px; }
.audit-disabled { opacity: .4; filter: grayscale(1); cursor: not-allowed; }
.rtabs { height: 100%; display: flex; flex-direction: column; }
.rtabs :deep(.el-tabs__content) { flex: 1; min-height: 0; }
.rtabs :deep(.el-tab-pane) { height: 100%; }
.rtabs :deep(.entry-row) { cursor: pointer; }
.conf-summary { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.ocr-card { display: flex; justify-content: space-between; gap: 8px; align-items: center; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; margin-bottom: 4px; cursor: pointer; }
.ocr-card.on { border-color: var(--brand); background: #eff6ff; }
.ocr-text { font-size: 13px; word-break: break-all; }
.items-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.header-map { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.hm-item { display: inline-flex; gap: 4px; align-items: center; border: 1px solid var(--border); border-radius: 4px; padding: 2px 6px; font-size: 12px; }
.hm-h { color: var(--text-2); }
.hm-arrow { color: var(--text-3); }
.hm-f { color: var(--brand); font-weight: 600; }
.section { margin-bottom: 16px; }
.sec-title { font-weight: 600; font-size: 13px; margin-bottom: 6px; display: flex; gap: 8px; align-items: center; }
.no-card { display: flex; gap: 10px; align-items: center; margin-bottom: 4px; }
.no-text { font-size: 18px; font-weight: 700; color: var(--contract-no-box); }
.table-block { margin-bottom: 10px; }
.table-block.irregular { border: 1px dashed var(--match-bad); border-radius: 6px; padding: 8px; background: #fff7ed; }
.table-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
.irregular-hint { font-size: 12px; color: var(--match-bad); margin-bottom: 6px; }
.norm-audit { margin-top: 6px; }
.norm-table { border-collapse: collapse; width: 100%; font-size: 12px; }
.norm-table th, .norm-table td { border: 1px solid var(--el-border-color, #dcdfe6); padding: 3px 6px; text-align: left; }
.norm-table th { background: var(--el-fill-color-light, #f5f7fa); }
.check-row { display: flex; gap: 6px; align-items: center; font-size: 13px; padding: 3px 0; flex-wrap: wrap; }
.cross-row { display: flex; gap: 8px; align-items: center; font-size: 12px; padding: 2px 0; }
.help-icon { color: var(--text-3); cursor: help; font-size: 15px; }
.help-icon:hover { color: var(--brand); }
.help-tip { max-width: 360px; line-height: 1.7; font-size: 12px; }
.help-line { margin-bottom: 4px; }
.help-line b { color: var(--brand); margin-right: 4px; }
.cmp-card { border: 1px solid var(--border); border-radius: 6px; padding: 8px; margin-bottom: 6px; }
.cmp-card.bad { border-color: var(--match-bad); background: #fef2f2; }
.cmp-card.clickable { cursor: pointer; }
.cmp-card.clickable:hover { border-color: var(--brand); }
:deep(.cell-bad) { color: var(--match-bad) !important; font-weight: 600; background: #fef2f2 !important; }
:deep(.row-bad td) { background: #fff5f5; }
.cmp-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; font-size: 13px; }
.cmp-field { display: flex; gap: 10px; font-size: 12px; padding: 2px 0; flex-wrap: wrap; }
.cmp-field.bad { color: var(--low); }
.cmp-field .fld { width: 36px; color: var(--text-3); }
.empty { flex: 1; display: flex; align-items: center; justify-content: center; }
</style>