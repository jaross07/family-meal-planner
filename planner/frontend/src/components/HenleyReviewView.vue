<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  anchorDate: String,
  viewMode: String,
  weekStartDay: Number,
  mealType: String,
  selectedDate: String,
  plannedMeals: Array,
  myRatings: Object,
  myNotes: Object,
  familyNotes: Object,
  mealiePublicUrl: String,
})

const emit = defineEmits([
  'update:mealType',
  'update:viewMode',
  'navigate',
  'select-date',
  'save-review',
])

const draftNotes = ref({})
const draftScores = ref({})
const brokenImages = ref({})
const savingId = ref(null)

const dowHeaders = computed(() =>
  props.weekStartDay === 1
    ? ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
)

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

const calendarDays = computed(() => {
  const anchor = parseIso(props.anchorDate)
  let gridStart
  let totalCells

  if (props.viewMode === '1week') {
    gridStart = startOfWeek(anchor, props.weekStartDay)
    totalCells = 7
  } else if (props.viewMode === '2week') {
    gridStart = startOfWeek(anchor, props.weekStartDay)
    totalCells = 14
  } else {
    const firstOfMonth = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
    gridStart = startOfWeek(firstOfMonth, props.weekStartDay)
    totalCells = 42
  }

  const cells = []
  for (let i = 0; i < totalCells; i++) {
    const d = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i)
    const iso = toIso(d)
    cells.push({
      iso,
      dayNum: d.getDate(),
      monthShort: d.toLocaleDateString('en-US', { month: 'short' }),
      inMonth: props.viewMode !== 'month' || d.getMonth() === anchor.getMonth(),
    })
  }
  return cells
})

const headerLabel = computed(() => {
  const anchor = parseIso(props.anchorDate)
  if (props.viewMode === 'month') {
    return anchor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
  }
  const days = calendarDays.value
  const first = parseIso(days[0].iso)
  const last = parseIso(days[days.length - 1].iso)
  const fStr = first.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  const lStr = last.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  return `${fStr} – ${lStr}`
})

const plannedByDate = computed(() => {
  const map = {}
  for (const item of props.plannedMeals || []) {
    if (props.mealType !== 'all' && item.meal_type !== props.mealType) continue
    if (!map[item.date]) map[item.date] = []
    map[item.date].push(item)
  }
  return map
})

const selectedDayMeals = computed(() => plannedByDate.value[props.selectedDate] || [])

const formattedSelectedDate = computed(() => {
  if (!props.selectedDate) return ''
  const d = parseIso(props.selectedDate)
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  })
})

watch(
  [selectedDayMeals, () => props.myRatings, () => props.myNotes],
  () => {
    for (const m of selectedDayMeals.value) {
      const rid = m.mealie_recipe_id
      if (draftScores.value[rid] === undefined) {
        draftScores.value[rid] = props.myRatings?.[rid] ?? 0
      }
      if (draftNotes.value[rid] === undefined) {
        draftNotes.value[rid] = props.myNotes?.[rid] ?? ''
      }
    }
  },
  { immediate: true, deep: true }
)

function ratingBadgeEmoji(recipeId) {
  const s = props.myRatings?.[recipeId]
  if (s === 1) return '👍'
  if (s === -1) return '👎'
  if (s === 0 && props.myNotes?.[recipeId]) return '😐'
  return '⭐'
}

function pillColors(recipeId) {
  const s = props.myRatings?.[recipeId]
  if (s === 1) return { background: '#dcfce7', color: '#166534', borderColor: '#86efac' }
  if (s === -1) return { background: '#fee2e2', color: '#991b1b', borderColor: '#fca5a5' }
  if (s === 0 && props.myNotes?.[recipeId]) return { background: '#fef9c3', color: '#854d0e', borderColor: '#fde047' }
  return { background: '#eff6ff', color: '#1d4ed8', borderColor: '#93c5fd' }
}

function setScore(recipeId, score) {
  draftScores.value[recipeId] = score
}

async function submitReview(recipeId) {
  savingId.value = recipeId
  try {
    await emit('save-review', {
      recipeId,
      score: draftScores.value[recipeId] ?? 0,
      note: draftNotes.value[recipeId] ?? '',
    })
  } finally {
    savingId.value = null
  }
}

function recipeImageUrl(recipeId) {
  return `/api/recipes/${recipeId}/image`
}
</script>

