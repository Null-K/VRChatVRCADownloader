<template>
  <div class="card" :class="{ selected }" :data-id="avatar.file_id" @click="$emit('click')">
    <div class="card-thumb">
      <img v-if="thumbSrc" :src="thumbSrc" class="thumb-img" :alt="avatar.short_name" />
      <div v-else class="thumb-placeholder flex-center">
        <span v-if="loadingThumb" class="thumb-spinner" />
        <SvgIcon v-else :svg="IconPlaceholder" :size="50" style="opacity:.2" />
      </div>
      <div class="card-version">v{{ avatar.version }}</div>
    </div>
    <div class="card-body">
      <div class="card-name truncate" :title="avatar.short_name">{{ avatar.short_name }}</div>
      <div class="card-date">{{ avatar.created_at.slice(0, 10) }}</div>
    </div>
    <button class="card-dl-btn" @click.stop="$emit('download')" title="下载">
      <SvgIcon :svg="IconDownload" :size="16" />
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, inject } from 'vue'
import SvgIcon from './SvgIcon.vue'
import IconPlaceholder from '../icons/placeholder.svg?raw'
import IconDownload from '../icons/download.svg?raw'
import type { AvatarItem } from '../types'

const props = defineProps<{ avatar: AvatarItem; selected: boolean }>()
defineEmits<{ click: []; download: [] }>()

const fetchImg = inject<(url: string) => Promise<string>>('fetchImg')!
const getCachedImg = inject<(url: string) => string | null>('getCachedImg')!

const thumbSrc = ref<string | null>(null)
const loadingThumb = ref(false)

watch(
  () => props.avatar.image_url,
  async (url) => {
    if (!url) { thumbSrc.value = null; return }

    const cached = getCachedImg(url)
    if (cached) { thumbSrc.value = cached; return }

    loadingThumb.value = true
    try {
      thumbSrc.value = await fetchImg(url)
    } catch {
      thumbSrc.value = null
    } finally {
      loadingThumb.value = false
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.card {
  position: relative;
  background: var(--surface0);
  border: 1px solid var(--surface1);
  border-radius: var(--radius);
  overflow: hidden;
  cursor: pointer;
  transition: border-color .12s, transform .15s, box-shadow .15s;
}
.card:hover {
  border-color: var(--surface2);
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}
.card.selected { border-color: var(--accent); }

.card-thumb {
  position: relative;
  aspect-ratio: 1;
  background: var(--crust);
  overflow: hidden;
}
.thumb-img {
  width: 100%; height: 100%; object-fit: cover;
  transition: transform .2s;
}
.card:hover .thumb-img { transform: scale(1.04); }
.thumb-placeholder { width: 100%; height: 100%; color: var(--surface2); }
.thumb-spinner {
  width: 16px; height: 16px;
  border: 1.5px solid var(--surface2);
  border-top-color: var(--overlay1);
  border-radius: 50%;
  animation: spin .7s linear infinite;
  display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg); } }

.card-version {
  position: absolute; top: 6px; right: 6px;
  background: rgba(0,0,0,.55);
  color: var(--subtext1); font-size: 10px; font-weight: 500;
  padding: 2px 6px; border-radius: 4px;
  letter-spacing: .3px;
}

.card-body { padding: 9px 10px 8px; }
.card-name { font-size: 12px; font-weight: 500; color: var(--text); margin-bottom: 3px; }
.card-date { font-size: 11px; color: var(--overlay1); }

.card-dl-btn {
  position: absolute; bottom: 8px; right: 8px;
  background: var(--accent); color: var(--crust);
  border: none; border-radius: var(--radius-sm);
  width: 26px; height: 26px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; opacity: 0;
  transition: opacity .12s;
}
.card:hover .card-dl-btn { opacity: 1; }
.card-dl-btn:hover { background: var(--lavender); }
</style>
