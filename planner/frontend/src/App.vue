<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiFetch } from './api'
import CalendarView from './components/CalendarView.vue'
import DayMealsModal from './components/DayMealsModal.vue'
import DayPanel from './components/DayPanel.vue'
import RulesModal from './components/RulesModal.vue'

const authenticated = ref(false)
const checkingSession = ref(true)
const loginForm = reactive({ username: '', password: '' })
const loginError = ref('')
const loggingIn = ref(false)

const currentUser = ref(null)
const household = ref([])
const mealieUnavailable = ref(false)
const toastMessage = ref('')

function toIso(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function parseIso(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

const todayIso = toIso(new Date())
const anchorDate = ref(todayIso)
const viewMode = ref('month')
const weekStartDay = ref(0)
const mealType = ref('dinner')
const selectedDate = ref(todayIso)

const attendance = ref([])
const contexts = reactive({})
const rules = ref([])
const recommendations = ref(null)
const myRatings = reactive({})
const loadingRecs = ref(false)
const planningRecipeId = ref(null)
const syncing = ref(false)
const showRulesModal = ref(false)
const dayModalDate = ref(null)

const mealiePublicUrl = `${window.location.protocol}//${window.location.hostname}`

function notify(msg) {
  toastMessage.value = msg
  setTimeout(() => {
    if (toastMessage.value === msg) toastMessage.value = ''
  }, 3500)
}

async function loadInitialData() {
  const prof = await apiFetch('/api/profile')
  currentUser.value = prof.current_user
  household.value = prof.household
  weekStartDay.value = prof.current_user.week_start_day ?? 0
  viewMode.value = prof.current_user.calendar_view || 'month'
  authenticated.value = true
  await Promise.all([loadVisibleRangeData(), loadRules(), loadDayDetails()])
}

async function handleLogin() {
  loginError.value = ''
  loggingIn.value = true
  try {
    await apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(loginForm),
    })
    loginForm.password = ''
    await loadInitialData()
  } catch (err) {
    loginError.value = err.message
  } finally {
    loggingIn.value = false
  }
}

async function handleLogout() {
  await apiFetch('/api/auth/logout', { method: 'POST' })
  authenticated.value = false
  currentUser.value = null
}

async function loadVisibleRangeData() {
  const anchor = parseIso(anchorDate.value)
  const start = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() - 14)
  const end = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + 45)
  const fromStr = toIso(start)
  const toStr = toIso(end)

  const [attData, ctxList] = await Promise.all([
    apiFetch(`/api/attendance?from=${fromStr}&to=${toStr}`),
    apiFetch(`/api/contexts?from=${fromStr}&to=${toStr}`),
  ])
  attendance.value = attData.items
  for (const c of ctxList) {
    contexts[`${c.date}:${c.meal_type}`] = c
  }
}

async function loadRules() {
  rules.value = await apiFetch('/api/rules')
}

async function loadDayDetails(includeVetoed = false) {
  loadingRecs.value = true
  try {
    const [ctx, recs] = await Promise.all([
      apiFetch(`/api/context?date=${selectedDate.value}&meal_type=${mealType.value}`),
      apiFetch(
        `/api/recommendations?date=${selectedDate.value}&meal_type=${mealType.value}&include_vetoed=${includeVetoed}`
      ),
    ])
    contexts[`${selectedDate.value}:${mealType.value}`] = ctx
    recommendations.value = recs
    mealieUnavailable.value = recs.mealie_available === false

    await Promise.all(
      (recs.items || []).map(async (item) => {
        const r = await apiFetch(`/api/ratings/${item.mealie_recipe_id}`)
        myRatings[item.mealie_recipe_id] = r.score
      })
    )
  } finally {
    loadingRecs.value = false
  }
}

function navigateCalendar(delta) {
  const d = parseIso(anchorDate.value)
  if (viewMode.value === '1week') {
    d.setDate(d.getDate() + delta * 7)
  } else if (viewMode.value === '2week') {
    d.setDate(d.getDate() + delta * 14)
  } else {
    d.setMonth(d.getMonth() + delta)
  }
  anchorDate.value = toIso(d)
  loadVisibleRangeData()
}

async function handleToggleBadge(entry) {
  const order = ['home', 'out', 'away']
  const nextStatus = order[(order.indexOf(entry.status) + 1) % order.length]
  await apiFetch('/api/attendance', {
    method: 'PUT',
    body: JSON.stringify({
      start_date: entry.date,
      meal_types: [entry.meal_type],
      mealie_user_id: entry.mealie_user_id,
      status: nextStatus,
    }),
  })
  await loadVisibleRangeData()
  if (entry.date === selectedDate.value) {
    await loadDayDetails()
  }
}

