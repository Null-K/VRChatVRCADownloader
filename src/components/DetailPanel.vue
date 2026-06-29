<template>
  <div class="detail">
    <div class="preview-wrap">
      <img v-if="previewSrc" :src="previewSrc" class="preview-img" :alt="avatar.short_name" />
      <div v-else class="preview-placeholder flex-center">
        <span v-if="loadingImg" class="preview-spinner" />
        <SvgIcon v-else :svg="IconPlaceholder" :size="60" style="opacity:.2" />
      </div>
    </div>

    <div class="detail-body">
      <h2 class="av-name">{{ avatar.short_name }}</h2>
      <p class="av-fullname truncate" :title="avatar.name">{{ avatar.name }}</p>

      <div class="meta-row">
        <span class="meta-badge">v{{ avatar.version }}</span>
        <span class="meta-date">{{ avatar.created_at.slice(0, 10) }}</span>
      </div>
      <div class="meta-id truncate" :title="avatar.file_id">{{ avatar.file_id }}</div>

      <button class="dl-btn" @click="$emit('download')">
        <SvgIcon :svg="IconDownload" :size="18" />
        下载此模型
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, inject } from 'vue'
import SvgIcon from './SvgIcon.vue'
import IconPlaceholder from '../icons/placeholder.svg?raw'
import IconDownload from '../icons/download.svg?raw'
import type { AvatarItem } from '../types'

const props = defineProps<{ avatar: AvatarItem }>()
defineEmits<{ download: [] }>()

const fetchImg = inject<(url: string) => Promise<string>>('fetchImg')!
const getCachedImg = inject<(url: string) => string | null>('getCachedImg')!

const previewSrc = ref<string | null>(null)
const loadingImg = ref(false)

watch(
  () => props.avatar.file_id,
  async () => {
    const url = props.avatar.image_url
    if (!url) { previewSrc.value = null; return }

    const cached = getCachedImg(url)
    if (cached) {
      previewSrc.value = cached
      return
    }

    previewSrc.value = null
    loadingImg.value = true
    try {
      previewSrc.value = await fetchImg(url)
    } catch {
      previewSrc.value = null
    } finally {
      loadingImg.value = false
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.detail { display: flex; flex-direction: column; height: 100%; }

.preview-wrap {
  aspect-ratio: 1;
  background: var(--crust);
  overflow: hidden;
  flex-shrink: 0;
}
.preview-img { width: 100%; height: 100%; object-fit: cover; }
.preview-placeholder { width: 100%; height: 100%; color: var(--surface2); }
.preview-spinner {
  width: 28px; height: 28px;
  border: 2px solid var(--surface2);
  border-top-color: var(--overlay1);
  border-radius: 50%;
  animation: spin .7s linear infinite;
  display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg); } }

.detail-body {
  padding: 16px; flex: 1;
  display: flex; flex-direction: column; gap: 8px;
}

.av-name { font-size: 15px; font-weight: 600; color: var(--text); line-height: 1.4; }
.av-fullname { font-size: 11px; color: var(--overlay0); }

.meta-row { display: flex; align-items: center; gap: 8px; }
.meta-badge {
  background: var(--surface1);
  color: var(--subtext0); font-size: 11px; font-weight: 500;
  padding: 2px 7px; border-radius: 4px;
  border: 1px solid var(--surface2);
}
.meta-date { font-size: 12px; color: var(--overlay1); }
.meta-id { font-size: 10px; color: var(--overlay0); font-family: monospace; }

.dl-btn {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 10px; border-radius: var(--radius);
  background: var(--accent); color: var(--crust);
  border: none; cursor: pointer; font-size: 13px; font-weight: 600;
  transition: background .12s;
  margin-top: auto;
}
.dl-btn:hover { background: var(--lavender); }
</style>
