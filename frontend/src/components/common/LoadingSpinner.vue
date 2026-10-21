<template>
  <span class="inline-spinner">
    <span class="dot"></span>
    <span class="dot"></span>
    <span class="dot"></span>
  </span>
</template>

<script setup>
// No props needed for minimal inline spinner
</script>

<style scoped>
/* Spinner ใช้สีหลักของเว็บและรองรับ dark mode */
.inline-spinner {
  display: inline-flex;
  align-items: center;
  gap: 0.25em;
  height: 1em;
}
.dot {
  width: 0.7em;
  height: 0.7em;
  background: var(--color-primary, #2563eb);
  border-radius: 50%;
  display: inline-block;
  animation: dot-bounce 1.1s infinite both;
  transition: background 0.2s;
}
.dot:nth-child(2) {
  animation-delay: 0.2s;
}
.dot:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes dot-bounce {
  0%, 80%, 100% {
    transform: scale(0.7);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
:root {
  --color-primary: #2563eb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --color-primary: #60a5fa;
  }
}
</style>
