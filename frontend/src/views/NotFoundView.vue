<template>
  <div class="not-found">
    <div class="not-found-content">
      <div class="error-code">404</div>
      <h1>ไม่พบหน้าที่คุณค้นหา</h1>
      <p>ขออภัย เราไม่สามารถค้นหาหน้าที่คุณกำลังมองหา</p>
      <div class="actions">
        <button @click="goBack" class="btn btn-secondary">กลับไปหน้าก่อนหน้า</button>
        <RouterLink to="/dashboard" class="btn btn-primary">ไปยังหน้าแดชบอร์ด</RouterLink>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

function goBack() {
  router.back()
}
</script>

<style scoped>
.not-found {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
  text-align: center;
}

.not-found-content {
  max-width: 500px;
  padding: 2rem;
}

.error-code {
  font-size: 6rem;
  font-weight: 700;
  color: #1e40af;
  line-height: 1;
  margin-bottom: 1rem;
}

h1 {
  font-size: 2rem;
  margin-bottom: 1rem;
  color: #1e293b;
}

p {
  color: #64748b;
  margin-bottom: 2rem;
}

.actions {
  display: flex;
  gap: 1rem;
  justify-content: center;
}

@media (max-width: 640px) {
  .error-code {
    font-size: 4rem;
  }

  h1 {
    font-size: 1.5rem;
  }

  .actions {
    flex-direction: column;
  }
}
</style>
