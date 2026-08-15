<template>
  <div class="overlay" @click.self="onOverlayClick">
    <div class="dialog">
      <!-- 登录阶段 -->
      <template v-if="phase === 'login'">
        <h2 class="dialog-title">登录 VRChat</h2>
        <p class="dialog-sub">使用你的 VRChat 账号或邮箱登录</p>
        <div class="form">
          <label class="field">
            <span class="field-label">用户名 / 邮箱</span>
            <input v-model="username" class="field-input"
                   placeholder="Username or Email" autocomplete="username" />
          </label>
          <label class="field">
            <span class="field-label">密码</span>
            <div class="field-wrap">
              <input v-model="password" class="field-input" :type="showPwd ? 'text' : 'password'"
                     placeholder="••••••••" autocomplete="current-password"
                     @keyup.enter="doLogin" />
              <button type="button" class="eye-btn" @click="showPwd = !showPwd" tabindex="-1">
                <SvgIcon :svg="showPwd ? IconEyeOff : IconEye" :size="23" />
              </button>
            </div>
          </label>
        </div>
        <div v-if="errMsg" class="err-msg">{{ errMsg }}</div>
        <div class="dialog-actions">
          <button class="btn-cancel" @click="$emit('close')">取消</button>
          <button class="btn-ok" :disabled="loading" @click="doLogin">
            <span v-if="loading" class="spinner" />
            <span v-else>登 录</span>
          </button>
        </div>
      </template>

      <!-- 2FA 阶段 -->
      <template v-else>
        <h2 class="dialog-title">双因素验证</h2>
        <p class="dialog-sub">{{ fa2Hint }}</p>
        <div class="form">
          <label class="field">
            <span class="field-label">验证码</span>
            <input v-model="code" class="field-input code-input"
                   placeholder="000000" maxlength="6" inputmode="numeric"
                   @input="code = code.replace(/\D/g, '').slice(0, 6)"
                   @keyup.enter="do2fa" ref="codeRef" />
          </label>
        </div>
        <div v-if="errMsg" class="err-msg">{{ errMsg }}</div>
        <div class="dialog-actions">
          <button class="btn-cancel" @click="$emit('close')">取消</button>
          <button class="btn-ok" :disabled="loading" @click="do2fa">
            <span v-if="loading" class="spinner" />
            <span v-else>验 证</span>
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import SvgIcon from './SvgIcon.vue'
import IconEye from '../icons/eye.svg?raw'
import IconEyeOff from '../icons/eye-off.svg?raw'
import type { LoginResult } from '../types'

const props = defineProps<{ proxy?: string }>()
const emit = defineEmits<{ close: []; 'logged-in': [user: string] }>()

const phase = ref<'login' | '2fa'>('login')
const username = ref('')
const password = ref('')
const showPwd = ref(false)
const code = ref('')
const loading = ref(false)
const errMsg = ref('')
const fa2Method = ref('totp')
const fa2Hint = ref('')
const codeRef = ref<HTMLInputElement | null>(null)

function onOverlayClick() {
  if (phase.value === 'login') emit('close')
}

async function doLogin() {
  if (!username.value || !password.value) { errMsg.value = '请填写用户名和密码'; return }
  loading.value = true
  errMsg.value = ''
  try {
    const res = await invoke<LoginResult>('cmd_login', {
      username: username.value,
      password: password.value,
      proxy: props.proxy || null,
    })
    if (res.error) { errMsg.value = res.error; return }
    if (res.requires_2fa) {
      if (res.fa_methods.includes('emailOtp')) {
        fa2Method.value = 'emailotp'
        fa2Hint.value = '请输入发送至邮箱的验证码'
      } else {
        fa2Method.value = 'totp'
        fa2Hint.value = '请输入验证器 App 中的 6 位验证码'
      }
      phase.value = '2fa'
      await nextTick()
      codeRef.value?.focus()
      return
    }
    emit('logged-in', username.value)
  } catch (e) {
    errMsg.value = String(e)
  } finally {
    loading.value = false
  }
}

async function do2fa() {
  if (!code.value) { errMsg.value = '请输入验证码'; return }
  loading.value = true
  errMsg.value = ''
  try {
    const res = await invoke<LoginResult>('cmd_verify_2fa', {
      code: code.value,
      method: fa2Method.value,
    })
    if (res.error) { errMsg.value = res.error; return }
    emit('logged-in', username.value)
  } catch (e) {
    errMsg.value = String(e)
  } finally {
    loading.value = false
  }
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
  width: 360px;
  box-shadow: var(--shadow);
}
.dialog-title { font-size: 17px; font-weight: 600; margin-bottom: 4px; color: var(--text); }
.dialog-sub   { font-size: 12px; color: var(--overlay1); margin-bottom: 22px; }

.form { display: flex; flex-direction: column; gap: 12px; margin-bottom: 8px; }
.field { display: flex; flex-direction: column; gap: 5px; }
.field-label { font-size: 11px; color: var(--overlay1); font-weight: 500; text-transform: uppercase; letter-spacing: .5px; }
.field-input {
  background: var(--surface0); border: 1px solid var(--surface1);
  border-radius: var(--radius-sm); color: var(--text);
  padding: 8px 11px; font-size: 13px; outline: none;
  transition: border-color .12s;
  width: 100%;
  /* 隐藏 WebView2/Edge 原生密码眼睛图标 */
  -webkit-text-security: unset;
}
.field-input::-ms-reveal,
.field-input::-ms-clear { display: none; }
.field-input:focus { border-color: var(--surface2); }
.field-input::placeholder { color: var(--overlay0); }

.field-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.field-wrap .field-input { padding-right: 34px; }
.eye-btn {
  position: absolute; right: 8px;
  background: none; border: none; cursor: pointer;
  color: var(--overlay0); padding: 2px;
  display: flex; align-items: center;
  transition: color .12s;
}
.eye-btn:hover { color: var(--text); }
.code-input {
  font-size: 20px; letter-spacing: 8px; text-align: center;
  font-family: 'Courier New', monospace;
}
.code-input::-webkit-outer-spin-button,
.code-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }

.err-msg { color: var(--red); font-size: 11px; margin: 6px 0; }

.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
.btn-cancel {
  padding: 7px 18px; border-radius: var(--radius-sm);
  background: transparent; border: 1px solid var(--surface2);
  color: var(--overlay1); cursor: pointer; font-size: 13px;
  transition: background .12s, color .12s;
}
.btn-cancel:hover { background: var(--surface1); color: var(--text); }
.btn-ok {
  padding: 7px 22px; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--crust);
  border: none; cursor: pointer; font-size: 13px; font-weight: 600;
  transition: background .12s; min-width: 72px;
  display: flex; align-items: center; justify-content: center;
}
.btn-ok:hover:not(:disabled) { background: var(--lavender); }
.btn-ok:disabled { opacity: .4; cursor: not-allowed; }
.spinner {
  width: 13px; height: 13px; border: 1.5px solid transparent;
  border-top-color: var(--crust); border-radius: 50%;
  animation: spin .6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
