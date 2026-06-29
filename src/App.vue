<template>
  <div class="app-shell">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="topbar-left">
        <div class="logo">
          <span class="logo-text">VRChat VRCA Downloader</span>
        </div>
        <div class="divider-v" />
        <div class="login-area">
          <div class="status-dot" :class="isLoggedIn ? 'online' : 'offline'" />
          <span class="status-text">{{ isLoggedIn ? displayUser : '未登录' }}</span>
        </div>
        <button class="btn btn-accent" @click="showLogin = true">
          {{ isLoggedIn ? '切换账号' : '登录账号' }}
        </button>
        <button v-if="isLoggedIn" class="btn btn-ghost btn-logout" @click="logout" title="退出登录">
          <SvgIcon :svg="IconLogout" :size="20" />
        </button>
        <button class="btn btn-primary" :disabled="!isLoggedIn || loading"
                @click="fetchAvatars">
          <span v-if="loading" class="spinner" />
          <span v-else>获取模型</span>
        </button>
      </div>
      <div class="topbar-right">
        <div class="search-box">
          <SvgIcon :svg="IconSearch" :size="18" class="search-icon" />
          <input v-model="searchQuery" class="search-input" placeholder="搜索模型名称..." />
          <button v-if="searchQuery" class="search-clear" @click="searchQuery=''">✕</button>
        </div>
        <button class="btn btn-ghost" @click="showSettings = true">
          <SvgIcon :svg="IconSettings" :size="22" />
        </button>
        <button class="btn btn-ghost" @click="showAbout = true" title="关于">
          <SvgIcon :svg="IconInfo" :size="22" />
        </button>
      </div>
    </header>

    <!-- 状态条 -->
    <div v-if="statusMsg" class="status-bar">
      <span class="spinner-sm" />
      <span>{{ statusMsg }}</span>
    </div>

    <!-- 主内容 -->
    <main class="main-content">
      <!-- 左：模型列表 -->
      <section class="avatar-panel">
        <div v-if="filteredAvatars.length === 0 && !loading" class="empty-state">
          <SvgIcon :svg="IconEmpty" :size="60" class="empty-icon" />
          <p>{{ isLoggedIn ? '暂无模型，请点击获取模型' : '请先登录一个账号' }}</p>
        </div>
        <div v-else class="avatar-grid" ref="gridRef">
          <AvatarCard
            v-for="av in filteredAvatars"
            :key="av.file_id"
            :avatar="av"
            :selected="selectedId === av.file_id"
            @click="selectAvatar(av)"
            @download="startDownload(av)"
          />
        </div>
      </section>

      <!-- 右：详情面板 -->
      <aside class="detail-panel">
        <DetailPanel
          v-if="selectedAvatar"
          :avatar="selectedAvatar"
          @download="startDownload(selectedAvatar)"
        />
        <div v-else class="detail-empty flex-center">
          <div style="text-align:center;opacity:.3">
            <SvgIcon :svg="IconEmpty" :size="50" style="margin-bottom:10px" />
            <p style="font-size:12px">选择一个模型查看详情</p>
          </div>
        </div>
      </aside>
    </main>

    <!-- 任务列表 -->
    <TaskList
      :tasks="tasks"
      @cancel="cancelTask"
      @cancel-all="cancelAll"
      @retry="retryFailed"
      @clear="clearFinished"
    />

    <!-- 弹窗 -->
    <LoginDialog v-if="showLogin" :proxy="proxy" @close="showLogin=false" @logged-in="onLoggedIn" />
    <SettingsDialog v-if="showSettings" v-model:proxy="proxy"
                    v-model:template="filenameTemplate"
                    @close="onSettingsClose" />
    <AboutDialog v-if="showAbout" @close="showAbout=false" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, provide } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { save as dialogSave } from '@tauri-apps/plugin-dialog'
import AvatarCard from './components/AvatarCard.vue'
import DetailPanel from './components/DetailPanel.vue'
import TaskList from './components/TaskList.vue'
import LoginDialog from './components/LoginDialog.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import AboutDialog from './components/AboutDialog.vue'
import SvgIcon from './components/SvgIcon.vue'
import IconSearch from './icons/search.svg?raw'
import IconSettings from './icons/settings.svg?raw'
import IconLogout from './icons/logout.svg?raw'
import IconEmpty from './icons/empty.svg?raw'
import IconInfo from './icons/info.svg?raw'
import type { AvatarItem, TaskSnapshot } from './types'

const imgCache = new Map<string, string>()
const imgPending = new Map<string, Promise<string>>()

function getCachedImg(url: string): string | null {
  return imgCache.get(url) ?? null
}

