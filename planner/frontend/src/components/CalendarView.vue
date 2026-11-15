<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  anchorDate: String, // YYYY-MM-DD
  viewMode: String, // 'month' | '2week' | '1week'
  weekStartDay: Number, // 0 = Sun, 1 = Mon
  mealType: String,
  selectedDate: String,
  attendance: Array,
  household: Array,
  contexts: Object,
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
const dragStart = ref(null)
const dragEnd = ref(null)

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
  return props.mealType !== 'breakfast'
}

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
    const userIds =
      dragTargetUser.value === 'ALL'
        ? activeHousehold.value.map((m) => m.mealie_user_id)
        : [dragTargetUser.value]
    if (userIds.length) {
      emit('range-set', {
        start_date: start,
        end_date: end,
        meal_types: [props.mealType],
        user_ids: userIds,
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

      <div class="cal-controls" title="Click and drag across multiple days on the calendar to bulk-set attendance">
        <span style="font-size: 0.78rem; color: var(--muted)">Click &amp; drag days:</span>
        <select v-model="dragTargetUser" aria-label="Drag target user">
          <option value="ALL">All Family</option>
          <option v-for="u in activeHousehold" :key="u.mealie_user_id" :value="u.mealie_user_id">
            {{ u.display_name }}
          </option>
        </select>
        <select v-model="dragStatus" aria-label="Drag status">
          <option value="away">Away</option>
          <option value="out">Out</option>
          <option value="home">Home</option>
        </select>
        <button :disabled="!undoAvailable" @click="emit('undo')">Undo</button>
      </div>
    </div>

    <div style="font-size: 0.75rem; color: var(--muted); margin-bottom: 8px">
      Tip: Double-click any day to check/uncheck Breakfast, Lunch &amp; Dinner attendance.
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
          'drag-highlight': isInDragRange(cell.iso),
        }"
        :style="{ minHeight: viewMode === 'month' ? '102px' : '150px' }"
        @mousedown="onCellMouseDown(cell.iso, $event)"
        @mouseenter="onCellMouseEnter(cell.iso)"
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
            <span v-if="!isDayMealPlanned(cell.iso)" title="Meal not planned">🚫</span>
            <span v-if="contexts[`${cell.iso}:${mealType}`]?.max_prep_time" title="Fast & Easy">⚡</span>
            <span v-if="contexts[`${cell.iso}:${mealType}`]?.require_leftovers" title="Make Extra">🍱</span>
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
