<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  apiFetch: { type: Function, required: true },
  notify: { type: Function, required: true },
})

const emit = defineEmits(['updated-count'])

const stores = ref(['WinCo', "Trader Joe's", 'Costco', 'Other'])
const categories = ref([
  'Produce',
  'Meat & Seafood',
  'Dairy & Eggs',
  'Bakery',
  'Frozen',
  'Pantry',
  'Other',
])

const items = ref([])
const loading = ref(false)
const activeStoreFilter = ref('ALL')
const groupMode = ref('category')
const showChecked = ref(true)

const newItem = reactive({
  name: '',
  quantity: '',
  unit: '',
  store: 'WinCo',
  category: 'Pantry',
})
const userOverrodeStore = ref(false)
const userOverrodeCategory = ref(false)
let lookupTimer = null

const showImporter = ref(false)
const importFrom = ref('')
const importTo = ref('')
const previewMeals = ref([])
const selectedMealKeys = ref(new Set())
const loadingPreview = ref(false)
const importing = ref(false)

function toIso(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function initDefaultDates() {
  const now = new Date()
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 6)
  importFrom.value = toIso(now)
  importTo.value = toIso(end)
}

async function loadShoppingList() {
  loading.value = true
  try {
    const res = await props.apiFetch('/api/shopping')
    if (res.stores?.length) stores.value = res.stores
    if (res.categories?.length) categories.value = res.categories
    items.value = res.items || []
    emitUncheckedCount()
  } finally {
    loading.value = false
  }
}

function emitUncheckedCount() {
  const remaining = items.value.filter((i) => !i.checked).length
  emit('updated-count', remaining)
}

watch(
  () => newItem.name,
  (val) => {
    clearTimeout(lookupTimer)
    const trimmed = val.trim()
    if (!trimmed) {
      userOverrodeStore.value = false
      userOverrodeCategory.value = false
      newItem.store = 'WinCo'
      newItem.category = 'Pantry'
      return
    }
    lookupTimer = setTimeout(async () => {
      try {
        const res = await props.apiFetch(`/api/shopping/lookup?name=${encodeURIComponent(trimmed)}`)
        if (!userOverrodeStore.value && res.store) newItem.store = res.store
        if (!userOverrodeCategory.value && res.category) newItem.category = res.category
      } catch {
        // Ignore transient lookup errors
      }
    }, 220)
  }
)

async function handleAddItem() {
  const name = newItem.name.trim()
  if (!name) return
  const qtyNum = parseFloat(newItem.quantity)
  const created = await props.apiFetch('/api/shopping/items', {
    method: 'POST',
    body: JSON.stringify({
      name,
      quantity: Number.isFinite(qtyNum) && qtyNum > 0 ? qtyNum : null,
      unit: newItem.unit.trim() || null,
      store: newItem.store,
      category: newItem.category,
    }),
  })
  items.value.push(created)
  newItem.name = ''
  newItem.quantity = ''
  newItem.unit = ''
  userOverrodeStore.value = false
  userOverrodeCategory.value = false
  newItem.store = 'WinCo'
  newItem.category = 'Pantry'
  emitUncheckedCount()
}

async function toggleChecked(item) {
  const nextVal = !item.checked
  item.checked = nextVal
  emitUncheckedCount()
  try {
    const updated = await props.apiFetch(`/api/shopping/items/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ checked: nextVal }),
    })
    Object.assign(item, updated)
  } catch (err) {
    item.checked = !nextVal
    emitUncheckedCount()
    props.notify(err.message || 'Could not update item')
  }
}

async function updateItemField(item, field, value) {
  const prev = item[field]
  item[field] = value
  try {
    const updated = await props.apiFetch(`/api/shopping/items/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ [field]: value }),
    })
    Object.assign(item, updated)
  } catch (err) {
    item[field] = prev
    props.notify(err.message || 'Could not update item')
  }
}

