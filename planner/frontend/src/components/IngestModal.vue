<script setup>
import { ref } from 'vue'
import { apiFetch } from '../api'

const emit = defineEmits(['close', 'imported'])

const urlInput = ref('')
const loadingPreview = ref(false)
const savingCommit = ref(false)
const errorMsg = ref('')
const sourceUrl = ref('')
const draft = ref(null)

async function fetchPreview() {
  if (!urlInput.value.trim()) return
  loadingPreview.value = true
  errorMsg.value = ''
  draft.value = null
  try {
    const res = await apiFetch('/api/ingest/preview', {
      method: 'POST',
      body: JSON.stringify({ url: urlInput.value.trim() }),
    })
    sourceUrl.value = res.source_url
    draft.value = res.recipe
  } catch (err) {
    errorMsg.value = err.message || 'Failed to parse recipe URL'
  } finally {
    loadingPreview.value = false
  }
}

function removeIngredient(idx) {
  draft.value.ingredients.splice(idx, 1)
}

function addIngredient() {
  draft.value.ingredients.push({
    original_text: '',
    quantity: null,
    unit: '',
    food: '',
    note: '',
  })
}

async function commitRecipe() {
  if (!draft.value) return
  savingCommit.value = true
  errorMsg.value = ''
  try {
    const cleanedIngredients = draft.value.ingredients
      .filter((i) => i.food && i.food.trim())
      .map((i) => ({
        original_text: i.original_text || `${i.quantity ?? ''} ${i.unit ?? ''} ${i.food}`.trim(),
        quantity: i.quantity === '' || i.quantity === null ? null : Number(i.quantity),
        unit: i.unit?.trim() || null,
        food: i.food.trim(),
        note: i.note?.trim() || null,
      }))

    const res = await apiFetch('/api/ingest/commit', {
      method: 'POST',
      body: JSON.stringify({
        source_url: sourceUrl.value,
        recipe: {
          ...draft.value,
          ingredients: cleanedIngredients,
        },
      }),
    })
    emit('imported', res.recipe)
    emit('close')
  } catch (err) {
    errorMsg.value = err.message || 'Failed to save recipe to Mealie'
  } finally {
    savingCommit.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="modal-box" style="max-width: 820px">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
        <h2 style="margin: 0; font-size: 1.15rem">✨ AI Recipe Importer (Gemini Flash)</h2>
        <button type="button" @click="emit('close')">Close</button>
      </div>

      <p style="margin: 0 0 12px; font-size: 0.85rem; color: var(--muted)">
        Paste a recipe blog URL below. Gemini Flash extracts ingredients and normalizes canonical foods (stripping prep notes like "fresh" or "minced") before saving to Mealie.
      </p>

      <div style="display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap">
        <input
          v-model="urlInput"
          type="url"
          placeholder="https://www.budgetbytes.com/..."
          style="flex: 1; min-width: 260px"
          @keyup.enter="fetchPreview"
        />
        <button class="primary" :disabled="loadingPreview || !urlInput.trim()" @click="fetchPreview">
          {{ loadingPreview ? 'Extracting...' : 'Parse URL' }}
        </button>
      </div>

      <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

      <div v-if="draft" style="border-top: 1px solid var(--border); padding-top: 14px">
        <div style="display: grid; grid-template-columns: 1fr 120px 120px; gap: 8px; margin-bottom: 12px">
          <div class="field" style="margin: 0">
            <label>Recipe Title</label>
            <input v-model="draft.name" type="text" />
          </div>
          <div class="field" style="margin: 0">
            <label>Prep (min)</label>
            <input v-model.number="draft.prep_time_minutes" type="number" min="0" />
          </div>
          <div class="field" style="margin: 0">
            <label>Cook (min)</label>
            <input v-model.number="draft.cook_time_minutes" type="number" min="0" />
          </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px">
          <strong style="font-size: 0.9rem">Normalized Ingredients ({{ draft.ingredients.length }})</strong>
          <button type="button" style="padding: 3px 8px; font-size: 0.78rem" @click="addIngredient">+ Add Row</button>
        </div>

        <div style="max-height: 290px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; padding: 8px; margin-bottom: 14px">
          <div
            v-for="(ing, idx) in draft.ingredients"
            :key="idx"
            style="display: grid; grid-template-columns: 68px 105px 1fr 1fr 32px; gap: 6px; align-items: center; margin-bottom: 6px"
          >
            <input v-model="ing.quantity" type="number" step="any" placeholder="Qty" title="Quantity" />
            <input v-model="ing.unit" type="text" placeholder="Unit" title="Unit (e.g. cup, tbsp)" />
            <input v-model="ing.food" type="text" placeholder="Canonical food" title="Canonical Food" />
            <input v-model="ing.note" type="text" placeholder="Prep note" title="Prep Note (e.g. chopped)" />
            <button type="button" class="danger" style="padding: 4px 6px" title="Remove" @click="removeIngredient(idx)">✕</button>
          </div>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <button type="button" @click="emit('close')">Cancel</button>
          <button class="primary" :disabled="savingCommit || !draft.name.trim()" @click="commitRecipe">
            {{ savingCommit ? 'Importing to Mealie...' : '✓ Import to Mealie' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
