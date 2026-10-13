<script setup>
// 学段选择器：切换后全局 Prompt 与讲解风格随之变化
defineProps({
  modelValue: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])

const GRADES = [
  { key: 'primary_low', label: '小学低年级', tip: '1-3 年级 · 故事化讲解' },
  { key: 'primary_high', label: '小学高年级', tip: '4-6 年级 · 通俗+小任务' },
  { key: 'junior', label: '初中', tip: '讲清脉络与因果' },
  { key: 'senior', label: '高中', tip: '深度分析+思辨' },
]
</script>

<template>
  <div class="grade-selector" role="group" aria-label="学段选择">
    <button
      v-for="g in GRADES"
      :key="g.key"
      class="grade-chip"
      :class="{ active: modelValue === g.key }"
      :title="g.tip"
      @click="emit('update:modelValue', g.key)"
    >{{ g.label }}</button>
  </div>
</template>
