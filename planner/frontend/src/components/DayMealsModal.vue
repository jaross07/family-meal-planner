<script setup>
import { computed } from 'vue'

const props = defineProps({
  date: String,
  household: Array,
  attendance: Array,
  dayContexts: Object, // { breakfast: {...}, lunch: {...}, dinner: {...} }
})

const emit = defineEmits(['close', 'toggle-meal-planned', 'toggle-user-attending'])

const meals = [
  { key: 'breakfast', label: 'Breakfast' },
  { key: 'lunch', label: 'Lunch' },
  { key: 'dinner', label: 'Dinner' },
]

const formattedDate = computed(() => {
  if (!props.date) return ''
  const [y, m, d] = props.date.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
})

const activeHousehold = computed(() =>
  (props.household || []).filter((m) => m.active !== false)
)

function isMealPlanned(mealKey) {
  const ctx = props.dayContexts?.[mealKey]
  if (ctx && typeof ctx.is_planned === 'boolean') return ctx.is_planned
  return mealKey === 'dinner'
}

function getUserEntry(mealKey, userId) {
  return (props.attendance || []).find(
    (a) => a.date === props.date && a.meal_type === mealKey && a.mealie_user_id === userId
  )
}

function isAttending(mealKey, userId) {
  const entry = getUserEntry(mealKey, userId)
  return entry ? entry.status === 'home' : true
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="modal-box" style="max-width: 540px">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px">
        <div>
          <h2 style="margin: 0; font-size: 1.15rem">{{ formattedDate }}</h2>
          <div style="font-size: 0.8rem; color: var(--muted)">
            Choose which meals to plan and who will be eating
          </div>
        </div>
        <button @click="emit('close')">Done</button>
      </div>

      <div
        v-for="meal in meals"
        :key="meal.key"
        style="border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-bottom: 12px"
        :style="{ background: isMealPlanned(meal.key) ? '#fff' : '#f8fafc' }"
      >
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px">
          <strong style="font-size: 1rem">{{ meal.label }}</strong>
          <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 0.85rem; font-weight: 600">
            <input
              type="checkbox"
              :checked="isMealPlanned(meal.key)"
              @change="emit('toggle-meal-planned', meal.key, $event.target.checked)"
            />
            Plan food for {{ meal.label.toLowerCase() }}
          </label>
        </div>

        <div
          style="display: flex; gap: 12px; flex-wrap: wrap"
          :style="{ opacity: isMealPlanned(meal.key) ? 1 : 0.55 }"
        >
          <label
            v-for="member in activeHousehold"
            :key="member.mealie_user_id"
            style="display: flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border); cursor: pointer; background: #fff"
          >
            <input
              type="checkbox"
              :checked="isAttending(meal.key, member.mealie_user_id)"
              @change="emit('toggle-user-attending', meal.key, member.mealie_user_id, $event.target.checked)"
            />
            <span
              class="diner-badge home"
              :style="{ backgroundColor: member.color_code, padding: '2px 7px' }"
            >
              {{ member.initials }}
            </span>
            <span style="font-size: 0.875rem; font-weight: 500">{{ member.display_name }}</span>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>
