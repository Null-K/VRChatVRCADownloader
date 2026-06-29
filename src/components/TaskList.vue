<template>
  <div class="task-panel">
    <div class="task-header">
      <span class="task-title">下载任务</span>
      <span class="task-count" v-if="tasks.length">{{ tasks.length }}</span>
      <div class="task-actions">
        <button class="tbtn" @click="$emit('retry')" title="重试失败任务">重试失败</button>
        <button class="tbtn" @click="$emit('clear')" title="清理已完成任务">清理完成</button>
        <button class="tbtn tbtn-danger" @click="$emit('cancel-all')" title="终止全部正在进行的任务">终止全部</button>
      </div>
    </div>
    <div v-if="tasks.length === 0" class="task-empty">暂无下载任务</div>
    <div v-else class="task-list">
      <div v-for="t in sortedTasks" :key="t.id" class="task-row" :class="t.status">
        <div class="task-info">
          <span class="task-name truncate" :title="t.name">{{ t.name }}</span>
          <span class="task-status-badge" :class="t.status">{{ statusLabel(t.status) }}</span>
        </div>
        <div class="task-progress-wrap" v-if="t.status === 'running' || t.total > 0">
          <div class="task-progress-bar">
            <div class="task-progress-fill" :style="{ width: progressPct(t) + '%' }" />
          </div>
          <span class="task-pct">{{ progressPct(t).toFixed(0) }}%</span>
        </div>
        <div class="task-meta">
          <span class="task-bytes">{{ fmtBytes(t.downloaded) }} / {{ fmtBytes(t.total) }}</span>
          <span class="task-speed" v-if="t.status === 'running'">{{ fmtBytes(t.speed) }}/s</span>
          <span class="task-error truncate" v-if="t.error" :title="t.error">{{ t.error }}</span>
          <button v-if="t.status === 'queued' || t.status === 'running'"
                  class="task-cancel-btn" @click="$emit('cancel', t.id)">
            <svg viewBox="0 0 12 12" fill="currentColor" width="10" height="10">
              <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TaskSnapshot } from '../types'

const props = defineProps<{ tasks: TaskSnapshot[] }>()
defineEmits<{
  cancel: [id: number]
  'cancel-all': []
  retry: []
  clear: []
}>()

const sortedTasks = computed(() =>
  [...props.tasks].sort((a, b) => b.id - a.id)
)

const LABELS: Record<string, string> = {
  queued: '排队中', running: '下载中', success: '已完成',
  failed: '失败', timeout: '超时', cancelled: '已终止',
}
function statusLabel(s: string) { return LABELS[s] ?? s }

function progressPct(t: TaskSnapshot) {
  if (!t.total) return 0
  return Math.min(100, (t.downloaded / t.total) * 100)
}

function fmtBytes(n: number) {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`
  return `${(n / 1024 ** 3).toFixed(2)} GB`
}
</script>

<style scoped>
.task-panel {
  flex-shrink: 0;
  border-top: 1px solid var(--surface0);
  background: var(--mantle);
  max-height: 220px;
  display: flex;
  flex-direction: column;
}
.task-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; border-bottom: 1px solid var(--surface0);
  flex-shrink: 0;
}
.task-title { font-size: 13px; font-weight: 600; color: var(--subtext0); }
.task-count {
  background: var(--surface1); color: var(--subtext0);
  font-size: 11px; padding: 1px 6px; border-radius: 99px;
}
.task-actions { display: flex; gap: 6px; margin-left: auto; }
.tbtn {
  font-size: 11px; padding: 3px 10px; border-radius: var(--radius-sm);
  border: 1px solid var(--surface1); background: transparent;
  color: var(--subtext0); cursor: pointer; transition: all .12s;
}
.tbtn:hover { background: var(--surface0); color: var(--text); }
.tbtn-danger { border-color: color-mix(in srgb, var(--red) 40%, transparent); }
.tbtn-danger:hover { background: color-mix(in srgb, var(--red) 15%, transparent); color: var(--red); }

.task-empty {
  padding: 16px; text-align: center; color: var(--overlay0); font-size: 12px;
}
.task-list { overflow-y: auto; flex: 1; }

.task-row {
  display: flex; flex-direction: column; gap: 3px;
  padding: 7px 16px; border-bottom: 1px solid var(--surface1);
  border-left: 2px solid transparent;
  transition: background .1s;
}
.task-row:hover { background: var(--surface0); }
.task-row.success  { border-left-color: var(--surface2); }
.task-row.failed,
.task-row.timeout  { border-left-color: var(--red); }
.task-row.cancelled{ border-left-color: var(--surface2); }
.task-row.running  { border-left-color: var(--subtext1); }

.task-info { display: flex; align-items: center; gap: 6px; }
.task-name { flex: 1; min-width: 0; font-size: 13px; font-weight: 500; }
.task-status-badge { flex-shrink: 0; font-size: 11px; }

.task-status-badge.running   { color: var(--subtext0); }
.task-status-badge.success   { color: var(--subtext0); }
.task-status-badge.failed,
.task-status-badge.timeout   { color: var(--red); }
.task-status-badge.cancelled { color: var(--overlay1); }
.task-status-badge.queued    { color: var(--overlay1); }

.task-progress-wrap { display: flex; align-items: center; gap: 8px; }
.task-progress-bar  { flex: 1; height: 2px; background: var(--surface2); border-radius: 99px; overflow: hidden; }
.task-progress-fill { height: 100%; background: var(--subtext1); border-radius: 99px; transition: width .3s; }
.task-pct { font-size: 10px; color: var(--overlay1); width: 30px; text-align: right; }

.task-meta { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--overlay0); }
.task-bytes { flex-shrink: 0; }
.task-speed { color: var(--subtext0); flex-shrink: 0; }
.task-error { color: var(--red); flex: 1; min-width: 0; }
.task-cancel-btn {
  margin-left: auto; background: none; border: none; cursor: pointer;
  color: var(--overlay0); font-size: 11px; padding: 2px 4px;
  border-radius: 4px; transition: color .1s;
}
.task-cancel-btn:hover { color: var(--text); }
</style>