async function fetchImg(url: string): Promise<string> {
  if (imgCache.has(url)) return imgCache.get(url)!
  if (imgPending.has(url)) return imgPending.get(url)!

  const p = (async () => {
    try {
      const bytes = await invoke<number[]>('cmd_fetch_image_bytes', { url, thumb: false })
      const blob = new Blob([new Uint8Array(bytes)], { type: 'image/jpeg' })
      const objUrl = URL.createObjectURL(blob)
      imgCache.set(url, objUrl)
      return objUrl
    } finally {
      imgPending.delete(url)
    }
  })()
  imgPending.set(url, p)
  return p
}

provide('fetchImg', fetchImg)
provide('getCachedImg', getCachedImg)

// ── state ──────────────────────────────────────────────────────────────────
const isLoggedIn = ref(false)
const displayUser = ref('')
const loading = ref(false)
const statusMsg = ref('')
const searchQuery = ref('')
const allAvatars = ref<AvatarItem[]>([])
const selectedId = ref('')
const tasks = ref<TaskSnapshot[]>([])
const showLogin = ref(false)
const showSettings = ref(false)
const showAbout = ref(false)
const proxy = ref('')
const filenameTemplate = ref('{short_name}')

let unlistenProgress: UnlistenFn | null = null
let unlistenTask: UnlistenFn | null = null
let unlistenRemove: UnlistenFn | null = null

// ── computed ───────────────────────────────────────────────────────────────
const filteredAvatars = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return allAvatars.value
  return allAvatars.value.filter(av =>
    av.name.toLowerCase().includes(q) || av.short_name.toLowerCase().includes(q)
  )
})

const selectedAvatar = computed(() =>
  allAvatars.value.find(av => av.file_id === selectedId.value) ?? null
)

// ── lifecycle ──────────────────────────────────────────────────────────────
onMounted(async () => {
  unlistenProgress = await listen<string>('fetch-progress', e => { statusMsg.value = e.payload })
  unlistenTask = await listen<TaskSnapshot>('task-updated', e => {
    const idx = tasks.value.findIndex(t => t.id === e.payload.id)
    if (idx >= 0) tasks.value.splice(idx, 1, e.payload)
    else tasks.value.push(e.payload)
  })
  unlistenRemove = await listen<number>('task-removed', e => {
    tasks.value = tasks.value.filter(t => t.id !== e.payload)
  })
  // 恢复任务列表
  try {
    const saved = await invoke<TaskSnapshot[]>('cmd_get_tasks')
    tasks.value = saved
  } catch {}
  // 加载持久化配置
  try {
    const cfg = await invoke<{ proxy?: string; filename_template?: string }>('cmd_load_config')
    if (cfg.proxy) proxy.value = cfg.proxy
    if (cfg.filename_template) filenameTemplate.value = cfg.filename_template
  } catch {}
  // 尝试自动恢复上次登录会话
  try {
    const name = await invoke<string>('cmd_restore_session')
    if (name) {
      isLoggedIn.value = true
      displayUser.value = name
    }
  } catch {}
})

onUnmounted(() => {
  unlistenProgress?.()
  unlistenTask?.()
  unlistenRemove?.()
})

// ── methods ────────────────────────────────────────────────────────────────
async function onLoggedIn(user: string) {
  isLoggedIn.value = true
  displayUser.value = user || '已登录'
  showLogin.value = false
  // 持久化会话
  try {
    await invoke('cmd_save_session', { displayName: user || '已登录' })
  } catch {}
}

async function logout() {
  isLoggedIn.value = false
  displayUser.value = ''
  allAvatars.value = []
  selectedId.value = ''
  try { await invoke('cmd_clear_session') } catch {}
}

async function onSettingsClose() {
  showSettings.value = false
  try {
    await invoke('cmd_save_config', {
      config: {
        proxy: proxy.value || null,
        filename_template: filenameTemplate.value || null,
      }
    })
  } catch {}
}

async function fetchAvatars() {
  loading.value = true
  statusMsg.value = '连接 VRChat 服务器...'
  try {
    const result = await invoke<AvatarItem[]>('cmd_fetch_avatars')
    allAvatars.value = result
    statusMsg.value = ''
    if (result.length > 0) selectedId.value = result[0].file_id
  } catch (e) {
    statusMsg.value = ''
    alert('获取失败: ' + e)
  } finally {
    loading.value = false
    statusMsg.value = ''
  }
}

function selectAvatar(av: AvatarItem) {
  selectedId.value = av.file_id
}

async function startDownload(av: AvatarItem) {
  try {
    const rendered = buildFilename(filenameTemplate.value, av)
    const target = await dialogSave({
      defaultPath: rendered,
      filters: [{ name: 'VRChat Avatar', extensions: ['vrca'] }],
    })
    if (!target) return
    await invoke('cmd_start_download', {
      name: av.short_name,
      url: av.url,
      savePath: target,
    })
  } catch (e) {
    alert('下载失败: ' + e)
  }
}