async function deleteItem(item) {
  items.value = items.value.filter((i) => i.id !== item.id)
  emitUncheckedCount()
  await props.apiFetch(`/api/shopping/items/${item.id}`, { method: 'DELETE' })
}

async function clearCheckedItems() {
  const storeParam =
    activeStoreFilter.value !== 'ALL'
      ? `?store=${encodeURIComponent(activeStoreFilter.value)}`
      : ''
  await props.apiFetch(`/api/shopping/checked${storeParam}`, { method: 'DELETE' })
  items.value = items.value.filter((i) => {
    if (!i.checked) return true
    if (activeStoreFilter.value !== 'ALL' && i.store !== activeStoreFilter.value) return true
    return false
  })
  props.notify('Cleared checked items')
}

async function openImporter() {
  showImporter.value = !showImporter.value
  if (showImporter.value) {
    await loadMealplanPreview()
  }
}

async function loadMealplanPreview() {
  if (!importFrom.value || !importTo.value) return
  loadingPreview.value = true
  try {
    const res = await props.apiFetch(
      `/api/shopping/mealplan-preview?from=${importFrom.value}&to=${importTo.value}`
    )
    previewMeals.value = res.meals || []
    const nextSelected = new Set()
    previewMeals.value.forEach((m, idx) => {
      if (m.default_selected) nextSelected.add(idx)
    })
    selectedMealKeys.value = nextSelected
  } finally {
    loadingPreview.value = false
  }
}

function toggleMealSelection(idx) {
  const next = new Set(selectedMealKeys.value)
  if (next.has(idx)) next.delete(idx)
  else next.add(idx)
  selectedMealKeys.value = next
}

async function handleImportSelected() {
  const selections = previewMeals.value.filter((_, idx) => selectedMealKeys.value.has(idx))
  if (!selections.length) return
  importing.value = true
  try {
    const res = await props.apiFetch('/api/shopping/import-mealplan', {
      method: 'POST',
      body: JSON.stringify({ selections }),
    })
    props.notify(`Added ${res.added} new item(s) and merged ${res.merged} ingredient(s)`)
    showImporter.value = false
    await loadShoppingList()
  } finally {
    importing.value = false
  }
}

const uncheckedCountByStore = computed(() => {
  const counts = { ALL: 0 }
  for (const s of stores.value) counts[s] = 0
  for (const item of items.value) {
    if (item.checked) continue
    counts.ALL += 1
    counts[item.store] = (counts[item.store] || 0) + 1
  }
  return counts
})

const storeFilteredItems = computed(() => {
  if (activeStoreFilter.value === 'ALL') return items.value
  return items.value.filter((i) => i.store === activeStoreFilter.value)
})

const activeItems = computed(() => storeFilteredItems.value.filter((i) => !i.checked))
const checkedItems = computed(() => storeFilteredItems.value.filter((i) => i.checked))

function sortByCategoryOrder(list) {
  const order = new Map(categories.value.map((c, idx) => [c, idx]))
  return [...list].sort((a, b) => {
    const ca = order.get(a.category) ?? 99
    const cb = order.get(b.category) ?? 99
    if (ca !== cb) return ca - cb
    return a.name.localeCompare(b.name)
  })
}

const groupedActiveSections = computed(() => {
  const list = activeItems.value
  if (groupMode.value === 'category') {
    const map = new Map()
    for (const cat of categories.value) map.set(cat, [])
    for (const item of list) {
      if (!map.has(item.category)) map.set(item.category, [])
      map.get(item.category).push(item)
    }
    const out = []
    for (const [cat, rows] of map.entries()) {
      if (rows.length) {
        out.push({
          key: `cat:${cat}`,
          title: cat,
          rows: [...rows].sort((a, b) => a.name.localeCompare(b.name)),
        })
      }
    }
    return out
  }

  if (groupMode.value === 'store') {
    const out = []
    for (const st of stores.value) {
      const rows = list.filter((i) => i.store === st)
      if (rows.length) {
        out.push({
          key: `store:${st}`,
          title: st,
          rows: sortByCategoryOrder(rows),
        })
      }
    }
    return out
  }

  const out = []
  for (const st of stores.value) {
    const storeRows = list.filter((i) => i.store === st)
    if (!storeRows.length) continue
    for (const cat of categories.value) {
      const catRows = storeRows.filter((i) => i.category === cat)
      if (catRows.length) {
        out.push({
          key: `sc:${st}:${cat}`,
          title: `${st} — ${cat}`,
          rows: [...catRows].sort((a, b) => a.name.localeCompare(b.name)),
        })
      }
    }
  }
  return out
})

