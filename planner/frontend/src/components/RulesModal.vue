<script setup>
import { reactive, ref } from 'vue'

const props = defineProps({
  rules: Array,
  household: Array,
  currentUser: Object,
})

const emit = defineEmits(['close', 'create-rule', 'delete-rule', 'add-exception', 'update-profile'])

const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const newRule = reactive({
  mealie_user_id: props.household[0]?.mealie_user_id || '',
  weekday: 2,
  meal_type: 'dinner',
  status: 'out',
  start_date: new Date().toISOString().slice(0, 10),
  end_date: '',
  label: '',
})

const exceptionDates = reactive({})
const profileForm = reactive({
  display_name: props.currentUser?.display_name || '',
  initials: props.currentUser?.initials || '',
  color_code: props.currentUser?.color_code || '#3B82F6',
})
const profileSaved = ref(false)

function submitRule() {
  if (!newRule.label.trim()) return
  emit('create-rule', {
    ...newRule,
    end_date: newRule.end_date || null,
  })
  newRule.label = ''
}

function submitProfile() {
  emit('update-profile', { ...profileForm })
  profileSaved.value = true
  setTimeout(() => (profileSaved.value = false), 2000)
}

function userName(uid) {
  return props.household.find((u) => u.mealie_user_id === uid)?.display_name || uid
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="modal-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px">
        <h2 style="margin: 0; font-size: 1.2rem">Recurring Rules &amp; Profile</h2>
        <button @click="emit('close')">Close</button>
      </div>

      <!-- Profile Badge Settings -->
      <div class="panel-section">
        <h3 style="margin: 0 0 8px; font-size: 0.95rem">My Badge &amp; Color</h3>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
          <input v-model="profileForm.display_name" placeholder="Name" style="width: 130px" />
          <input v-model="profileForm.initials" placeholder="Initials" maxlength="4" style="width: 75px" />
          <input v-model="profileForm.color_code" type="color" style="width: 46px; height: 34px; padding: 2px" />
          <button class="primary" @click="submitProfile">Save Profile</button>
          <span v-if="profileSaved" style="color: var(--success); font-size: 0.85rem">Saved!</span>
        </div>
      </div>

      <!-- Add New Recurring Rule -->
      <div class="panel-section">
        <h3 style="margin: 0 0 8px; font-size: 0.95rem">Add Recurring Schedule Rule</h3>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
          <select v-model="newRule.mealie_user_id">
            <option v-for="u in household" :key="u.mealie_user_id" :value="u.mealie_user_id">
              {{ u.display_name }}
            </option>
          </select>
          <select v-model.number="newRule.weekday">
            <option v-for="(name, idx) in weekdays" :key="idx" :value="idx">{{ name }}</option>
          </select>
          <select v-model="newRule.meal_type">
            <option value="dinner">Dinner</option>
            <option value="lunch">Lunch</option>
            <option value="breakfast">Breakfast</option>
          </select>
          <select v-model="newRule.status">
            <option value="out">Out</option>
            <option value="away">Away</option>
            <option value="home">Home</option>
          </select>
          <input v-model="newRule.label" placeholder="Label (e.g. Dance class)" style="min-width: 170px" />
          <input v-model="newRule.start_date" type="date" title="Start date" />
          <input v-model="newRule.end_date" type="date" title="Optional end date" />
          <button class="primary" @click="submitRule">Add Rule</button>
        </div>
      </div>

      <!-- Existing Rules List -->
      <div>
        <h3 style="margin: 0 0 8px; font-size: 0.95rem">Active Rules</h3>
        <div v-if="!rules.length" style="color: var(--muted); font-size: 0.875rem">No recurring rules yet.</div>
        <div
          v-for="rule in rules"
          :key="rule.id"
          style="border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin-bottom: 8px"
        >
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap">
            <div>
              <strong>{{ userName(rule.mealie_user_id) }}</strong> &bull;
              Every {{ weekdays[rule.weekday] }} ({{ rule.meal_type }}) &rarr;
              <strong>{{ rule.status }}</strong> — <em>{{ rule.label }}</em>
            </div>
            <button class="danger" @click="emit('delete-rule', rule.id)">Delete</button>
          </div>

          <div style="display: flex; gap: 6px; align-items: center; margin-top: 8px; flex-wrap: wrap">
            <input v-model="exceptionDates[rule.id]" type="date" />
            <button @click="exceptionDates[rule.id] && emit('add-exception', rule.id, exceptionDates[rule.id])">
              Skip 1 Date
            </button>
            <span v-if="rule.exceptions?.length" style="font-size: 0.78rem; color: var(--muted)">
              Skipped: {{ rule.exceptions.join(', ') }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