function buildFilename(tpl: string, av: AvatarItem): string {
  const date = (av.created_at || '').slice(0, 10)
  return (tpl || '{short_name}')
    .replace('{short_name}', av.short_name)
    .replace('{name}', av.name)
    .replace('{version}', String(av.version))
    .replace('{id}', av.file_id)
    .replace('{date}', date)
    .replace(/[\\/:*?"<>|]/g, '_') + '.vrca'
}

async function cancelTask(id: number) {
  await invoke('cmd_cancel_task', { id })
}
async function cancelAll() {
  await invoke('cmd_cancel_all')
}
async function retryFailed() {
  await invoke('cmd_retry_failed')
}
async function clearFinished() {
  await invoke('cmd_clear_finished')
}
</script>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg);
  overflow: hidden;
}

/* ── Topbar ─────────────────────────────────────────────────────── */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  height: 54px;
  background: var(--mantle);
  border-bottom: 1px solid var(--surface1);
  flex-shrink: 0;
  gap: 16px;
}
.topbar-left, .topbar-right { display: flex; align-items: center; gap: 10px; }
.logo { display: flex; align-items: center; gap: 8px; }
.logo-icon { color: var(--overlay1); flex-shrink: 0; }
.logo-text { font-size: 14px; font-weight: 600; color: var(--text); letter-spacing: .3px; }
.divider-v { width: 1px; height: 20px; background: var(--surface2); }
.login-area { display: flex; align-items: center; gap: 7px; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.status-dot.online  { background: var(--green); }
.status-dot.offline { background: var(--overlay0); }
.status-text { color: var(--overlay1); font-size: 12px; }
.btn-logout:hover { color: var(--red) !important; background: color-mix(in srgb, var(--red) 10%, transparent) !important; }

/* ── Buttons ────────────────────────────────────────────────────── */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 14px; border-radius: var(--radius-sm);
  border: 1px solid transparent;
  cursor: pointer; font-size: 13px; font-weight: 500;
  transition: background .12s, color .12s, border-color .12s;
  white-space: nowrap;
}
.btn:disabled { opacity: .35; cursor: not-allowed; }
.btn-accent  { background: var(--accent); color: var(--crust); border-color: var(--accent); }
.btn-accent:hover:not(:disabled) { background: var(--lavender); border-color: var(--lavender); }
.btn-primary { background: transparent; color: var(--subtext0); border-color: var(--surface2); }
.btn-primary:hover:not(:disabled) { background: var(--surface1); color: var(--text); }
.btn-ghost   { background: transparent; color: var(--overlay1); padding: 5px 9px; }
.btn-ghost:hover { color: var(--text); background: var(--surface1); }

/* ── Search ─────────────────────────────────────────────────────── */
.search-box { position: relative; display: flex; align-items: center; }
.search-icon {
  position: absolute; left: 10px;
  color: var(--overlay0); pointer-events: none;
}
.search-input {
  background: var(--surface0); border: 1px solid var(--surface1);
  border-radius: var(--radius-sm); color: var(--text);
  padding: 5px 30px; font-size: 13px; width: 220px;
  outline: none; transition: border-color .12s;
}
.search-input:focus { border-color: var(--surface2); }
.search-input::placeholder { color: var(--overlay0); }
.search-clear {
  position: absolute; right: 8px; background: none; border: none;
  color: var(--overlay0); cursor: pointer; font-size: 11px; padding: 2px;
}
.search-clear:hover { color: var(--text); }

/* ── Status bar ─────────────────────────────────────────────────── */
.status-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 20px; font-size: 11px; color: var(--overlay1);
  background: var(--mantle); border-bottom: 1px solid var(--surface1);
  flex-shrink: 0;
}

/* ── Main ───────────────────────────────────────────────────────── */
.main-content { display: flex; flex: 1; overflow: hidden; min-height: 0; }

/* ── Avatar panel ───────────────────────────────────────────────── */
.avatar-panel { flex: 1; overflow-y: auto; padding: 14px; min-width: 0; }
.empty-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 100%; gap: 10px; color: var(--overlay0);
}
.empty-icon { font-size: 40px; opacity: .4; }
.avatar-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}

/* ── Detail panel ───────────────────────────────────────────────── */
.detail-panel {
  width: 360px; flex-shrink: 0;
  border-left: 1px solid var(--surface1);
  overflow-y: auto;
  background: var(--mantle);
}
.detail-empty { height: 100%; color: var(--overlay0); font-size: 13px; }

/* ── Spinners ───────────────────────────────────────────────────── */
.spinner {
  width: 14px; height: 14px; border: 2px solid transparent;
  border-top-color: currentColor; border-radius: 50%;
  animation: spin .6s linear infinite; display: inline-block;
}
.spinner-sm {
  width: 10px; height: 10px; border: 2px solid transparent;
  border-top-color: var(--accent); border-radius: 50%;
  animation: spin .6s linear infinite; display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
