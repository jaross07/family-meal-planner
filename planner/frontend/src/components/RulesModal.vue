<script setup>
import { reactive, ref } from 'vue'

const props = defineProps({
  rules: Array,
  household: Array,
  currentUser: Object,
})

const emit = defineEmits([
  'close',
  'create-rule',
  'delete-rule',
  'add-exception',
  'update-member',
])

const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const activeMembers = () => (props.household || []).filter((m) => m.active !== false)

const newRule = reactive({
  mealie_user_id: activeMembers()[0]?.mealie_user_id || '',
  weekday: 2,
  meal_type: 'dinner',
  status: 'out',
  start_date: new Date().toISOString().slice(0, 10),
  end_date: '',
  label: '',
})

const exceptionDates = reactive({})
const savedMemberId = ref('')

function submitRule() {
  if (!newRule.label.trim()) return
  emit('create-rule', {
    ...newRule,
    end_date: newRule.end_date || null,
  })
  newRule.label = ''
}

function saveMember(member) {
  emit('update-member', member.mealie_user_id, {
    display_name: member.display_name,
    initials: member.initials,
    color_code: member.color_code,
    active: member.active,
  })
  savedMemberId.value = member.mealie_user_id
  setTimeout(() => {
    if (savedMemberId.value === member.mealie_user_id) savedMemberId.value = ''
  }, 1800)
}

function toggleMemberActive(member, checked) {
  member.active = checked
  saveMember(member)
}

function userName(uid) {
  return props.household.find((u) => u.mealie_user_id === uid)?.display_name || uid
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="modal-box">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px">
        <h2 style="margin: 0; font-size: 1.2rem">Configure Household &amp; Rules</h2>
        <button @click="emit('close')">Close</button>
      </div>

      <!-- Household Visibility & Badge Configuration -->
      <div class="panel-section">
        <h3 style="margin: 0 0 4px; font-size: 0.95rem">Household Members on Calendar</h3>
        <p style="margin: 0 0 10px; font-size: 0.8rem; color: var(--muted)">
          Check who appears on the monthly calendar and counts toward meal recommendations.
        </p>

        <div
          v-for="member in household"
          :key="member.mealie_user_id"
          style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px"
        >
          <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; min-width: 90px; font-size: 0.85rem; font-weight: 600">
            <input
              type="checkbox"
              :checked="member.active !== false"
              @change="toggleMemberActive(member, $event.target.checked)"
            />
            Show
          </label>
          <input v-model="member.display_name" placeholder="Name" style="width: 135px" />
          <input v-model="member.initials" placeholder="Initials" maxlength="4" style="width: 68px" />
          <input v-model="member.color_code" type="color" style="width: 44px; height: 34px; padding: 2px" />
          <button @click="saveMember(member)">Save</button>
          <span v-if="savedMemberId === member.mealie_user_id" style="color: var(--success); font-size: 0.8rem">
            Saved!
          </span>
        </div>
      </div>

      <!-- Add New Recurring Rule -->
      <div class="panel-section">
        <h3 style="margin: 0 0 8px; font-size: 0.95rem">Add Recurring Schedule Rule</h3>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
          <select v-model="newRule.mealie_user_id">
            <option v-for="u in activeMembers()" :key="u.mealie_user_id" :value="u.mealie_user_id">
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
