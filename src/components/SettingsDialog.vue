<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog">
      <h2 class="dialog-title">设置</h2>

      <div class="form">
        <label class="field">
          <span class="field-label">网络代理</span>
          <input :value="proxy" @input="$emit('update:proxy', ($event.target as HTMLInputElement).value)"
                 class="field-input" placeholder="http://127.0.0.1:7890" />
          <span class="field-hint">留空表示直连，格式：http://host:port</span>
        </label>

        <label class="field">
          <span class="field-label">文件名模板</span>
          <input :value="template" @input="$emit('update:template', ($event.target as HTMLInputElement).value)"
                 class="field-input" placeholder="{short_name}" />
          <span class="field-hint">变量：{short_name}  {name}  {version}  {id}  {date}</span>
        </label>
      </div>

      <div class="dialog-actions">
        <button class="btn-ok" @click="$emit('close')">关 闭</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ proxy: string; template: string }>()
defineEmits<{
  close: []
  'update:proxy': [v: string]
  'update:template': [v: string]
}>()
</script>

<style scoped>
.overlay {
  position: fixed; inset: 0; z-index: 999;
  background: rgba(0,0,0,.7);
  display: flex; align-items: center; justify-content: center;
}
.dialog {
  background: var(--mantle); border: 1px solid var(--surface1);
  border-radius: var(--radius); padding: 28px 32px; width: 400px; box-shadow: var(--shadow);
}
.dialog-title { font-size: 15px; font-weight: 600; margin-bottom: 18px; color: var(--text); }
.form { display: flex; flex-direction: column; gap: 14px; margin-bottom: 8px; }
.field { display: flex; flex-direction: column; gap: 5px; }
.field-label { font-size: 11px; color: var(--overlay1); font-weight: 500; text-transform: uppercase; letter-spacing: .5px; }
.field-input {
  background: var(--surface0); border: 1px solid var(--surface1);
  border-radius: var(--radius-sm); color: var(--text);
  padding: 8px 11px; font-size: 13px; outline: none; transition: border-color .12s;
}
.field-input:focus { border-color: var(--surface2); }
.field-input::placeholder { color: var(--overlay0); }
.field-hint { font-size: 11px; color: var(--overlay0); }
.dialog-actions { display: flex; justify-content: flex-end; margin-top: 20px; }
.btn-ok {
  padding: 7px 24px; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--crust);
  border: none; cursor: pointer; font-size: 13px; font-weight: 600;
  transition: background .12s;
}
.btn-ok:hover { background: var(--lavender); }
</style>
