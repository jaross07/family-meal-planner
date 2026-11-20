<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { parseIso, toIso, startOfWeek } from '../utils'

const props = defineProps({
  anchorDate: String,
  viewMode: String,
  weekStartDay: Number,
  mealType: String,
  selectedDate: String,
  attendance: Array,
  household: Array,
  contexts: Object,
  plannedMeals: Array,
  dayNotes: Object,
  holidays: Array,
  undoAvailable: Boolean,
})

const emit = defineEmits([
  'update:mealType',
  'update:viewMode',
  'navigate',
  'select-date',
  'open-day-modal',
  'toggle-badge',
  'range-set',
  'undo',
])

const dragTargetUser = ref('ALL')
const dragStatus = ref('away')
const dragMealScope = ref('all')
const dragStart = ref(null)
const dragEnd = ref(null)
const isDragging = ref(false)
const selectionAnchor = ref(null)
const selectedBulkDates = ref(new Set())
const rangeFrom = ref('')
const rangeTo = ref('')

const activeHousehold = computed(() =>
  (props.household || []).filter((m) => m.active !== false)
)

watch(
  activeHousehold,
  (list) => {
    if (dragTargetUser.value !== 'ALL' && !list.some((m) => m.mealie_user_id === dragTargetUser.value)) {
      dragTargetUser.value = 'ALL'
    }
  },
  { immediate: true }
)

const dowHeaders = computed(() =>
  props.weekStartDay === 1
    ? ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
)

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

const holidaysByDate = computed(() => {
  const map = {}
  for (const h of props.holidays || []) {
    if (!map[h.date]) map[h.date] = []
    map[h.date].push(h)
  }
  return map
})

