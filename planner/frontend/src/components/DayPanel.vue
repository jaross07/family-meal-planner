<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  selectedDate: String,
  mealType: String,
  recommendations: Object,
  plannedMeals: Array,
  dayAttendance: Array,
  myRatings: Object,
  familyNotes: Object,
  context: Object,
  dayNote: String,
  mealiePublicUrl: String,
  loading: Boolean,
  planningRecipeId: String,
  searchQuery: { type: String, default: '' },
  categories: { type: Array, default: () => [] },
  selectedCategory: { type: String, default: '' },
})

const emit = defineEmits([
  'update-context',
  'save-day-note',
  'rate-recipe',
  'hide-recipe',
  'plan-recipe',
  'search-recipes',
  'select-category',
  'remove-planned',
  'replace-planned',
  'show-vetoed',
  'open-day-modal',
  'toggle-recipe-leftover',
])

const replacingEntry = ref(null)
const noteDraft = ref(props.dayNote || '')
const savingNote = ref(false)

watch(
  () => [props.selectedDate, props.dayNote],
  () => {
    noteDraft.value = props.dayNote || ''
  }
)

function commitNote() {
  const trimmed = noteDraft.value.trim()
  if (trimmed === (props.dayNote || '').trim()) return
  savingNote.value = true
  emit('save-day-note', props.selectedDate, trimmed)
  setTimeout(() => {
    savingNote.value = false
  }, 400)
}
const brokenImages = ref({})

const formattedDate = computed(() => {
  if (!props.selectedDate) return ''
  const [y, m, d] = props.selectedDate.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  })
})

const scheduleNotes = computed(() =>
  (props.dayAttendance || []).filter((entry) => entry.label || entry.status !== 'home')
)

function toggleFastEasy() {
  const nextPrep = props.context?.max_prep_time ? null : 25
  emit('update-context', {
    date: props.selectedDate,
    meal_type: props.mealType,
    require_leftovers: Boolean(props.context?.require_leftovers),
    max_prep_time: nextPrep,
    is_planned: props.context?.is_planned ?? (props.mealType === 'dinner'),
    eating_leftovers: Boolean(props.context?.eating_leftovers),
    henleys_choice: Boolean(props.context?.henleys_choice),
  })
}

function toggleMakeExtra() {
  emit('update-context', {
    date: props.selectedDate,
    meal_type: props.mealType,
    require_leftovers: !props.context?.require_leftovers,
    max_prep_time: props.context?.max_prep_time ?? null,
    is_planned: props.context?.is_planned ?? (props.mealType === 'dinner'),
    eating_leftovers: Boolean(props.context?.eating_leftovers),
    henleys_choice: Boolean(props.context?.henleys_choice),
  })
}

function toggleEatingLeftovers() {
  emit('update-context', {
    date: props.selectedDate,
    meal_type: props.mealType,
    require_leftovers: Boolean(props.context?.require_leftovers),
    max_prep_time: props.context?.max_prep_time ?? null,
    is_planned: props.context?.is_planned ?? (props.mealType === 'dinner'),
    eating_leftovers: !props.context?.eating_leftovers,
    henleys_choice: Boolean(props.context?.henleys_choice),
  })
}

function toggleHenleysChoice() {
  emit('update-context', {
    date: props.selectedDate,
    meal_type: props.mealType,
    require_leftovers: Boolean(props.context?.require_leftovers),
    max_prep_time: props.context?.max_prep_time ?? null,
    is_planned: props.context?.is_planned ?? (props.mealType === 'dinner'),
    eating_leftovers: Boolean(props.context?.eating_leftovers),
    henleys_choice: !props.context?.henleys_choice,
  })
}

function mealieRecipeUrl(slug) {
  const base = (props.mealiePublicUrl || '').replace(/\/$/, '')
  return slug ? `${base}/g/home/r/${slug}` : base
}