<template>
  <main class="workspace">
    <!-- Left: Planned Meals Calendar for Rating -->
    <div class="card">
      <div class="cal-header">
        <div class="cal-controls">
          <button @click="emit('navigate', -1)">&larr;</button>
          <strong style="min-width: 155px; text-align: center">{{ headerLabel }}</strong>
          <button @click="emit('navigate', 1)">&rarr;</button>

          <select :value="viewMode" @change="emit('update:viewMode', $event.target.value)" aria-label="Calendar span">
            <option value="month">Month</option>
            <option value="2week">2 Weeks</option>
            <option value="1week">1 Week</option>
          </select>

          <select :value="mealType" @change="emit('update:mealType', $event.target.value)" aria-label="Meal filter">
            <option value="all">All Meals</option>
            <option value="dinner">Dinner</option>
            <option value="lunch">Lunch</option>
            <option value="breakfast">Breakfast</option>
          </select>
        </div>

        <div style="display: flex; gap: 8px; font-size: 0.78rem; color: var(--muted); flex-wrap: wrap">
          <span>⭐ Not rated yet</span>
          <span>👍 Yum</span>
          <span>😐 Okay</span>
          <span>👎 Yuck</span>
        </div>
      </div>

      <div class="cal-grid">
        <div v-for="dow in dowHeaders" :key="dow" class="cal-dow">
          {{ dow }}
        </div>

        <div
          v-for="cell in calendarDays"
          :key="cell.iso"
          class="cal-cell"
          :class="{
            outside: !cell.inMonth,
            selected: cell.iso === selectedDate,
          }"
          :style="{ minHeight: viewMode === 'month' ? '92px' : '136px' }"
          @click="emit('select-date', cell.iso)"
        >
          <div class="cell-top">
            <span>
              <span v-if="viewMode !== 'month' || cell.dayNum === 1" style="color: var(--muted); margin-right: 3px">
                {{ cell.monthShort }}
              </span>
              {{ cell.dayNum }}
            </span>
          </div>

          <div
            v-for="pm in plannedByDate[cell.iso] || []"
            :key="pm.id || `${pm.date}-${pm.meal_type}-${pm.mealie_recipe_id}`"
            style="margin-top: 4px; border: 1px solid; border-radius: 6px; padding: 3px 6px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis"
            :style="pillColors(pm.mealie_recipe_id)"
            :title="`${pm.name}${myNotes?.[pm.mealie_recipe_id] ? ' — ' + myNotes[pm.mealie_recipe_id] : ''}`"
          >
            {{ ratingBadgeEmoji(pm.mealie_recipe_id) }} {{ pm.name }}
          </div>
        </div>
      </div>
    </div>

    <!-- Right: Focused Rating & Notes Card for Selected Day -->
    <div class="card">
      <div class="panel-section">
        <h2 style="margin: 0 0 4px; font-size: 1.2rem">⭐ {{ formattedSelectedDate }}</h2>
        <div style="font-size: 0.85rem; color: var(--muted)">
          Tap a meal on the calendar to rate it and leave a note!
        </div>
      </div>

      <div v-if="!selectedDayMeals.length" style="color: var(--muted); padding: 18px 0; text-align: center">
        No meals planned on this day yet. Pick another day with a meal card on the calendar!
      </div>

      <div v-else>
        <div
          v-for="meal in selectedDayMeals"
          :key="meal.id || meal.mealie_recipe_id"
          style="border: 1px solid var(--border); border-radius: 12px; padding: 14px; margin-bottom: 14px; background: #fff"
        >
          <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 12px">
            <img
              v-if="!brokenImages[meal.mealie_recipe_id]"
              :src="recipeImageUrl(meal.mealie_recipe_id)"
              alt=""
              style="width: 72px; height: 72px; object-fit: cover; border-radius: 10px; flex-shrink: 0; border: 1px solid var(--border)"
              @error="brokenImages[meal.mealie_recipe_id] = true"
            />
            <div>
              <div style="font-size: 0.75rem; text-transform: uppercase; font-weight: 700; color: var(--muted)">
                {{ meal.meal_type }}
              </div>
              <div style="font-size: 1.08rem; font-weight: 700; color: var(--text)">
                {{ meal.name }}
              </div>
            </div>
          </div>

          <!-- Big Kid-Friendly Rating Buttons -->
          <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px">
            <button
              type="button"
              style="padding: 10px 6px; font-size: 0.95rem; font-weight: 600; border-radius: 10px"
              :class="{ 'active-dislike': (draftScores[meal.mealie_recipe_id] ?? 0) === -1 }"
              @click="setScore(meal.mealie_recipe_id, -1)"
            >
              👎 Yuck
            </button>
            <button
              type="button"
              style="padding: 10px 6px; font-size: 0.95rem; font-weight: 600; border-radius: 10px"
              :class="{ 'active-neutral': (draftScores[meal.mealie_recipe_id] ?? 0) === 0 }"
              @click="setScore(meal.mealie_recipe_id, 0)"
            >
              😐 Okay
            </button>
            <button
              type="button"
              style="padding: 10px 6px; font-size: 0.95rem; font-weight: 600; border-radius: 10px"
              :class="{ 'active-like': (draftScores[meal.mealie_recipe_id] ?? 0) === 1 }"
              @click="setScore(meal.mealie_recipe_id, 1)"
            >
              👍 Yum!
            </button>
          </div>

          <!-- Note Input -->
          <div style="margin-bottom: 10px">
            <label style="display: block; font-size: 0.8rem; font-weight: 600; color: var(--muted); margin-bottom: 4px">
              Notes (what did you like or want changed?)
            </label>
            <textarea
              v-model="draftNotes[meal.mealie_recipe_id]"
              rows="2"
              placeholder="e.g., Loved the pasta! Not too spicy..."
              style="width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid var(--border); border-radius: 8px; font-family: inherit; font-size: 0.9rem; resize: vertical"
            />
          </div>

          <button
            type="button"
            class="primary"
            style="width: 100%; padding: 9px; font-weight: 600"
            :disabled="savingId === meal.mealie_recipe_id"
            @click="submitReview(meal.mealie_recipe_id)"
          >
            {{ savingId === meal.mealie_recipe_id ? 'Saving...' : 'Save Rating & Note' }}
          </button>
        </div>
      </div>
    </div>
  </main>
</template>
