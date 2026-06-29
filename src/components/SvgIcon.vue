<template>
  <span class="svg-icon" :style="{ width: size, height: size }" v-html="svg" />
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  svg: string
  size?: string | number
}>(), {
  size: 16,
})

const size = computed(() =>
  typeof props.size === 'number' ? `${props.size}px` : props.size
)
</script>

<style scoped>
.svg-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: inherit;
}
.svg-icon :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