function recipeImageUrl(recipeId) {
  return `/api/recipes/${recipeId}/image`
}

const shuffleSeed = ref(0)

function shuffleRecipes() {
  shuffleSeed.value += 1
}

function hashSeed(str) {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const displayedItems = computed(() => {
  const list = [...(props.recommendations?.items || [])]
  if (list.length <= 1) return list
  // Keep active leftover-chain boosts pinned at the top, shuffle the rest
  const boosted = list.filter((i) => Boolean(i.leftover_badge))
  const regular = list.filter((i) => !i.leftover_badge)
  let seed = hashSeed(`${props.selectedDate || ''}:${props.mealType || ''}:${shuffleSeed.value}`)
  for (let i = regular.length - 1; i > 0; i--) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    const j = seed % (i + 1)
    ;[regular[i], regular[j]] = [regular[j], regular[i]]
  }
  return [...boosted, ...regular]
})

const showCustomInput = ref(false)
const customMealTitle = ref('')
const localSearch = ref(props.searchQuery || '')
let searchDebounceTimer = null

watch(
  () => props.searchQuery,
  (val) => {
    if ((val || '') !== localSearch.value) {
      localSearch.value = val || ''
    }
  }
)

watch(
  () => [props.selectedDate, props.mealType],
  () => {
    showCustomInput.value = false
    customMealTitle.value = ''
  }
)

function onSearchInput() {
  clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    emit('search-recipes', localSearch.value)
  }, 220)
}

function clearSearch() {
  clearTimeout(searchDebounceTimer)
  localSearch.value = ''
  emit('search-recipes', '')
}

function submitCustomMeal(presetTitle = null) {
  const title = (presetTitle !== null ? presetTitle : customMealTitle.value).trim()
  if (!title) return
  chooseRecipe({ mealie_recipe_id: null, name: title })
  customMealTitle.value = ''
  showCustomInput.value = false
}

function chooseRecipe(item) {
  if (replacingEntry.value) {
    emit('replace-planned', replacingEntry.value, item)
    replacingEntry.value = null
  } else {
    emit('plan-recipe', item)
  }
}
</script>