async function handleRangeSet(payload) {
  for (const uid of payload.user_ids) {
    await apiFetch('/api/attendance', {
      method: 'PUT',
      body: JSON.stringify({
        start_date: payload.start_date,
        end_date: payload.end_date,
        meal_types: payload.meal_types,
        mealie_user_id: uid,
        status: payload.status,
      }),
    })
  }
  notify(`Updated ${payload.start_date} to ${payload.end_date}`)
  await loadVisibleRangeData()
  await loadDayDetails()
}

async function handleUndo() {
  const res = await apiFetch('/api/attendance/undo', { method: 'POST' })
  if (res.reverted > 0) {
    notify(`Reverted ${res.reverted} attendance entry(s)`)
    await loadVisibleRangeData()
    await loadDayDetails()
  }
}

async function handleUpdateContext(payload) {
  const updated = await apiFetch('/api/context', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
  contexts[`${payload.date}:${payload.meal_type}`] = updated
  await loadDayDetails()
}

async function openDayModal(dateIso) {
  selectedDate.value = dateIso
  await Promise.all(
    ['breakfast', 'lunch', 'dinner'].map(async (mtype) => {
      const c = await apiFetch(`/api/context?date=${dateIso}&meal_type=${mtype}`)
      contexts[`${dateIso}:${mtype}`] = c
    })
  )
  dayModalDate.value = dateIso
}

const modalDayContexts = computed(() => {
  if (!dayModalDate.value) return {}
  return {
    breakfast: contexts[`${dayModalDate.value}:breakfast`],
    lunch: contexts[`${dayModalDate.value}:lunch`],
    dinner: contexts[`${dayModalDate.value}:dinner`],
  }
})

async function handleModalToggleMealPlanned(mtype, isPlanned) {
  const d = dayModalDate.value
  const existing = contexts[`${d}:${mtype}`] || {}
  const updated = await apiFetch('/api/context', {
    method: 'PUT',
    body: JSON.stringify({
      date: d,
      meal_type: mtype,
      require_leftovers: Boolean(existing.require_leftovers),
      max_prep_time: existing.max_prep_time ?? null,
      is_planned: isPlanned,
    }),
  })
  contexts[`${d}:${mtype}`] = updated
  if (d === selectedDate.value && mtype === mealType.value) {
    await loadDayDetails()
  }
}

async function handleModalToggleUserAttending(mtype, userId, attending) {
  const d = dayModalDate.value
  await apiFetch('/api/attendance', {
    method: 'PUT',
    body: JSON.stringify({
      start_date: d,
      meal_types: [mtype],
      mealie_user_id: userId,
      status: attending ? 'home' : 'out',
    }),
  })
  await loadVisibleRangeData()
  if (d === selectedDate.value && mtype === mealType.value) {
    await loadDayDetails()
  }
}

async function handleRateRecipe(recipeId, score) {
  await apiFetch(`/api/ratings/${recipeId}`, {
    method: 'PUT',
    body: JSON.stringify({ score }),
  })
  myRatings[recipeId] = score
  await loadDayDetails()
}

async function handlePlanRecipe(item) {
  planningRecipeId.value = item.mealie_recipe_id
  try {
    await apiFetch('/api/plan', {
      method: 'POST',
      body: JSON.stringify({
        date: selectedDate.value,
        meal_type: mealType.value,
        mealie_recipe_id: item.mealie_recipe_id,
      }),
    })
    mealieUnavailable.value = false
    notify(`Added "${item.name}" to Mealie's meal plan!`)
  } catch (err) {
    if (err.status === 503) mealieUnavailable.value = true
    notify(err.message)
  } finally {
    planningRecipeId.value = null
  }
}

async function handleSyncNow() {
  syncing.value = true
  try {
    const res = await apiFetch('/api/sync', { method: 'POST' })
    mealieUnavailable.value = false
    notify(`Synced ${res.synced_total} recipes from Mealie`)
    await loadInitialData()
  } catch (err) {
    if (err.status === 503) mealieUnavailable.value = true
    notify(err.message)
  } finally {
    syncing.value = false
  }
}

async function handleCreateRule(payload) {
  for (const uid of payload.user_ids) {
    await apiFetch('/api/rules', {
      method: 'POST',
      body: JSON.stringify({
        mealie_user_id: uid,
        weekday: payload.weekday,
        meal_type: payload.meal_type,
        status: payload.status,
        start_date: payload.start_date,
        end_date: payload.end_date,
        label: payload.label,
      }),
    })
  }
  await Promise.all([loadRules(), loadVisibleRangeData(), loadDayDetails()])
}

async function handleDeleteRule(ruleId) {
  await apiFetch(`/api/rules/${ruleId}`, { method: 'DELETE' })
  await Promise.all([loadRules(), loadVisibleRangeData(), loadDayDetails()])
}

async function handleAddException(ruleId, dateStr) {
  await apiFetch(`/api/rules/${ruleId}/exceptions`, {
    method: 'POST',
    body: JSON.stringify({ date: dateStr }),
  })
  await Promise.all([loadRules(), loadVisibleRangeData(), loadDayDetails()])
}

async function handleUpdateMember(memberId, payload) {
  await apiFetch(`/api/household/${memberId}`, { method: 'PUT', body: JSON.stringify(payload) })
  await loadInitialData()
}

async function handleUpdatePreferences(payload) {
  const updated = await apiFetch('/api/profile', { method: 'PUT', body: JSON.stringify(payload) })
  weekStartDay.value = updated.week_start_day
  viewMode.value = updated.calendar_view
  if (currentUser.value) {
    currentUser.value.week_start_day = updated.week_start_day
    currentUser.value.calendar_view = updated.calendar_view
  }
}

watch([selectedDate, mealType], () => {
  if (authenticated.value) loadDayDetails()
})

onMounted(async () => {
  try {
    await loadInitialData()
  } catch (_) {
    authenticated.value = false
  } finally {
    checkingSession.value = false
  }
})
</script>

<template>
  <div v-if="checkingSession" class="login-wrap">Loading...</div>

  <div v-else-if="!authenticated" class="login-wrap">
    <form class="login-card" @submit.prevent="handleLogin">
      <h1>Family Meal Planner</h1>
      <p>Sign in with your Mealie username and password.</p>
      <div v-if="loginError" class="error-msg">{{ loginError }}</div>
      <div class="field">
        <label>Username</label>
        <input v-model="loginForm.username" required autocomplete="username" />
      </div>
      <div class="field">
        <label>Password</label>
        <input v-model="loginForm.password" type="password" required autocomplete="current-password" />
      </div>
      <button class="primary" type="submit" style="width: 100%" :disabled="loggingIn">
        {{ loggingIn ? 'Signing in...' : 'Sign In' }}
      </button>
    </form>
  </div>

  <div v-else>
    <div v-if="mealieUnavailable" class="banner-warn">
      Mealie is currently unreachable. Showing cached recipes; adding meals to Mealie is temporarily disabled.
    </div>
    <div v-if="toastMessage" class="banner-warn" style="background: #dbeafe; color: #1e40af; border-color: #93c5fd">
      {{ toastMessage }}
    </div>

    <header class="topbar">
      <div class="brand">
        <span>🍽 Family Meal Planner</span>
        <span
          v-if="currentUser"
          class="diner-badge home"
          :style="{ backgroundColor: currentUser.color_code }"
        >
          {{ currentUser.initials }} · {{ currentUser.display_name }}
        </span>
      </div>

      <div class="nav-actions">
        <a :href="mealiePublicUrl" target="_blank" rel="noopener">
          <button type="button">Open Mealie</button>
        </a>
        <button :disabled="syncing" @click="handleSyncNow">
          {{ syncing ? 'Syncing...' : 'Sync Recipes' }}
        </button>
        <button @click="showRulesModal = true">Configure</button>
        <button @click="handleLogout">Sign Out</button>
      </div>
    </header>

    <main class="workspace">
      <CalendarView
        :anchor-date="anchorDate"
        v-model:view-mode="viewMode"
        :week-start-day="weekStartDay"
        v-model:meal-type="mealType"
        :selected-date="selectedDate"
        :attendance="attendance"
        :household="household"
        :contexts="contexts"
        :undo-available="true"
        @navigate="navigateCalendar"
        @select-date="selectedDate = $event"
        @open-day-modal="openDayModal"
        @toggle-badge="handleToggleBadge"
        @range-set="handleRangeSet"
        @undo="handleUndo"
      />

      <DayPanel
        :selected-date="selectedDate"
        :meal-type="mealType"
        :recommendations="recommendations"
        :my-ratings="myRatings"
        :context="contexts[`${selectedDate}:${mealType}`]"
        :mealie-public-url="mealiePublicUrl"
        :loading="loadingRecs"
        :planning-recipe-id="planningRecipeId"
        @update-context="handleUpdateContext"
        @rate-recipe="handleRateRecipe"
        @plan-recipe="handlePlanRecipe"
        @show-vetoed="loadDayDetails(true)"
        @open-day-modal="openDayModal"
      />
    </main>

    <DayMealsModal
      v-if="dayModalDate"
      :date="dayModalDate"
      :household="household"
      :attendance="attendance"
      :day-contexts="modalDayContexts"
      @close="dayModalDate = null"
      @toggle-meal-planned="handleModalToggleMealPlanned"
      @toggle-user-attending="handleModalToggleUserAttending"
    />

    <RulesModal
      v-if="showRulesModal"
      :rules="rules"
      :household="household"
      :current-user="currentUser"
      @close="showRulesModal = false"
      @create-rule="handleCreateRule"
      @delete-rule="handleDeleteRule"
      @add-exception="handleAddException"
      @update-member="handleUpdateMember"
      @update-preferences="handleUpdatePreferences"
    />
  </div>
</template>
