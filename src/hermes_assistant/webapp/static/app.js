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
    case '?': state.showHelp = !state.showHelp; break;
    case 'Escape': state.showHelp = false; break;
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
      ['d', 'Toggle dark / light theme'],
      ['?', 'Show / hide this help'],
      ['Esc', 'Close modal'],
    ];

    return {
      state, theme, toast, navItems, shortcuts,
      toggleTheme, refresh, goTo, selectProject,
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