<template>
  <div class="card">
    <div class="panel-section">
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px">
        <h2 style="margin: 0 0 4px; font-size: 1.1rem">{{ formattedDate }}</h2>
        <button @click="emit('open-day-modal', selectedDate)">Edit Day Meals</button>
      </div>
      <div style="font-size: 0.85rem; color: var(--muted); text-transform: capitalize">
        {{ mealType }} &bull;
        <span v-if="recommendations?.diners?.length">
          Diners: {{ recommendations.diners.map((d) => d.display_name).join(', ') }}
        </span>
        <span v-else>No diners home</span>
      </div>

      <div v-if="scheduleNotes.length" style="margin-top: 8px; display: flex; flex-direction: column; gap: 4px">
        <div
          v-for="note in scheduleNotes"
          :key="note.mealie_user_id"
          style="font-size: 0.8rem; color: var(--muted); background: #f8fafc; border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px"
        >
          <strong>{{ note.display_name }}</strong>: {{ note.status }}
          <span v-if="note.label"> — {{ note.label }}</span>
        </div>
      </div>

      <div style="margin-top: 10px">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px">
          <label style="font-size: 0.78rem; font-weight: 600; color: var(--muted)">📝 Day Notes</label>
          <span v-if="savingNote" style="font-size: 0.72rem; color: var(--success)">Saved</span>
        </div>
        <textarea
          v-model="noteDraft"
          rows="2"
          placeholder="Add notes for this day..."
          style="width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 0.84rem; font-family: inherit; resize: vertical"
          @blur="commitNote"
          @keydown.ctrl.enter="commitNote"
          @keydown.meta.enter="commitNote"
        ></textarea>
      </div>

      <hr style="border: 0; border-top: 1px solid var(--border); margin: 12px 0 10px" />

      <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; flex-wrap: wrap">
        <div style="display: flex; align-items: center; gap: 8px; flex: 1; min-width: 180px">
          <span style="font-size: 0.92rem; font-weight: 700">Recipes:</span>
          <select
            :value="selectedCategory"
            aria-label="Filter by Mealie category"
            style="flex: 1; min-width: 120px; font-size: 0.82rem; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--border)"
            @change="emit('select-category', $event.target.value)"
          >
            <option value="">All Categories</option>
            <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
          </select>
        </div>
        <button
          type="button"
          title="Shuffle recipe order"
          style="padding: 4px 9px; font-size: 0.8rem"
          @click="shuffleRecipes"
        >
          🔀 Shuffle
        </button>
      </div>

      <div class="toggle-row">
        <button
          class="toggle-chip"
          :class="{ active: Boolean(context?.max_prep_time) }"
          @click="toggleFastEasy"
        >
          ⚡ Fast &amp; Easy (&le;25m)
        </button>
        <button
          class="toggle-chip"
          :class="{ active: Boolean(context?.require_leftovers) }"
          @click="toggleMakeExtra"
        >
          🍱 Make Extra
        </button>
        <button
          class="toggle-chip"
          :class="{ active: Boolean(context?.eating_leftovers) }"
          @click="toggleEatingLeftovers"
        >
          ♻ Eating Leftovers
        </button>
        <button
          class="toggle-chip"
          :class="{ active: Boolean(context?.henleys_choice) }"
          @click="toggleHenleysChoice"
        >
          👑 Henley's Choice
        </button>
        <button
          type="button"
          class="toggle-chip"
          :class="{ active: showCustomInput }"
          @click="showCustomInput = !showCustomInput"
        >
          ✏️ Pencil In Meal
        </button>
      </div>

      <!-- Inline Pencil-In Custom Meal Box -->
      <div
        v-if="showCustomInput"
        style="margin-top: 8px; padding: 8px; border: 1px solid #cbd5e1; border-radius: 8px; background: #f8fafc"
      >
        <div style="display: flex; gap: 6px; margin-bottom: 6px">
          <input
            v-model="customMealTitle"
            type="text"
            placeholder="e.g., Eating leftovers, Grilling burgers..."
            style="flex: 1; font-size: 0.85rem"
            @keyup.enter="submitCustomMeal()"
          />
          <button
            type="button"
            class="primary"
            style="padding: 5px 10px; font-size: 0.82rem"
            :disabled="!customMealTitle.trim() || planningRecipeId === '__custom__'"
            @click="submitCustomMeal()"
          >
            Add
          </button>
        </div>
        <div style="display: flex; gap: 6px; flex-wrap: wrap">
          <button
            type="button"
            style="padding: 2px 8px; font-size: 0.75rem"
            @click="submitCustomMeal('Eating Leftovers')"
          >
            ♻ Eating Leftovers
          </button>
          <button
            type="button"
            style="padding: 2px 8px; font-size: 0.75rem"
            @click="submitCustomMeal(&quot;Henley's Choice&quot;)"
          >
            👑 Henley's Choice
          </button>
          <button
            type="button"
            style="padding: 2px 8px; font-size: 0.75rem"
            @click="submitCustomMeal('Takeout / Eating Out')"
          >
            🍕 Takeout / Eating Out
          </button>
        </div>
      </div>

      <!-- Filter-Aware Recipe Search Bar -->
      <div style="margin-top: 10px; position: relative; display: flex; align-items: center">
        <input
          v-model="localSearch"
          type="text"
          placeholder="🔍 Search recipes (honors active filters)..."
          style="width: 100%; padding-right: 28px; font-size: 0.85rem"
          @input="onSearchInput"
        />
        <button
          v-if="localSearch"
          type="button"
          title="Clear search"
          style="position: absolute; right: 4px; border: none; background: transparent; padding: 2px 6px; font-size: 0.9rem; color: var(--muted)"
          @click="clearSearch"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- Currently Planned in Mealie Section -->
    <div v-if="plannedMeals?.length" class="panel-section">
      <div style="font-size: 0.78rem; font-weight: 700; text-transform: uppercase; color: #166534; margin-bottom: 6px">
        ✓ Planned in Mealie
      </div>

      <div
        v-for="entry in plannedMeals"
        :key="entry.id || entry.mealie_recipe_id"
        style="border: 1px solid #86efac; background: #f0fdf4; border-radius: 8px; padding: 8px; margin-bottom: 6px; display: flex; gap: 10px; align-items: center"
      >
        <img
          v-if="entry.mealie_recipe_id && !brokenImages[entry.mealie_recipe_id]"
          :src="recipeImageUrl(entry.mealie_recipe_id)"
          alt=""
          style="width: 52px; height: 52px; object-fit: cover; border-radius: 6px; flex-shrink: 0"
          @error="brokenImages[entry.mealie_recipe_id] = true"
        />
        <div style="flex: 1; min-width: 0">
          <div style="font-weight: 600; font-size: 0.9rem; color: #14532d">{{ entry.name }}</div>
          <div style="display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap">
            <a v-if="entry.slug" :href="mealieRecipeUrl(entry.slug)" target="_blank" rel="noopener">
              <button type="button" style="padding: 3px 8px; font-size: 0.78rem">Open</button>
            </a>
            <button
              type="button"
              style="padding: 3px 8px; font-size: 0.78rem"
              @click="replacingEntry = replacingEntry?.id === entry.id ? null : entry"
            >
              {{ replacingEntry?.id === entry.id ? 'Cancel Replace' : 'Replace' }}
            </button>
            <button
              type="button"
              class="danger"
              style="padding: 3px 8px; font-size: 0.78rem"
              @click="emit('remove-planned', entry)"
            >
              Remove
            </button>
          </div>
        </div>
      </div>

      <div
        v-if="replacingEntry"
        style="font-size: 0.8rem; color: #1e40af; background: #dbeafe; padding: 6px 8px; border-radius: 6px; margin-top: 6px"
      >
        Pick a recipe below to replace <strong>{{ replacingEntry.name }}</strong>.
      </div>
    </div>

    <div v-if="loading" style="color: var(--muted); padding: 12px 0">Loading recommendations...</div>

    <div
      v-else-if="context?.eating_leftovers"
      style="background: #f0fdf4; border: 1px solid #86efac; color: #166534; border-radius: 8px; padding: 12px; margin-bottom: 10px"
    >
      <strong>♻ Eating Leftovers</strong> — No new recipe required for this meal. Toggle off <em>Eating Leftovers</em> above if you want fresh recipe suggestions.
    </div>

    <div
      v-else-if="context?.henleys_choice"
      style="background: #fefce8; border: 1px solid #fde047; color: #854d0e; border-radius: 8px; padding: 12px; margin-bottom: 10px"
    >
      <strong>👑 Henley's Choice</strong> — Henley picks this meal; no recipe planning required. Toggle off <em>Henley's Choice</em> above if you want recipe suggestions.
    </div>

    <div v-else-if="context && context.is_planned === false" style="color: var(--muted); padding: 12px 0">
      This meal is marked as not planned. Double-click the day or click <strong>Edit Day Meals</strong> to enable it.
    </div>

    <div v-else-if="recommendations?.reason === 'no_diners'" style="color: var(--muted); padding: 12px 0">
      Everyone is marked out or away for this meal.
    </div>

    <div v-else-if="recommendations?.reason === 'all_vetoed'" style="padding: 12px 0">
      <p style="margin: 0 0 10px; color: var(--muted)">
        Every matching recipe was disliked by at least one diner eating this meal.
      </p>
      <button @click="emit('show-vetoed')">Show least-disliked</button>
    </div>

    <div v-else-if="!recommendations?.items?.length" style="color: var(--muted); padding: 12px 0">
      No matching recipes found. Try syncing recipes from Mealie or adjusting day toggles.
    </div>

    <div v-else>
      <div v-for="item in displayedItems" :key="item.mealie_recipe_id" class="recipe-item">
        <div style="display: flex; gap: 10px; align-items: flex-start; margin-bottom: 8px">
          <img
            v-if="!brokenImages[item.mealie_recipe_id]"
            :src="recipeImageUrl(item.mealie_recipe_id)"
            alt=""
            style="width: 60px; height: 60px; object-fit: cover; border-radius: 8px; flex-shrink: 0; border: 1px solid var(--border)"
            @error="brokenImages[item.mealie_recipe_id] = true"
          />
          <div style="flex: 1; min-width: 0">
            <div class="recipe-title">{{ item.name }}</div>
            <div class="recipe-meta">
              <span>Score: {{ item.score }}</span>
              <span v-if="item.prep_time_minutes">⏱ {{ item.prep_time_minutes }}m</span>
              <button
                type="button"
                style="padding: 1px 7px; font-size: 0.72rem; border-radius: 999px"
                :style="item.leftover_yield ? { background: '#dcfce7', borderColor: '#16a34a', color: '#166534', fontWeight: '600' } : {}"
                title="Toggle whether this recipe makes leftovers for Make Extra days"
                @click="emit('toggle-recipe-leftover', item)"
              >
                🍱 {{ item.leftover_yield ? 'Makes Extra ✓' : 'Mark Makes Extra' }}
              </button>
              <span v-if="item.last_planned_date">Last: {{ item.last_planned_date }}</span>
            </div>
            <div v-if="item.leftover_badge" class="leftover-pill" style="margin-bottom: 4px">
              ♻ {{ item.leftover_badge }}
            </div>
            <div
              v-for="fn in familyNotes?.[item.mealie_recipe_id] || []"
              :key="fn.user_id"
              style="font-size: 0.76rem; color: #475569; background: #f8fafc; border-left: 3px solid #94a3b8; padding: 2px 6px; margin-top: 3px; border-radius: 0 4px 4px 0"
            >
              <strong>{{ fn.display_name }}:</strong> "{{ fn.note }}"
            </div>
          </div>
        </div>

        <div class="recipe-actions">
          <div class="rate-btns">
            <button
              :class="{ 'active-dislike': (myRatings[item.mealie_recipe_id] ?? 0) === -1 }"
              title="Dislike (Hard Veto)"
              @click="emit('rate-recipe', item.mealie_recipe_id, -1)"
            >
              👎
            </button>
            <button
              :class="{ 'active-neutral': (myRatings[item.mealie_recipe_id] ?? 0) === 0 }"
              title="Neutral"
              @click="emit('rate-recipe', item.mealie_recipe_id, 0)"
            >
              😐
            </button>
            <button
              :class="{ 'active-like': (myRatings[item.mealie_recipe_id] ?? 0) === 1 }"
              title="Like"
              @click="emit('rate-recipe', item.mealie_recipe_id, 1)"
            >
              👍
            </button>
          </div>

          <div style="display: flex; gap: 6px">
            <button
              type="button"
              title="Hide recipe from planner suggestions"
              @click="emit('hide-recipe', item)"
            >
              🚫 Hide
            </button>
            <a :href="mealieRecipeUrl(item.slug)" target="_blank" rel="noopener">
              <button type="button">Open in Mealie</button>
            </a>
            <button
              class="primary"
              :disabled="planningRecipeId === item.mealie_recipe_id"
              @click="chooseRecipe(item)"
            >
              {{
                planningRecipeId === item.mealie_recipe_id
                  ? 'Saving...'
                  : replacingEntry
                  ? 'Use as Replacement'
                  : 'Plan it'
              }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
