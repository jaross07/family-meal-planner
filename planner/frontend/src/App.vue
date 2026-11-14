<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { apiFetch } from './api'
import CalendarView from './components/CalendarView.vue'
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

const today = new Date()
const year = ref(today.getFullYear())
const month = ref(today.getMonth())
const mealType = ref('dinner')
const selectedDate = ref(today.toISOString().slice(0, 10))

const attendance = ref([])
const contexts = reactive({})
const rules = ref([])
const recommendations = ref(null)
const myRatings = reactive({})
const loadingRecs = ref(false)
const planningRecipeId = ref(null)
const syncing = ref(false)
const showRulesModal = ref(false)

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
  authenticated.value = true
  await Promise.all([loadMonthAttendance(), loadRules(), loadDayDetails()])
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

async function loadMonthAttendance() {
  const firstDay = new Date(year.value, month.value, 1)
  const startOffset = firstDay.getDay()
  const gridStart = new Date(year.value, month.value, 1 - startOffset)
  const gridEnd = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + 41)

  const data = await apiFetch(
    `/api/attendance?from=${gridStart.toISOString().slice(0, 10)}&to=${gridEnd.toISOString().slice(0, 10)}`
  )
  attendance.value = data.items
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
    contexts[selectedDate.value] = ctx
    recommendations.value = recs
    mealieUnavailable.value = recs.mealie_available === false

    // Fetch current user's rating for each visible recommended recipe
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

function changeMonth(delta) {
  const d = new Date(year.value, month.value + delta, 1)
  year.value = d.getFullYear()
  month.value = d.getMonth()
  loadMonthAttendance()
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
  await loadMonthAttendance()
  if (entry.date === selectedDate.value) {
    await loadInitialData()
  }
}

async function handleRangeSet(payload) {
  await apiFetch('/api/attendance', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
  notify(`Updated ${payload.start_date} to ${payload.end_date}`)
  await loadMonthAttendance()
  await loadInitialData()
}

async function handleUndo() {
  const res = await apiFetch('/api/attendance/undo', { method: 'POST' })
  if (res.reverted > 0) {
    notify(`Reverted ${res.reverted} attendance entry(s)`)
    await loadMonthAttendance()
    await loadInitialData()
  }
}

async function handleUpdateContext(payload) {
  const updated = await apiFetch('/api/context', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
  contexts[payload.date] = updated
  await loadInitialData()
}

async function handleRateRecipe(recipeId, score) {
  await apiFetch(`/api/ratings/${recipeId}`, {
    method: 'PUT',
    body: JSON.stringify({ score }),
  })
  myRatings[recipeId] = score
  await loadInitialData()
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
  await apiFetch('/api/rules', { method: 'POST', body: JSON.stringify(payload) })
  await Promise.all([loadRules(), loadMonthAttendance(), loadDayDetails()])
}

async function handleDeleteRule(ruleId) {
  await apiFetch(`/api/rules/${ruleId}`, { method: 'DELETE' })
  await Promise.all([loadRules(), loadMonthAttendance(), loadDayDetails()])
}

async function handleAddException(ruleId, dateStr) {
  await apiFetch(`/api/rules/${ruleId}/exceptions`, {
    method: 'POST',
    body: JSON.stringify({ date: dateStr }),
  })
  await Promise.all([loadRules(), loadMonthAttendance(), loadDayDetails()])
}

async function handleUpdateProfile(payload) {
  await apiFetch('/api/profile', { method: 'PUT', body: JSON.stringify(payload) })
  await loadInitialData()
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

  <!-- Login View -->
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

  <!-- Authenticated App -->
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
        <button @click="showRulesModal = true">Rules &amp; Profile</button>
        <button @click="handleLogout">Sign Out</button>
      </div>
    </header>

    <main class="workspace">
      <CalendarView
        :year="year"
        :month="month"
        v-model:meal-type="mealType"
        :selected-date="selectedDate"
        :attendance="attendance"
        :household="household"
        :contexts="contexts"
        :undo-available="true"
        @change-month="changeMonth"
        @select-date="selectedDate = $event"
        @toggle-badge="handleToggleBadge"
        @range-set="handleRangeSet"
        @undo="handleUndo"
      />

      <DayPanel
        :selected-date="selectedDate"
        :meal-type="mealType"
        :recommendations="recommendations"
        :my-ratings="myRatings"
        :context="contexts[selectedDate]"
        :mealie-public-url="mealiePublicUrl"
        :loading="loadingRecs"
        :planning-recipe-id="planningRecipeId"
        @update-context="handleUpdateContext"
        @rate-recipe="handleRateRecipe"
        @plan-recipe="handlePlanRecipe"
        @show-vetoed="loadDayDetails(true)"
      />
    </main>

    <RulesModal
      v-if="showRulesModal"
      :rules="rules"
      :household="household"
      :current-user="currentUser"
      @close="showRulesModal = false"
      @create-rule="handleCreateRule"
      @delete-rule="handleDeleteRule"
      @add-exception="handleAddException"
      @update-profile="handleUpdateProfile"
    />
  </div>
</template>
