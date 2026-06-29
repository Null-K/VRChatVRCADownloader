<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog">
      <div class="about-header">
        <div class="about-app-name">VRChat VRCA Downloader</div>
        <div class="about-version">v{{ version }}</div>
      </div>

      <p class="about-desc">
        VRChat 模型文件（.vrca）下载工具
        <br /><br />
        本工具为第三方辅助工具，仅用于个人账号资产管理与下载。
        所有数据请求均通过 VRChat 官方公开 API 完成。
        <br /><br />
        - 不提供或支持任何破解、绕过权限或非法访问行为<br />
        - 不包含对 VRChat 客户端/服务器/资源的注入或篡改<br />
        - 不存储、不上传、不分享用户账号密码或 Cookie
      </p>

      <div class="about-rows">
        <div class="about-row">
          <span class="about-label">作者</span>
          <span class="about-value">PuddingKC</span>
        </div>
        <div class="about-row">
          <span class="about-label">仓库</span>
          <button class="about-link" @click="openUrl('https://github.com/Null-K/VRChatVRCADownloader')">
            VRChatVRCADownloader
            <SvgIcon :svg="IconExternal" :size="11" />
          </button>
        </div>
        <div class="about-row">
          <span class="about-label">版本</span>
          <span class="about-value">{{ version }}</span>
        </div>
        <div class="about-row">
          <span class="about-label">框架</span>
          <span class="about-value">Tauri 2 · Vue 3 · Rust</span>
        </div>
        <div class="about-row">
          <span class="about-label">许可证</span>
          <span class="about-value">WTFPL</span>
        </div>
      </div>

      <div class="about-footer">
        <button class="btn-close" @click="$emit('close')">关 闭</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { open } from '@tauri-apps/plugin-shell'
import SvgIcon from './SvgIcon.vue'
import IconExternal from '../icons/external.svg?raw'

defineEmits<{ close: [] }>()

const version = '2.0.0'

async function openUrl(url: string) {
  await open(url)
}
</script>

<style scoped>
.overlay {
  position: fixed; inset: 0; z-index: 999;
  background: rgba(0,0,0,.7);
  display: flex; align-items: center; justify-content: center;
}
.dialog {
  background: var(--mantle);
  border: 1px solid var(--surface1);
  border-radius: var(--radius);
  padding: 28px 32px;
  width: 400px;
  box-shadow: var(--shadow);
  display: flex; flex-direction: column; gap: 20px;
}

.about-header {
  display: flex; align-items: baseline; gap: 10px;
}
.about-app-name {
  font-size: 18px; font-weight: 700; color: var(--text);
}
.about-version {
  font-size: 12px; color: var(--overlay1);
  background: var(--surface1); padding: 2px 8px;
  border-radius: 4px; border: 1px solid var(--surface2);
}

.about-desc {
  font-size: 12px; color: var(--subtext0); line-height: 1.7;
}

.about-rows {
  display: flex; flex-direction: column;
  border: 1px solid var(--surface1); border-radius: var(--radius-sm);
  overflow: hidden;
}
.about-row {
  display: flex; align-items: center;
  padding: 9px 14px; gap: 16px;
  border-bottom: 1px solid var(--surface1);
  font-size: 13px;
}
.about-row:last-child { border-bottom: none; }
.about-label {
  width: 52px; flex-shrink: 0;
  color: var(--overlay1); font-size: 11px;
  text-transform: uppercase; letter-spacing: .4px;
}
.about-value { color: var(--text); }
.about-link {
  background: none; border: none; cursor: pointer;
  color: var(--subtext0); font-size: 13px; padding: 0;
  display: flex; align-items: center; gap: 4px;
  transition: color .12s;
}
.about-link:hover { color: var(--text); }

.about-footer {
  display: flex; justify-content: flex-end;
}
.btn-close {
  padding: 7px 24px; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--crust);
  border: none; cursor: pointer; font-size: 13px; font-weight: 600;
  transition: background .12s;
}
.btn-close:hover { background: var(--lavender); }
</style>
