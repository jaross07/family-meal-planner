<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiFetch } from '../api'

const props = defineProps({
  anchorDate: String,
  weekStartDay: Number,
  mealType: String,
})

const emit = defineEmits(['close', 'planned'])

function parseIso(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function toIso(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function startOfWeek(d, startDay) {
  const dow = d.getDay()
  const diff = (dow - startDay + 7) % 7
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() - diff)
}

const weekStart = ref(toIso(startOfWeek(parseIso(props.anchorDate), props.weekStartDay ?? 0)))
const loading = ref(false)
const submitting = ref(false)
const previewDays = ref([])
const selectedByDate = ref({})
const includeByDate = ref({})

const weekRangeLabel = computed(() => {
  const s = parseIso(weekStart.value)
  const e = new Date(s.getFullYear(), s.getMonth(), s.getDate() + 6)
  const fStr = s.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  const lStr = e.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  return `${fStr} – ${lStr}`
})

function formatDay(iso) {
  const d = parseIso(iso)
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

async function loadPreview() {
  loading.value = true
  try {
    const data = await apiFetch(
      `/api/week-preview?start_date=${weekStart.value}&meal_type=${props.mealType}`
    )
    previewDays.value = data.days || []
    const nextSel = {}
    const nextInc = {}
    for (const day of previewDays.value) {
      nextSel[day.date] = day.selected_recipe_id || ''
      nextInc[day.date] = Boolean(day.is_planned && day.selected_recipe_id)
    }
    selectedByDate.value = nextSel
    includeByDate.value = nextInc
  } finally {
    loading.value = false
  }
}

function shiftWeek(delta) {
  const d = parseIso(weekStart.value)
  d.setDate(d.getDate() + delta * 7)
  weekStart.value = toIso(d)
}

const plannedCount = computed(() =>
  previewDays.value.filter((d) => includeByDate.value[d.date] && selectedByDate.value[d.date]).length
)

async function commitBatch() {
  const items = previewDays.value
    .filter((d) => includeByDate.value[d.date] && selectedByDate.value[d.date])
    .map((d) => ({
      date: d.date,
      meal_type: props.mealType,
      mealie_recipe_id: selectedByDate.value[d.date],
    }))

  if (!items.length) return
  submitting.value = true
  try {
    const res = await apiFetch('/api/plan-week', {
      method: 'POST',
      body: JSON.stringify({ items }),
    })
    emit('planned', res.count)
    emit('close')
  } finally {
    submitting.value = false
  }
}

watch(weekStart, loadPreview)
onMounted(loadPreview)
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="modal-box" style="max-width: 720px">
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 14px">
        <div>
          <h2 style="margin: 0; font-size: 1.2rem; text-transform: capitalize">
            Batch Plan Week ({{ mealType }})
          </h2>
          <div style="font-size: 0.8rem; color: var(--muted)">
            Preview top picks for each night based on who is home, adjust any pick, and send to Mealie.
          </div>
        </div>
        <button @click="emit('close')">Close</button>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px">
        <div style="display: flex; align-items: center; gap: 8px">
          <button @click="shiftWeek(-1)">&larr; Prev Week</button>
          <strong>{{ weekRangeLabel }}</strong>
          <button @click="shiftWeek(1)">Next Week &rarr;</button>
        </div>
        <button @click="loadPreview" :disabled="loading">Refresh Picks</button>
      </div>

      <div v-if="loading" style="padding: 20px 0; color: var(--muted)">Building 7-day lineup...</div>

      <div v-else>
        <div
          v-for="day in previewDays"
          :key="day.date"
          style="display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; padding: 10px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px"
          :style="{ background: includeByDate[day.date] ? '#fff' : '#f8fafc' }"
        >
          <div style="min-width: 170px">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-weight: 600">
              <input
                type="checkbox"
                v-model="includeByDate[day.date]"
                :disabled="!day.candidates?.length"
              />
              <span>{{ formatDay(day.date) }}</span>
            </label>
            <div style="font-size: 0.76rem; color: var(--muted); margin-left: 24px">
              <span v-if="!day.is_planned">Meal skipped</span>
              <span v-else-if="day.diners?.length">
                Diners: {{ day.diners.map((d) => d.display_name).join(', ') }}
              </span>
              <span v-else>No diners home</span>
            </div>
          </div>

          <div style="flex: 1; min-width: 240px">
            <select
              v-if="day.candidates?.length"
              v-model="selectedByDate[day.date]"
              :disabled="!includeByDate[day.date]"
              style="width: 100%"
            >
              <option v-for="c in day.candidates" :key="c.mealie_recipe_id" :value="c.mealie_recipe_id">
                {{ c.name }} (Score {{ c.score }}{{ c.prep_time_minutes ? `, ${c.prep_time_minutes}m` : '' }}{{ c.leftover_badge ? ` • ${c.leftover_badge}` : '' }})
              </option>
            </select>
            <span v-else style="font-size: 0.82rem; color: var(--muted)">
              {{ day.is_planned ? 'No matching recipes available' : 'Not planning this meal' }}
            </span>
          </div>
        </div>
      </div>

      <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px">
        <button @click="emit('close')">Cancel</button>
        <button
          class="primary"
          :disabled="submitting || plannedCount === 0"
          @click="commitBatch"
        >
          {{ submitting ? 'Sending to Mealie...' : `Send ${plannedCount} Meal(s) to Mealie` }}
        </button>
      </div>
    </div>
  </div>
</template>