function formatQuantity(item) {
  const parts = []
  if (item.quantity != null) {
    const rounded = Math.round(item.quantity * 100) / 100
    parts.push(String(rounded))
  }
  if (item.unit) parts.push(item.unit)
  return parts.join(' ')
}

onMounted(() => {
  initDefaultDates()
  loadShoppingList()
})
</script>

<template>
  <main style="max-width: 1040px; margin: 0 auto; padding: 16px">
    <div class="card" style="margin-bottom: 14px">
      <div
        style="
          display: flex;
          flex-wrap: wrap;
          justify-content: space-between;
          align-items: center;
          gap: 10px;
          margin-bottom: 12px;
        "
      >
        <div>
          <h2 style="margin: 0; font-size: 1.2rem">🛒 Shopping List</h2>
          <div style="font-size: 0.82rem; color: var(--muted)">
            Pull ingredients from planned meals or add household items by store &amp; aisle.
          </div>
        </div>

        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <button type="button" class="primary" @click="openImporter">
            {{ showImporter ? 'Close Meal Importer' : '📅 Import from Meal Plan' }}
          </button>
          <button
            v-if="checkedItems.length"
            type="button"
            class="danger"
            @click="clearCheckedItems"
          >
            Clear Checked ({{ checkedItems.length }})
          </button>
        </div>
      </div>

      <div
        v-if="showImporter"
        style="
          background: #f8fafc;
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 12px;
          margin-bottom: 14px;
        "
      >
        <div
          style="
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 8px;
            margin-bottom: 10px;
          "
        >
          <strong style="font-size: 0.9rem">Select Planned Meals:</strong>
          <input v-model="importFrom" type="date" aria-label="From date" />
          <span style="color: var(--muted)">to</span>
          <input v-model="importTo" type="date" aria-label="To date" />
          <button type="button" :disabled="loadingPreview" @click="loadMealplanPreview">
            {{ loadingPreview ? 'Loading...' : 'Refresh Dates' }}
          </button>
        </div>

        <div v-if="loadingPreview" style="color: var(--muted); font-size: 0.88rem; padding: 8px 0">
          Checking planned meals in Mealie...
        </div>
        <div
          v-else-if="!previewMeals.length"
          style="color: var(--muted); font-size: 0.88rem; padding: 8px 0"
        >
          No planned meals found in this date range.
        </div>
        <div v-else style="display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px">
          <label
            v-for="(m, idx) in previewMeals"
            :key="`${m.date}-${m.meal_type}-${idx}`"
            style="
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 8px;
              background: #fff;
              border: 1px solid var(--border);
              border-radius: 6px;
              padding: 7px 10px;
              cursor: pointer;
              font-size: 0.88rem;
            "
          >
            <span style="display: flex; align-items: center; gap: 8px">
              <input
                type="checkbox"
                :checked="selectedMealKeys.has(idx)"
                :disabled="!m.has_recipe"
                @change="toggleMealSelection(idx)"
              />
              <span>
                <strong>{{ m.date }}</strong> ({{ m.meal_type }}): {{ m.recipe_name }}
              </span>
            </span>
            <span
              v-if="m.skip_reason === 'eating_leftovers'"
              style="font-size: 0.75rem; color: #166534; background: #dcfce7; padding: 2px 7px; border-radius: 999px"
            >
              ♻ Eating Leftovers (skipped)
            </span>
            <span
              v-else-if="m.skip_reason === 'henleys_choice'"
              style="font-size: 0.75rem; color: #854d0e; background: #fef9c3; padding: 2px 7px; border-radius: 999px"
            >
              👑 Henley's Choice (skipped)
            </span>
            <span
              v-else-if="!m.has_recipe"
              style="font-size: 0.75rem; color: var(--muted)"
            >
              Penciled-in note (no recipe ingredients)
            </span>
          </label>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <button type="button" @click="showImporter = false">Cancel</button>
          <button
            type="button"
            class="primary"
            :disabled="importing || selectedMealKeys.size === 0"
            @click="handleImportSelected"
          >
            {{
              importing
                ? 'Importing...'
                : `Add Ingredients from ${selectedMealKeys.size} Meal(s)`
            }}
          </button>
        </div>
      </div>

      <form
        style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center"
        @submit.prevent="handleAddItem"
      >
        <input
          v-model="newItem.name"
          type="text"
          placeholder="Add item (e.g. Bananas, Paper towels, Coffee)..."
          style="flex: 2 1 220px"
        />
        <input
          v-model="newItem.quantity"
          type="number"
          step="any"
          min="0"
          placeholder="Qty"
          style="width: 72px"
        />
        <input
          v-model="newItem.unit"
          type="text"
          placeholder="Unit"
          style="width: 84px"
        />
        <select
          v-model="newItem.store"
          aria-label="Store"
          @change="userOverrodeStore = true"
        >
          <option v-for="st in stores" :key="st" :value="st">{{ st }}</option>
        </select>
        <select
          v-model="newItem.category"
          aria-label="Category"
          @change="userOverrodeCategory = true"
        >
          <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
        </select>
        <button type="submit" class="primary" :disabled="!newItem.name.trim()">+ Add</button>
      </form>
    </div>

    <div
      class="card"
      style="
        margin-bottom: 14px;
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
      "
    >
      <div style="display: flex; flex-wrap: wrap; gap: 6px">
        <button
          type="button"
          class="toggle-chip"
          :class="{ active: activeStoreFilter === 'ALL' }"
          @click="activeStoreFilter = 'ALL'"
        >
          All Stores ({{ uncheckedCountByStore.ALL || 0 }})
        </button>
        <button
          v-for="st in stores"
          :key="st"
          type="button"
          class="toggle-chip"
          :class="{ active: activeStoreFilter === st }"
          @click="activeStoreFilter = st"
        >
          {{ st }} ({{ uncheckedCountByStore[st] || 0 }})
        </button>
      </div>

      <div style="display: flex; align-items: center; gap: 6px">
        <span style="font-size: 0.8rem; color: var(--muted); font-weight: 600">Group by:</span>
        <select v-model="groupMode" aria-label="Group shopping items by">
          <option value="category">Category</option>
          <option value="store_category">Store → Category</option>
          <option value="store">Store</option>
        </select>
      </div>
    </div>

    <div v-if="loading" class="card" style="text-align: center; color: var(--muted); padding: 24px">
      Loading shopping list...
    </div>

    <div
      v-else-if="!activeItems.length && !checkedItems.length"
      class="card"
      style="text-align: center; color: var(--muted); padding: 28px"
    >
      Your shopping list is empty. Use <strong>Import from Meal Plan</strong> above or add items directly!
    </div>

    <div v-else>
      <div
        v-for="section in groupedActiveSections"
        :key="section.key"
        class="card"
        style="margin-bottom: 12px"
      >
        <div
          style="
            font-weight: 700;
            font-size: 0.95rem;
            padding-bottom: 8px;
            margin-bottom: 8px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
          "
        >
          <span>{{ section.title }}</span>
          <span style="font-size: 0.78rem; color: var(--muted)">{{ section.rows.length }}</span>
        </div>

        <div style="display: flex; flex-direction: column; gap: 6px">
          <div
            v-for="item in section.rows"
            :key="item.id"
            style="
              display: flex;
              flex-wrap: wrap;
              align-items: center;
              justify-content: space-between;
              gap: 8px;
              padding: 7px 8px;
              border: 1px solid var(--border);
              border-radius: 8px;
              background: #fff;
            "
          >
            <label
              style="
                display: flex;
                align-items: flex-start;
                gap: 10px;
                cursor: pointer;
                flex: 1 1 240px;
              "
            >
              <input
                type="checkbox"
                :checked="item.checked"
                style="margin-top: 3px; width: 17px; height: 17px; cursor: pointer"
                @change="toggleChecked(item)"
              />
              <div>
                <div style="font-weight: 600; font-size: 0.94rem">
                  <span v-if="formatQuantity(item)" style="color: var(--primary); margin-right: 5px">
                    {{ formatQuantity(item) }}
                  </span>
                  <span>{{ item.name }}</span>
                  <span
                    v-if="item.note"
                    style="font-weight: 400; color: var(--muted); font-size: 0.82rem; margin-left: 5px"
                  >
                    ({{ item.note }})
                  </span>
                </div>
                <div
                  v-if="item.source_recipes?.length"
                  style="font-size: 0.75rem; color: var(--muted); margin-top: 2px"
                >
                  For: {{ item.source_recipes.join(', ') }}
                </div>
              </div>
            </label>

            <div style="display: flex; align-items: center; gap: 6px">
              <select
                :value="item.store"
                aria-label="Item store"
                style="padding: 3px 6px; font-size: 0.78rem"
                @change="updateItemField(item, 'store', $event.target.value)"
              >
                <option v-for="st in stores" :key="st" :value="st">{{ st }}</option>
              </select>
              <select
                :value="item.category"
                aria-label="Item category"
                style="padding: 3px 6px; font-size: 0.78rem"
                @change="updateItemField(item, 'category', $event.target.value)"
              >
                <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
              </select>
              <button
                type="button"
                title="Delete item"
                style="padding: 3px 8px; font-size: 0.78rem; color: var(--muted)"
                @click="deleteItem(item)"
              >
                ✕
              </button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="checkedItems.length" class="card" style="margin-top: 14px; background: #f8fafc">
        <div
          style="
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
          "
          @click="showChecked = !showChecked"
        >
          <strong style="font-size: 0.9rem; color: var(--muted)">
            ✓ Checked Off ({{ checkedItems.length }})
          </strong>
          <span style="font-size: 0.8rem; color: var(--muted)">
            {{ showChecked ? 'Hide ▲' : 'Show ▼' }}
          </span>
        </div>

        <div
          v-if="showChecked"
          style="display: flex; flex-direction: column; gap: 5px; margin-top: 10px"
        >
          <div
            v-for="item in checkedItems"
            :key="item.id"
            style="
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 8px;
              padding: 6px 8px;
              border-radius: 6px;
              opacity: 0.65;
            "
          >
            <label
              style="
                display: flex;
                align-items: center;
                gap: 10px;
                cursor: pointer;
                text-decoration: line-through;
                color: var(--muted);
                flex: 1;
              "
            >
              <input
                type="checkbox"
                checked
                style="width: 16px; height: 16px; cursor: pointer"
                @change="toggleChecked(item)"
              />
              <span>
                <span v-if="formatQuantity(item)">{{ formatQuantity(item) }} </span>
                {{ item.name }}
              </span>
              <span style="font-size: 0.74rem; text-decoration: none">
                · {{ item.store }} · {{ item.category }}
              </span>
            </label>
            <button
              type="button"
              title="Delete item"
              style="padding: 2px 7px; font-size: 0.75rem; color: var(--muted)"
              @click="deleteItem(item)"
            >
              ✕
            </button>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>
