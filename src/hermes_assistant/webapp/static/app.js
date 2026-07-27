/* HERMES Dashboard — Main application (Vue 3, requires screens.js loaded first) */
/* global Vue, ProjectListScreen, ProjectDetailScreen, PendenzenScreen, ReviewsScreen, WbsNodeItem, WbsTab */
'use strict';

const {
  createApp, ref, reactive, onMounted, onUnmounted, watch,
} = Vue;

// ── Global reactive state ──────────────────────────────────────────────────
const state = reactive({
  screen: 'projects',  // 'projects' | 'detail' | 'pendenzen' | 'reviews'
  projectId: null,     // currently selected project ID
  data: null,          // DashboardData from API
  loading: false,
  error: null,
  lastRefresh: null,
  showHelp: false,
  showImport: false,
});

// ── Theme ──────────────────────────────────────────────────────────────────
const theme = ref(localStorage.getItem('hermes-theme') || 'light');

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('hermes-theme', t);
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark';
  applyTheme(theme.value);
}

// ── Toast notifications ────────────────────────────────────────────────────
const toast = ref(null);
let _toastTimer = null;

function showToast(msg) {
  toast.value = msg;
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { toast.value = null; }, 4000);
}

// ── API fetch ──────────────────────────────────────────────────────────────
async function fetchData(projectId) {
  state.loading = true;
  state.error = null;
  try {
    const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    const resp = await fetch(`/api/dashboard${qs}`);
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${resp.status}`);
    }
    state.data = await resp.json();
    state.lastRefresh = new Date().toLocaleTimeString();
  } catch (e) {
    state.error = String(e.message || e);
  } finally {
    state.loading = false;
  }
}

async function refresh() {
  await fetchData(state.projectId);
}

// ── Navigation ─────────────────────────────────────────────────────────────
function goTo(screen) {
  state.screen = screen;
  if (screen === 'projects') {
    state.projectId = null;
    fetchData(null);
  }
}

function selectProject(projectId) {
  state.projectId = projectId;
  state.screen = 'detail';
  fetchData(projectId);
}

// ── Live polling (5 s, silent — only updates if generated_at changed) ──────
let _pollTimer = null;

function startPolling() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    if (state.loading) return;
    try {
      const qs = state.projectId ? `?project_id=${encodeURIComponent(state.projectId)}` : '';
      const resp = await fetch(`/api/dashboard${qs}`);
      if (!resp.ok) return;
      const fresh = await resp.json();
      if (fresh.generated_at !== state.data?.generated_at) {
        state.data = fresh;
        state.lastRefresh = new Date().toLocaleTimeString();
      }
    } catch {
      // Silently ignore polling errors to avoid toast spam
    }
  }, 5000);
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

// ── JSON Import ────────────────────────────────────────────────────────────
const importMode = ref('text');        // 'text' | 'file'
const importText = ref('');
const importFilename = ref('');
const importFileContent = ref('');
const importLoading = ref(false);
const importResult = ref(null);
const importError = ref('');
const importPreview = ref(null);

function _computePreview(jsonStr) {
  try {
    const data = JSON.parse(jsonStr);
    if (typeof data !== 'object' || Array.isArray(data)) return null;
    const counts = {};
    for (const [k, v] of Object.entries(data)) {
      if (Array.isArray(v)) counts[k] = v.length;
    }
    return Object.keys(counts).length > 0 ? counts : null;
  } catch {
    return null;
  }
}

function openImport() {
  state.showImport = true;
  importMode.value = 'text';
  importText.value = '';
  importFilename.value = '';
  importFileContent.value = '';
  importLoading.value = false;
  importResult.value = null;
  importError.value = '';
  importPreview.value = null;
}

function closeImport() {
  state.showImport = false;
}

function onImportFile(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  importFilename.value = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  const reader = new FileReader();
  reader.onload = (ev) => {
    importFileContent.value = ev.target.result;
    importPreview.value = _computePreview(importFileContent.value);
  };
  reader.readAsText(file);
}

async function runImport() {
  if (importLoading.value) return;
  const jsonStr = (importMode.value === 'text'
    ? importText.value
    : importFileContent.value
  ).trim();
  if (!jsonStr) {
    importError.value = 'No JSON provided.';
    return;
  }
  let payload;
  try {
    payload = JSON.parse(jsonStr);
  } catch (e) {
    importError.value = `Invalid JSON: ${e.message}`;
    return;
  }
  // Unused but validates object structure client-side
  void payload;
  importLoading.value = true;
  importError.value = '';
  importResult.value = null;
  try {
    const resp = await fetch('/api/import/json', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: jsonStr,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = data.detail;
      importError.value = typeof detail === 'string'
        ? detail
        : (detail && detail.errors ? detail.errors.join('; ') : `HTTP ${resp.status}`);
    } else {
      importResult.value = data;
      if (data.ok) {
        showToast(
          `Import done — ${data.created} created, ${data.updated} updated`
          + (data.skipped ? `, ${data.skipped} skipped` : '')
        );
        await refresh();
      }
    }
  } catch (e) {
    importError.value = String(e.message || e);
  } finally {
    importLoading.value = false;
  }
}

// ── Keyboard shortcuts ─────────────────────────────────────────────────────
function onKeydown(e) {
  // Ignore shortcuts when focus is inside an input or select
  const tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;

  switch (e.key) {
    case '1': goTo('projects'); break;
    case '2': goTo('detail'); break;
    case '3': goTo('pendenzen'); break;
    case '4': goTo('reviews'); break;
    case 'r': refresh(); break;
    case 'd': toggleTheme(); break;
    case 'i': openImport(); break;
    case '?': state.showHelp = !state.showHelp; break;
    case 'Escape':
      state.showHelp = false;
      if (state.showImport) closeImport();
      break;
    default: break;
  }
}

// ── Root App component ─────────────────────────────────────────────────────
const App = {
  components: {
    ProjectListScreen,
    ProjectDetailScreen,
    PendenzenScreen,
    ReviewsScreen,
  },
  setup() {
    // Show toast whenever an API error occurs
    watch(() => state.error, (err) => { if (err) showToast(err); });

    // Live preview as user types JSON
    watch(importText, (val) => { importPreview.value = _computePreview(val); });

    onMounted(() => {
      applyTheme(theme.value);
      document.addEventListener('keydown', onKeydown);
      fetchData(null);
      startPolling();
    });

    onUnmounted(() => {
      document.removeEventListener('keydown', onKeydown);
      stopPolling();
    });

    const navItems = [
      { key: 'projects', label: 'Projects', shortcut: '1', icon: '▤' },
      { key: 'detail',   label: 'Project Detail', shortcut: '2', icon: '◫' },
      { key: 'pendenzen', label: 'Pendenzen', shortcut: '3', icon: '⚑' },
      { key: 'reviews',  label: 'Reviews', shortcut: '4', icon: '✓' },
    ];

    const shortcuts = [
      ['1', 'Projects screen'],
      ['2', 'Project detail'],
      ['3', 'Pendenzen'],
      ['4', 'Reviews'],
      ['r', 'Refresh data'],
      ['i', 'Import JSON'],
      ['d', 'Toggle dark / light theme'],
      ['?', 'Show / hide this help'],
      ['Esc', 'Close modal'],
    ];

    return {
      state, theme, toast, navItems, shortcuts,
      toggleTheme, refresh, goTo, selectProject,
      // Import modal
      openImport, closeImport, onImportFile, runImport,
      importMode, importText, importFilename, importLoading,
      importResult, importError, importPreview,
    };
  },
  template: `
    <div class="hermes-layout">

      <!-- ── Navbar ─────────────────────────────────────────────────────── -->
      <nav class="hermes-navbar" role="banner">
        <span class="font-bold text-white tracking-widest text-base select-none">HERMES</span>
        <span class="text-slate-400 text-xs flex-1 hidden sm:block">Local Dashboard</span>

        <span v-if="state.projectId" class="text-slate-300 text-xs hidden md:block">
          Project:&nbsp;<strong class="text-white font-mono">{{ state.projectId }}</strong>
        </span>

        <button
          @click="refresh"
          :disabled="state.loading"
          class="text-slate-300 hover:text-white text-sm px-2 py-1 rounded hover:bg-slate-700 transition-colors"
          :aria-label="state.loading ? 'Loading…' : 'Refresh (r)'"
        >{{ state.loading ? '⏳' : '↻' }}&nbsp;Refresh</button>

        <button
          @click="openImport"
          class="text-slate-300 hover:text-white text-sm px-2 py-1 rounded hover:bg-slate-700 transition-colors"
          aria-label="Import JSON (i)"
          title="Import JSON (i)"
        >&#8593;&nbsp;Import</button>

        <button
          @click="toggleTheme"
          class="text-slate-300 hover:text-white text-sm px-2 py-1 rounded hover:bg-slate-700 transition-colors"
          :aria-label="'Toggle theme (d) — currently ' + theme"
          :title="'Toggle theme (d)'"
        >{{ theme === 'dark' ? '☀' : '◑' }}</button>

        <button
          @click="state.showHelp = true"
          class="text-slate-300 hover:text-white text-sm px-3 py-1 rounded hover:bg-slate-700 transition-colors font-bold"
          aria-label="Keyboard shortcuts (?)"
          title="Shortcuts (?)"
        >?</button>
      </nav>

      <!-- ── Sidebar ────────────────────────────────────────────────────── -->
      <aside class="hermes-sidebar" role="navigation" aria-label="Main navigation">
        <button
          v-for="item in navItems"
          :key="item.key"
          class="nav-btn"
          :class="{ active: state.screen === item.key }"
          :aria-current="state.screen === item.key ? 'page' : undefined"
          @click="goTo(item.key)"
        >
          <span class="w-5 text-center select-none" aria-hidden="true">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
          <span class="ml-auto text-xs opacity-50 font-mono">{{ item.shortcut }}</span>
        </button>
      </aside>

      <!-- ── Main content ───────────────────────────────────────────────── -->
      <main class="hermes-main" role="main">
        <project-list-screen
          v-if="state.screen === 'projects'"
          :data="state.data"
          :loading="state.loading"
          :error="state.error"
          @select-project="selectProject"
        />
        <project-detail-screen
          v-else-if="state.screen === 'detail'"
          :data="state.data"
          :loading="state.loading"
          :error="state.error"
          :project-id="state.projectId"
          @back="goTo('projects')"
        />
        <pendenzen-screen
          v-else-if="state.screen === 'pendenzen'"
          :data="state.data"
          :loading="state.loading"
          :error="state.error"
        />
        <reviews-screen
          v-else
          :data="state.data"
          :loading="state.loading"
          :error="state.error"
        />

        <!-- Status bar -->
        <footer class="mt-8 pt-3 flex flex-wrap gap-4 text-xs"
                style="color:var(--c-text-muted);border-top:1px solid var(--c-border)">
          <span>Last refresh: {{ state.lastRefresh || '—' }}</span>
          <span v-if="state.data?.generated_at">Server: {{ state.data.generated_at }}</span>
          <span v-if="state.loading" class="flex items-center gap-1">
            <span class="spinner" style="width:10px;height:10px;border-width:1.5px"></span> Updating&hellip;
          </span>
        </footer>
      </main>

      <!-- ── Help modal ─────────────────────────────────────────────────── -->
      <div v-if="state.showHelp" class="modal-overlay" @click.self="state.showHelp = false" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
        <div class="modal-box" style="max-width:380px">
          <div class="flex justify-between items-center mb-4">
            <h2 class="font-semibold text-base">Keyboard Shortcuts</h2>
            <button @click="state.showHelp = false" class="text-gray-400 hover:text-gray-600 text-2xl leading-none" aria-label="Close help">&times;</button>
          </div>
          <table class="w-full text-sm">
            <tbody>
              <tr v-for="[key, desc] in shortcuts" :key="key" class="border-b" style="border-color:var(--c-border)">
                <td class="py-2 pr-4 w-16"><kbd class="kbd">{{ key }}</kbd></td>
                <td class="py-2">{{ desc }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ── Import JSON Modal ──────────────────────────────────────────── -->
      <div v-if="state.showImport"
           class="modal-overlay"
           @click.self="closeImport"
           role="dialog"
           aria-modal="true"
           aria-label="Import JSON data"
           data-testid="import-modal">
        <div class="modal-box" style="max-width:560px">
          <div class="flex justify-between items-center mb-4">
            <h2 class="font-semibold text-base">Import JSON</h2>
            <button @click="closeImport"
                    class="text-gray-400 hover:text-gray-600 text-2xl leading-none"
                    aria-label="Close import modal">&times;</button>
          </div>

          <!-- Mode toggle -->
          <div class="flex gap-2 mb-3">
            <button @click="importMode='text'"
                    class="text-xs px-3 py-1 rounded border transition-colors"
                    :style="importMode==='text'
                      ? 'background:var(--c-primary);color:#fff;border-color:var(--c-primary)'
                      : 'border-color:var(--c-border)'"
                    data-testid="mode-text">Paste JSON</button>
            <button @click="importMode='file'"
                    class="text-xs px-3 py-1 rounded border transition-colors"
                    :style="importMode==='file'
                      ? 'background:var(--c-primary);color:#fff;border-color:var(--c-primary)'
                      : 'border-color:var(--c-border)'"
                    data-testid="mode-file">Upload File</button>
          </div>

          <!-- Text mode -->
          <div v-if="importMode==='text'">
            <textarea
              v-model="importText"
              placeholder='{"risks": [{"title": "Example risk"}]}'
              class="w-full font-mono text-xs rounded p-2"
              style="min-height:180px;background:var(--c-bg-card);border:1px solid var(--c-border);color:var(--c-text);resize:vertical"
              data-testid="import-textarea"
            ></textarea>
          </div>

          <!-- File mode -->
          <div v-else
               class="flex flex-col items-center justify-center p-8 rounded cursor-pointer"
               style="border:2px dashed var(--c-border);min-height:180px"
               @click="$el.querySelector('#import-file-input').click()">
            <input id="import-file-input"
                   type="file"
                   accept=".json,application/json"
                   @change="onImportFile"
                   style="display:none"
                   data-testid="import-file-input">
            <span style="color:var(--c-primary)">Click to select a JSON file</span>
            <span v-if="importFilename"
                  class="mt-2 text-xs"
                  style="color:var(--c-text-muted)"
                  data-testid="import-filename">{{ importFilename }}</span>
            <span v-else class="mt-2 text-xs" style="color:var(--c-text-muted)">
              or drag and drop
            </span>
          </div>

          <!-- Preview -->
          <div v-if="importPreview"
               class="mt-3 p-2 rounded text-xs"
               style="background:var(--c-bg-card);border:1px solid var(--c-border)"
               data-testid="import-preview">
            <strong>Will import:</strong>
            <span v-for="(count, type) in importPreview" :key="type" class="ml-2">
              {{ type }}: <strong>{{ count }}</strong>
            </span>
          </div>

          <!-- Result -->
          <div v-if="importResult"
               class="mt-3 p-2 rounded text-xs"
               style="background:var(--c-bg-card);border:1px solid var(--c-border)"
               data-testid="import-result">
            <span v-if="importResult.ok" style="color:#22c55e">
              Done: {{ importResult.created }} created,
              {{ importResult.updated }} updated
              <template v-if="importResult.skipped">,
                {{ importResult.skipped }} skipped
              </template>
            </span>
            <span v-else style="color:#ef4444">Import failed</span>
            <ul v-if="importResult.errors && importResult.errors.length"
                class="mt-1 list-disc pl-4"
                style="color:#f97316">
              <li v-for="e in importResult.errors.slice(0, 5)" :key="e">{{ e }}</li>
              <li v-if="importResult.errors.length > 5"
                  style="color:var(--c-text-muted)">
                +{{ importResult.errors.length - 5 }} more errors
              </li>
            </ul>
          </div>

          <!-- Inline error -->
          <div v-if="importError"
               class="mt-3 text-xs"
               style="color:#ef4444"
               data-testid="import-error">{{ importError }}</div>

          <!-- Spinner -->
          <div v-if="importLoading" class="mt-3 flex items-center gap-2 text-xs" style="color:var(--c-text-muted)">
            <span class="spinner" style="width:12px;height:12px;border-width:1.5px"></span>
            Importing&hellip;
          </div>

          <!-- Action buttons -->
          <div class="flex gap-3 mt-4">
            <button
              @click="runImport"
              :disabled="importLoading"
              class="text-sm px-4 py-2 rounded transition-colors"
              style="background:var(--c-primary);color:#fff"
              :style="importLoading ? 'opacity:0.6;cursor:not-allowed' : ''"
              data-testid="import-submit"
            >{{ importLoading ? 'Importing…' : 'Import' }}</button>
            <button
              @click="closeImport"
              class="text-sm px-4 py-2 rounded transition-colors"
              style="background:var(--c-bg-card);border:1px solid var(--c-border)"
              data-testid="import-cancel"
            >Cancel</button>
          </div>
        </div>
      </div>

      <!-- ── Toast ──────────────────────────────────────────────────────── -->
      <div v-if="toast" class="toast" role="alert" aria-live="assertive">
        {{ toast }}
      </div>
    </div>
  `,
};

// ── Mount ──────────────────────────────────────────────────────────────────
// Register shared sub-components globally so they are available in all
// screen templates without repeating the local components: {} declaration.
const vueApp = createApp(App);
vueApp.component('WbsNodeItem', WbsNodeItem);  // recursive — must be global
vueApp.component('WbsTab', WbsTab);
vueApp.component('TimelineTab', TimelineTab);
vueApp.component('KanbanTab', KanbanTab);
vueApp.mount('#app');
