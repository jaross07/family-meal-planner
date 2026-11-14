<script setup>
import { computed } from 'vue'

const props = defineProps({
  selectedDate: String,
  mealType: String,
  recommendations: Object,
  myRatings: Object,
  context: Object,
  mealiePublicUrl: String,
  loading: Boolean,
  planningRecipeId: String,
})

const emit = defineEmits([
  'update-context',
  'rate-recipe',
  'plan-recipe',
  'show-vetoed',
])

const formattedDate = computed(() => {
  if (!props.selectedDate) return ''
  const [y, m, d] = props.selectedDate.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  })
})

function toggleFastEasy() {
  const nextPrep = props.context?.max_prep_time ? null : 25
  emit('update-context', {
    date: props.selectedDate,
    meal_type: props.mealType,
    require_leftovers: Boolean(props.context?.require_leftovers),
    max_prep_time: nextPrep,
  })
}

function toggleMakeExtra() {
  emit('update-context', {
    date: props.selectedDate,
    meal_type: props.mealType,
    require_leftovers: !props.context?.require_leftovers,
    max_prep_time: props.context?.max_prep_time ?? null,
  })
}

function mealieRecipeUrl(slug) {
  const base = (props.mealiePublicUrl || '').replace(/\/$/, '')
  return slug ? `${base}/g/home/r/${slug}` : base
}
</script>

<template>
  <div class="card">
    <div class="panel-section">
      <h2 style="margin: 0 0 4px; font-size: 1.1rem">{{ formattedDate }}</h2>
      <div style="font-size: 0.85rem; color: var(--muted); text-transform: capitalize">
        {{ mealType }} &bull;
        <span v-if="recommendations?.diners?.length">
          Diners: {{ recommendations.diners.map((d) => d.display_name).join(', ') }}
        </span>
        <span v-else>No diners home</span>
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
      </div>
    </div>

    <div v-if="loading" style="color: var(--muted); padding: 12px 0">Loading recommendations...</div>

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
      <div v-for="item in recommendations.items" :key="item.mealie_recipe_id" class="recipe-item">
        <div class="recipe-title">{{ item.name }}</div>
        <div class="recipe-meta">
          <span>Score: {{ item.score }}</span>
          <span v-if="item.prep_time_minutes">⏱ {{ item.prep_time_minutes }}m</span>
          <span v-if="item.leftover_yield">🍱 High-yield</span>
          <span v-if="item.last_planned_date">Last: {{ item.last_planned_date }}</span>
        </div>

        <div v-if="item.leftover_badge" class="leftover-pill">
          ♻ {{ item.leftover_badge }}
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
            <a :href="mealieRecipeUrl(item.slug)" target="_blank" rel="noopener">
              <button type="button">Open in Mealie</button>
            </a>
            <button
              class="primary"
              :disabled="planningRecipeId === item.mealie_recipe_id"
              @click="emit('plan-recipe', item)"
            >
              {{ planningRecipeId === item.mealie_recipe_id ? 'Planning...' : 'Plan it' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
