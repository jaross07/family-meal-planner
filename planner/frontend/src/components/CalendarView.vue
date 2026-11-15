<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  year: Number,
  month: Number, // 0-indexed (0=Jan)
  mealType: String,
  selectedDate: String,
  attendance: Array,
  household: Array,
  contexts: Object,
  undoAvailable: Boolean,
})

const emit = defineEmits([
  'update:mealType',
  'change-month',
  'select-date',
  'toggle-badge',
  'range-set',
  'undo',
])

const dragUserId = ref(props.household[0]?.mealie_user_id || '')
const dragStatus = ref('away')
const dragStart = ref(null)
const dragEnd = ref(null)

const monthLabel = computed(() => {
  const d = new Date(props.year, props.month, 1)
  return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
})

const calendarDays = computed(() => {
  const firstDay = new Date(props.year, props.month, 1)
  const startOffset = firstDay.getDay() // 0=Sun
  const gridStart = new Date(props.year, props.month, 1 - startOffset)
  const cells = []
  for (let i = 0; i < 42; i++) {
    const d = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i)
    const iso = d.toISOString().slice(0, 10)
    cells.push({
      iso,
      dayNum: d.getDate(),
      inMonth: d.getMonth() === props.month,
    })
  }
  return cells
})

const attendanceByDate = computed(() => {
  const map = {}
  for (const item of props.attendance) {
    if (item.meal_type !== props.mealType) continue
    if (!map[item.date]) map[item.date] = []
    map[item.date].push(item)
  }
  return map
})

function isInDragRange(iso) {
  if (!dragStart.value || !dragEnd.value) return false
  const [a, b] = dragStart.value <= dragEnd.value
    ? [dragStart.value, dragEnd.value]
    : [dragEnd.value, dragStart.value]
  return iso >= a && iso <= b
}

function onCellMouseDown(iso, e) {
  if (e.button !== 0) return
  emit('select-date', iso)
  dragStart.value = iso
  dragEnd.value = iso
}

function onCellMouseEnter(iso) {
  if (dragStart.value) {
    dragEnd.value = iso
  }
}

function onMouseUp() {
  if (dragStart.value && dragEnd.value && dragStart.value !== dragEnd.value) {
    const [start, end] = dragStart.value <= dragEnd.value
      ? [dragStart.value, dragEnd.value]
      : [dragEnd.value, dragStart.value]
    const targetUser = dragUserId.value || props.household[0]?.mealie_user_id
    if (targetUser) {
      emit('range-set', {
        start_date: start,
        end_date: end,
        meal_types: [props.mealType],
        mealie_user_id: targetUser,
        status: dragStatus.value,
      })
    }
  }
  dragStart.value = null
  dragEnd.value = null
}

function badgeStyle(entry) {
  if (entry.status === 'home') {
    return { backgroundColor: entry.color_code, borderColor: entry.color_code }
  }
  return { borderColor: entry.color_code }
}

function ruleLabelsForDate(iso) {
  const entries = attendanceByDate.value[iso] || []
  return entries.filter((e) => e.label).map((e) => `${e.display_name}: ${e.label}`)
}
</script>

<template>
  <div class="card" @mouseup="onMouseUp" @mouseleave="onMouseUp">
    <div class="cal-header">
      <div class="cal-controls">
        <button @click="emit('change-month', -1)">&larr;</button>
        <strong style="min-width: 140px; text-align: center">{{ monthLabel }}</strong>
        <button @click="emit('change-month', 1)">&rarr;</button>
        <select :value="mealType" @change="emit('update:mealType', $event.target.value)">
          <option value="dinner">Dinner</option>
          <option value="lunch">Lunch</option>
          <option value="breakfast">Breakfast</option>
        </select>
      </div>

      <div class="cal-controls">
        <span style="font-size: 0.78rem; color: var(--muted)">Drag range:</span>
        <select v-model="dragUserId" aria-label="Drag user">
          <option v-for="u in household.filter(m => m.active !== false)" :key="u.mealie_user_id" :value="u.mealie_user_id">
            {{ u.display_name }}
          </option>
        </select>
        <select v-model="dragStatus" aria-label="Drag status">
          <option value="away">Away</option>
          <option value="out">Out</option>
          <option value="home">Home</option>
        </select>
        <button :disabled="!undoAvailable" @click="emit('undo')">Undo last change</button>
      </div>
    </div>

    <div class="cal-grid">
      <div v-for="dow in ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']" :key="dow" class="cal-dow">
        {{ dow }}
      </div>

      <div
        v-for="cell in calendarDays"
        :key="cell.iso"
        class="cal-cell"
        :class="{
          outside: !cell.inMonth,
          selected: cell.iso === selectedDate,
          'drag-highlight': isInDragRange(cell.iso),
        }"
        @mousedown="onCellMouseDown(cell.iso, $event)"
        @mouseenter="onCellMouseEnter(cell.iso)"
      >
        <div class="cell-top">
          <span>{{ cell.dayNum }}</span>
          <span class="ctx-icons">
            <span v-if="contexts[cell.iso]?.max_prep_time" title="Fast & Easy">⚡</span>
            <span v-if="contexts[cell.iso]?.require_leftovers" title="Make Extra">🍱</span>
          </span>
        </div>

        <div class="badge-row">
          <button
            v-for="entry in attendanceByDate[cell.iso] || []"
            :key="entry.mealie_user_id"
            type="button"
            class="diner-badge"
            :class="[entry.status, { 'from-rule': entry.source === 'rule' }]"
            :style="badgeStyle(entry)"
            :title="`${entry.display_name}: ${entry.status} (${entry.source}) — click to cycle`"
            @mousedown.stop
            @click.stop="emit('toggle-badge', entry)"
          >
            {{ entry.initials }} · {{ entry.status }}
          </button>
        </div>

        <div v-for="lbl in ruleLabelsForDate(cell.iso)" :key="lbl" class="rule-tag" :title="lbl">
          {{ lbl }}
        </div>
      </div>
    </div>
  </div>
</template>