const plannedByDate = computed(() => {
  const map = {}
  for (const item of props.plannedMeals || []) {
    if (item.meal_type !== props.mealType) continue
    if (!map[item.date]) map[item.date] = []
    map[item.date].push(item)
  }
  return map
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

function isDayMealPlanned(iso) {
  const ctx = props.contexts?.[`${iso}:${props.mealType}`]
  if (ctx && typeof ctx.is_planned === 'boolean') return ctx.is_planned
  return props.mealType === 'dinner'
}

function expandIsoRange(startIso, endIso) {
  const [s, e] = startIso <= endIso ? [startIso, endIso] : [endIso, startIso]
  const out = []
  let cur = parseIso(s)
  const last = parseIso(e)
  while (cur <= last && out.length < 62) {
    out.push(toIso(cur))
    cur = new Date(cur.getFullYear(), cur.getMonth(), cur.getDate() + 1)
  }
  return out
}

function syncInputsFromSet(dateSet) {
  const sorted = Array.from(dateSet).sort()
  if (sorted.length > 0) {
    rangeFrom.value = sorted[0]
    rangeTo.value = sorted[sorted.length - 1]
  } else {
    rangeFrom.value = ''
    rangeTo.value = ''
  }
}

function isCellHighlighted(iso) {
  if (isDragging.value && dragStart.value && dragEnd.value) {
    const [a, b] = dragStart.value <= dragEnd.value
      ? [dragStart.value, dragEnd.value]
      : [dragEnd.value, dragStart.value]
    if (iso >= a && iso <= b) return true
  }
  return selectedBulkDates.value.has(iso)
}

function onCellPointerDown(iso, e) {
  if (e.button !== undefined && e.button !== 0) return
  if (e.target && e.target.closest('button, select, input, a')) return
  e.preventDefault()
  emit('select-date', iso)

  const isCtrl = e.ctrlKey || e.metaKey
  const isShift = e.shiftKey

  if (isShift && selectionAnchor.value) {
    const next = new Set(isCtrl ? selectedBulkDates.value : [])
    for (const d of expandIsoRange(selectionAnchor.value, iso)) {
      next.add(d)
    }
    selectedBulkDates.value = next
    syncInputsFromSet(next)
    return
  }

  if (isCtrl) {
    const next = new Set(selectedBulkDates.value)
    if (next.has(iso)) {
      next.delete(iso)
    } else {
      next.add(iso)
    }
    selectedBulkDates.value = next
    selectionAnchor.value = iso
    syncInputsFromSet(next)
    return
  }

  // Plain click or start of drag
  selectionAnchor.value = iso
  dragStart.value = iso
  dragEnd.value = iso
  isDragging.value = false
  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function onCellPointerEnter(iso) {
  if (dragStart.value) {
    dragEnd.value = iso
    if (iso !== dragStart.value) isDragging.value = true
  }
}

function onWindowPointerMove(e) {
  if (!dragStart.value) return
  const el = document.elementFromPoint(e.clientX, e.clientY)
  const cell = el?.closest?.('[data-date]')
  if (cell?.dataset?.date) {
    dragEnd.value = cell.dataset.date
    if (cell.dataset.date !== dragStart.value) isDragging.value = true
  }
}

function clearBulkSelection() {
  selectedBulkDates.value = new Set()
  rangeFrom.value = ''
  rangeTo.value = ''
}

function applyBulkSelection() {
  const userIds =
    dragTargetUser.value === 'ALL'
      ? activeHousehold.value.map((m) => m.mealie_user_id)
      : [dragTargetUser.value]
  const mealTypes =
    dragMealScope.value === 'all'
      ? ['breakfast', 'lunch', 'dinner']
      : [props.mealType]
  if (!userIds.length) return

  // If multiple non-contiguous dates were Ctrl+clicked, send explicit dates list; otherwise use date range
  if (selectedBulkDates.value.size > 1) {
    const sorted = Array.from(selectedBulkDates.value).sort()
    emit('range-set', {
      dates: sorted,
      start_date: sorted[0],
      end_date: sorted[sorted.length - 1],
      meal_types: mealTypes,
      user_ids: userIds,
      status: dragStatus.value,
    })
    clearBulkSelection()
    return
  }

  if (rangeFrom.value && rangeTo.value) {
    const [s, e] = rangeFrom.value <= rangeTo.value
      ? [rangeFrom.value, rangeTo.value]
      : [rangeTo.value, rangeFrom.value]
    emit('range-set', {
      start_date: s,
      end_date: e,
      meal_types: mealTypes,
      user_ids: userIds,
      status: dragStatus.value,
    })
    clearBulkSelection()
  }
}

function onPointerUp() {
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  if (dragStart.value && dragEnd.value) {
    if (isDragging.value && dragStart.value !== dragEnd.value) {
      const next = new Set(expandIsoRange(dragStart.value, dragEnd.value))
      selectedBulkDates.value = next
      syncInputsFromSet(next)
    } else {
      // Single plain click selects just that day as anchor
      const next = new Set([dragStart.value])
      selectedBulkDates.value = next
      syncInputsFromSet(next)
    }
  }
  dragStart.value = null
  dragEnd.value = null
  isDragging.value = false
}

onUnmounted(() => {
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
})

function badgeStyle(entry) {
  if (entry.status === 'home') {
    return { backgroundColor: entry.color_code, borderColor: entry.color_code }
  }
  return { borderColor: entry.color_code }
}
</script>

<template>
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

        <select :value="mealType" @change="emit('update:mealType', $event.target.value)" aria-label="Meal type">
          <option value="dinner">Dinner</option>
          <option value="lunch">Lunch</option>
          <option value="breakfast">Breakfast</option>
        </select>
      </div>

      <div class="cal-controls" title="Drag across calendar cells or pick start/end dates to bulk-set attendance">
        <span style="font-size: 0.78rem; color: var(--muted)">Bulk set:</span>
        <select v-model="dragTargetUser" aria-label="Target user">
          <option value="ALL">All Family</option>
          <option v-for="u in activeHousehold" :key="u.mealie_user_id" :value="u.mealie_user_id">
            {{ u.display_name }}
          </option>
        </select>
        <select v-model="dragStatus" aria-label="Status">
          <option value="away">Away</option>
          <option value="out">Out</option>
          <option value="home">Home</option>
        </select>
        <select v-model="dragMealScope" aria-label="Meals to update">
          <option value="all">All Meals</option>
          <option value="current">This Meal</option>
        </select>
        <template v-if="selectedBulkDates.size > 1">
          <span style="font-size: 0.78rem; font-weight: 600; color: #1d4ed8; background: #dbeafe; padding: 3px 8px; border-radius: 6px">
            {{ selectedBulkDates.size }} days selected
          </span>
        </template>
        <template v-else>
          <input v-model="rangeFrom" type="date" aria-label="Start date" style="padding: 4px 6px; font-size: 0.78rem" />
          <input v-model="rangeTo" type="date" aria-label="End date" style="padding: 4px 6px; font-size: 0.78rem" />
        </template>
        <button class="primary" :disabled="selectedBulkDates.size === 0 && (!rangeFrom || !rangeTo)" @click="applyBulkSelection">Apply</button>
        <button v-if="selectedBulkDates.size > 1" @click="clearBulkSelection">Clear</button>
        <button :disabled="!undoAvailable" @click="emit('undo')">Undo</button>
      </div>
    </div>

    <div style="font-size: 0.75rem; color: var(--muted); margin-bottom: 8px">
      Tip: Drag across days, Shift+Click a range, or Ctrl/Cmd+Click multiple days, then click Apply; double-click a day to edit all meals.
    </div>

    <div class="cal-grid" style="touch-action: none; user-select: none; -webkit-user-select: none">
      <div v-for="dow in dowHeaders" :key="dow" class="cal-dow">
        {{ dow }}
      </div>

      <div
        v-for="cell in calendarDays"
        :key="cell.iso"
        :data-date="cell.iso"
        class="cal-cell"
        :class="{
          outside: !cell.inMonth,
          selected: cell.iso === selectedDate,
          'drag-highlight': isCellHighlighted(cell.iso),
        }"
        :style="{ minHeight: viewMode === 'month' ? '92px' : '136px' }"
        @pointerdown="onCellPointerDown(cell.iso, $event)"
        @pointerenter="onCellPointerEnter(cell.iso)"
        @dblclick.stop="emit('open-day-modal', cell.iso)"
      >
        <div class="cell-top">
          <span>
            <span v-if="viewMode !== 'month' || cell.dayNum === 1" style="color: var(--muted); margin-right: 3px">
              {{ cell.monthShort }}
            </span>
            {{ cell.dayNum }}
          </span>
          <span class="ctx-icons">
            <span v-if="dayNotes?.[cell.iso]" :title="dayNotes[cell.iso]">📝</span>
            <span v-if="!isDayMealPlanned(cell.iso)" title="Meal not planned">🚫</span>
            <span v-if="contexts[`${cell.iso}:${mealType}`]?.max_prep_time" title="Fast & Easy">⚡</span>
            <span v-if="contexts[`${cell.iso}:${mealType}`]?.require_leftovers" title="Make Extra">🍱</span>
            <span v-if="contexts[`${cell.iso}:${mealType}`]?.eating_leftovers" title="Eating Leftovers">♻</span>
            <span v-if="contexts[`${cell.iso}:${mealType}`]?.henleys_choice" title="Henley's Choice">👑</span>
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
            :title="`${entry.display_name}: ${entry.status}${entry.label ? ' (' + entry.label + ')' : ''} — click to cycle`"
            @pointerdown.stop
            @click.stop="emit('toggle-badge', entry)"
          >
            {{ entry.initials }} · {{ entry.status }}
          </button>
        </div>
        <div
          v-for="(hol, hIdx) in holidaysByDate[cell.iso] || []"
          :key="`hol-${cell.iso}-${hIdx}`"
          :style="hol.source === 'family'
            ? 'margin-top: 3px; background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; border-radius: 5px; padding: 1px 5px; font-size: 0.68rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis'
            : 'margin-top: 3px; background: #ede9fe; color: #5b21b6; border: 1px solid #c4b5fd; border-radius: 5px; padding: 1px 5px; font-size: 0.68rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis'"
          :title="hol.label"
        >
          {{ hol.emoji }} {{ hol.label }}
        </div>

        <div
          v-for="pm in plannedByDate[cell.iso] || []"
          :key="pm.id || pm.mealie_recipe_id"
          style="margin-top: 4px; background: #dcfce7; color: #166534; border: 1px solid #86efac; border-radius: 5px; padding: 2px 5px; font-size: 0.7rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis"
          :title="`Planned: ${pm.name}`"
        >
          ✓ {{ pm.name }}
        </div>
      </div>
    </div>
  </div>
</template>
