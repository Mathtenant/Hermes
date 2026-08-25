/* HERMES Dashboard — Screen components.
 * Loaded after components.js and before app.js.
 *
 * Wrapped in an IIFE (and exported on `window`) because classic <script> tags
 * share one global lexical scope — see the note at the top of components.js.
 */
/* global Vue */
(function (global) {
'use strict';

const { ref, computed } = Vue;

// Shared: rank used wherever priorities are ordered.
const PRIO_RANK = { blocker: 0, high: 1, medium: 2, low: 3 };

// ── OverviewScreen ─────────────────────────────────────────────────────────
// Landing screen: headline counts (each tile navigates), plus the two lists a
// project lead looks at first — what is due next and what is riskiest.
const OverviewScreen = {
  props: ['data', 'loading', 'error', 'counts'],
  emits: ['navigate', 'select-project', 'import'],
  setup(props) {
    const openPendenzen = computed(
      () => (props.data?.pendenzen ?? []).filter(p => p.status !== 'closed')
    );

    const blockers = computed(
      () => openPendenzen.value.filter(p => p.priority === 'blocker')
    );

    const openRisks = computed(
      () => (props.data?.risks ?? []).filter(r => r.status === 'open')
    );

    // Next five dated timeline entries that are not already closed.
    const upcoming = computed(() => {
      const today = new Date().toISOString().slice(0, 10);
      return (props.data?.timeline ?? [])
        .filter(e => e.status !== 'closed' && e.date >= today)
        .sort((a, b) => a.date.localeCompare(b.date))
        .slice(0, 5);
    });

    const topRisks = computed(
      () => [...(props.data?.risks ?? [])]
        .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
        .slice(0, 5)
    );

    const urgentPendenzen = computed(
      () => [...openPendenzen.value]
        .sort((a, b) => (PRIO_RANK[a.priority] ?? 9) - (PRIO_RANK[b.priority] ?? 9))
        .slice(0, 5)
    );

    const isEmpty = computed(
      () => !props.loading
        && !props.error
        && (props.counts?.projects ?? 0) === 0
        && (props.counts?.risks ?? 0) === 0
        && (props.counts?.pendenzen ?? 0) === 0
    );

    function scoreBand(score) {
      if (score >= 15) return 'critical';
      if (score >= 9) return 'high';
      if (score >= 4) return 'medium';
      return 'low';
    }

    return {
      openPendenzen, blockers, openRisks, upcoming, topRisks,
      urgentPendenzen, isEmpty, scoreBand,
    };
  },
  template: `
    <div>
      <div class="page-header">
        <div>
          <h1 class="page-title">Overview</h1>
          <div class="page-subtitle">
            {{ data?.scope || 'all projects' }}
            <template v-if="data?.range_start"> · {{ data.range_start }} → {{ data.range_end }}</template>
          </div>
        </div>
      </div>

      <div v-if="loading && !data" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="card notice-error">{{ error }}</div>

      <template v-else>
        <!-- Headline counts — each tile is a shortcut into its screen -->
        <div class="stat-grid">
          <button class="stat-tile" @click="$emit('navigate', 'projects')">
            <span class="stat-label">Projects</span>
            <span class="stat-value">{{ counts.projects }}</span>
            <span class="stat-hint">View all projects</span>
          </button>

          <button class="stat-tile" @click="$emit('navigate', 'detail')">
            <span class="stat-label">Timeline items</span>
            <span class="stat-value">{{ counts.timeline }}</span>
            <span class="stat-hint">{{ upcoming.length }} upcoming</span>
          </button>

          <button class="stat-tile"
                  :class="{ 'is-alert': blockers.length > 0 }"
                  @click="$emit('navigate', 'pendenzen')">
            <span class="stat-label">Pendenzen</span>
            <span class="stat-value">{{ counts.pendenzen }}</span>
            <span class="stat-hint">
              {{ openPendenzen.length }} open<template v-if="blockers.length">, {{ blockers.length }} blocker</template>
            </span>
          </button>

          <button class="stat-tile"
                  :class="{ 'is-alert': openRisks.length > 0 }"
                  @click="$emit('navigate', 'risks')">
            <span class="stat-label">Risks</span>
            <span class="stat-value" data-testid="risks-count">{{ counts.risks }}</span>
            <span class="stat-hint">{{ openRisks.length }} open</span>
          </button>

          <button class="stat-tile" @click="$emit('navigate', 'reviews')">
            <span class="stat-label">Reviews</span>
            <span class="stat-value">{{ counts.reviews }}</span>
            <span class="stat-hint">Rubric verdicts</span>
          </button>
        </div>

        <!-- Nothing imported yet -->
        <div v-if="isEmpty" class="card">
          <div class="empty-state">
            <span class="empty-state-icon" aria-hidden="true">◵</span>
            <div class="empty-state-title">No project data yet</div>
            <p class="text-sm mb-4">
              Import a Copilot JSON export to populate the dashboard, or create a
              project directory under <code>data/projects/</code>.
            </p>
            <button class="btn btn-primary" @click="$emit('import')">Import JSON</button>
          </div>
        </div>

        <div v-else class="stat-grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
          <!-- Coming up -->
          <section class="card">
            <div class="flex justify-between items-center mb-3">
              <h2 class="text-base font-semibold">Coming up</h2>
              <button class="btn-link" @click="$emit('navigate', 'detail')">Timeline &rarr;</button>
            </div>
            <div v-if="!upcoming.length" class="text-sm text-gray-400 py-2">
              Nothing scheduled ahead.
            </div>
            <div v-for="e in upcoming" :key="e.date + e.label" class="tl-entry">
              <span class="tl-date">{{ e.date }}</span>
              <span :class="['tl-dot', e.status]" :aria-label="e.status"></span>
              <span class="flex-1 truncate" :title="e.label">{{ e.label }}</span>
              <span class="text-xs text-gray-400 shrink-0">{{ e.kind }}</span>
            </div>
          </section>

          <!-- Needs attention -->
          <section class="card">
            <div class="flex justify-between items-center mb-3">
              <h2 class="text-base font-semibold">Needs attention</h2>
              <button class="btn-link" @click="$emit('navigate', 'pendenzen')">Pendenzen &rarr;</button>
            </div>
            <div v-if="!urgentPendenzen.length" class="text-sm text-gray-400 py-2">
              No open pendenzen.
            </div>
            <div v-for="p in urgentPendenzen" :key="p.id" class="tl-entry">
              <span :class="['prio-dot', p.priority]" :aria-label="p.priority"></span>
              <span class="flex-1 truncate" :title="p.title">{{ p.title }}</span>
              <span class="text-xs text-gray-400 shrink-0">{{ p.owner || '—' }}</span>
              <span class="text-xs font-mono text-gray-400 shrink-0">{{ p.due_date || '' }}</span>
            </div>
          </section>

          <!-- Top risks -->
          <section class="card">
            <div class="flex justify-between items-center mb-3">
              <h2 class="text-base font-semibold">Highest-scoring risks</h2>
              <button class="btn-link" @click="$emit('navigate', 'risks')">Risks &rarr;</button>
            </div>
            <div v-if="!topRisks.length" class="text-sm text-gray-400 py-2">
              No risks recorded.
            </div>
            <div v-for="r in topRisks" :key="r.id" class="tl-entry">
              <span class="flex-1 truncate" :title="r.title">{{ r.title }}</span>
              <span class="score-bar shrink-0">
                <span class="score-track">
                  <span class="score-fill"
                        :class="scoreBand(r.score)"
                        :style="{ width: Math.min(100, (r.score / 25) * 100) + '%' }"></span>
                </span>
                <span class="text-xs tabular-nums font-semibold">{{ r.score }}</span>
              </span>
            </div>
          </section>
        </div>
      </template>
    </div>
  `,
};

// ── ProjectListScreen ──────────────────────────────────────────────────────
const ProjectListScreen = {
  props: ['data', 'loading', 'error'],
  emits: ['select-project'],
  setup(props) {
    const sortKey = ref('project_id');
    const sortDir = ref(1);
    const query = ref('');

    const sorted = computed(() => {
      const q = query.value.trim().toLowerCase();
      const rows = (props.data?.projects ?? []).filter(
        p => !q
          || String(p.project_id).toLowerCase().includes(q)
          || String(p.label ?? '').toLowerCase().includes(q)
      );
      return [...rows].sort((a, b) => {
        const av = String(a[sortKey.value] ?? '');
        const bv = String(b[sortKey.value] ?? '');
        return sortDir.value * av.localeCompare(bv);
      });
    });

    function toggleSort(key) {
      if (sortKey.value === key) sortDir.value *= -1;
      else { sortKey.value = key; sortDir.value = 1; }
    }

    function sortIcon(key) {
      return sortKey.value === key ? (sortDir.value === 1 ? ' ↑' : ' ↓') : '';
    }

    function tlCount(pid) {
      return (props.data?.timeline ?? []).filter(e => e.project_id === pid).length;
    }

    return { sorted, query, toggleSort, sortIcon, tlCount };
  },
  template: `
    <div>
      <div class="page-header">
        <div>
          <h1 class="page-title">Projects</h1>
          <div class="page-subtitle">Select a project to open its timeline, kanban and WBS.</div>
        </div>
      </div>

      <div v-if="loading && !data" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="card notice-error">{{ error }}</div>
      <div v-else-if="!data?.projects?.length" class="card">
        <div class="empty-state">
          <span class="empty-state-icon" aria-hidden="true">▤</span>
          <div class="empty-state-title">No projects found</div>
          <p class="text-sm">Create a directory under <code>data/projects/</code> or import a JSON export.</p>
        </div>
      </div>
      <div v-else>
        <div class="filter-bar">
          <input class="text-input"
                 type="search"
                 v-model="query"
                 placeholder="Filter projects…"
                 aria-label="Filter projects">
          <span class="result-count">{{ sorted.length }} of {{ data.projects.length }}</span>
        </div>

        <div class="card card-flush overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th @click="toggleSort('project_id')">Project{{ sortIcon('project_id') }}</th>
                <th @click="toggleSort('label')">Label{{ sortIcon('label') }}</th>
                <th class="text-right">Timeline</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in sorted"
                  :key="p.project_id"
                  class="is-clickable"
                  tabindex="0"
                  @click="$emit('select-project', p.project_id)"
                  @keydown.enter="$emit('select-project', p.project_id)">
                <td class="font-mono font-medium text-blue-500">{{ p.project_id }}</td>
                <td>{{ p.label || '—' }}</td>
                <td class="text-right tabular-nums">{{ tlCount(p.project_id) }}</td>
                <td class="text-right text-gray-400" aria-hidden="true">&rsaquo;</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
};

// ── TimelineTab ────────────────────────────────────────────────────────────
const TimelineTab = {
  props: ['entries'],
  setup(props) {
    const filterStatus = ref('');

    const filtered = computed(() => {
      const rows = props.entries ?? [];
      return filterStatus.value ? rows.filter(e => e.status === filterStatus.value) : rows;
    });

    function labelClass(status) {
      if (status === 'blocked') return 'tl-label-blocked';
      if (status === 'closed') return 'tl-label-closed';
      return '';
    }

    return { filterStatus, filtered, labelClass };
  },
  template: `
    <div>
      <div class="filter-bar">
        <select class="filter-select" v-model="filterStatus" aria-label="Filter by status">
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
          <option value="blocked">Blocked</option>
          <option value="future">Future</option>
        </select>
        <span class="result-count">{{ filtered.length }} items</span>
      </div>
      <div v-if="!filtered.length" class="empty-state">
        <div class="empty-state-title">No timeline items</div>
        <p class="text-sm">Run <code>hermes schedule</code> to derive one.</p>
      </div>
      <div v-for="e in filtered" :key="e.date + e.label" class="tl-entry">
        <span class="tl-date">{{ e.date }}</span>
        <span :class="['tl-dot', e.status]" :aria-label="e.status"></span>
        <span :class="labelClass(e.status)" class="flex-1">{{ e.label }}</span>
        <span class="text-gray-400 text-xs shrink-0">{{ e.kind }}</span>
        <span class="text-gray-400 text-xs shrink-0 font-mono">{{ e.project_id }}</span>
      </div>
    </div>
  `,
};

// ── KanbanTab ──────────────────────────────────────────────────────────────
const KanbanTab = {
  props: ['columns'],
  setup() {
    const selectedCard = ref(null);
    return {
      selectedCard,
      openCard(card) { selectedCard.value = card; },
      closeCard() { selectedCard.value = null; },
    };
  },
  template: `
    <div>
      <div v-if="!columns?.length" class="empty-state">
        <div class="empty-state-title">No kanban data</div>
      </div>
      <div v-else class="kanban-board">
        <div v-for="col in columns" :key="col.status" class="kanban-col">
          <div class="kanban-col-header">
            <span>{{ col.label }}</span>
            <span class="kanban-count">{{ col.cards.length + col.overflow }}</span>
          </div>
          <div v-if="!col.cards.length && !col.overflow"
               class="text-gray-400 text-xs italic text-center py-4">
            Empty
          </div>
          <div v-for="card in col.cards"
               :key="card.id"
               class="kanban-card"
               tabindex="0"
               @click="openCard(card)"
               @keydown.enter="openCard(card)">
            <div class="text-gray-400 font-mono text-xs mb-0.5">{{ card.wbs_number }}</div>
            <div class="font-medium leading-snug">{{ card.title }}</div>
            <div class="flex items-center gap-2 mt-1 flex-wrap">
              <span v-if="card.owner" class="text-gray-400 text-xs">{{ card.owner }}</span>
              <span v-if="card.priority"
                    class="badge"
                    :class="card.priority === 'blocker' ? 'badge-blocked' : 'badge-open'">
                {{ card.priority }}
              </span>
            </div>
          </div>
          <div v-if="col.overflow" class="text-gray-400 text-xs italic text-center py-1">
            +{{ col.overflow }} more&hellip;
          </div>
        </div>
      </div>

      <!-- Card detail -->
      <div v-if="selectedCard" class="modal-overlay" @click.self="closeCard"
           role="dialog" aria-modal="true" aria-label="Task detail">
        <div class="modal-box" style="max-width:440px">
          <div class="flex justify-between items-start mb-4">
            <h3 class="modal-title leading-tight pr-4">{{ selectedCard.title }}</h3>
            <button class="modal-close" @click="closeCard" aria-label="Close">&times;</button>
          </div>
          <table class="text-sm w-full">
            <tbody>
              <tr v-for="[k, v] in [
                    ['WBS', selectedCard.wbs_number || '—'],
                    ['Kind', selectedCard.kind],
                    ['Owner', selectedCard.owner || '—'],
                    ['Priority', selectedCard.priority || '—']]"
                  :key="k">
                <td class="text-gray-400 pr-4 py-1.5 w-24 align-top">{{ k }}</td>
                <td class="font-mono text-xs py-1.5">{{ v }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
};

// ── ProjectDetailScreen ────────────────────────────────────────────────────
// WbsTab / WbsNodeItem are registered globally in app.js.
const ProjectDetailScreen = {
  props: ['data', 'loading', 'error', 'projectId'],
  emits: ['back'],
  components: { TimelineTab, KanbanTab },
  setup() {
    const activeTab = ref('timeline');
    return { activeTab };
  },
  template: `
    <div>
      <div class="page-header">
        <div>
          <button v-if="projectId" class="btn-link mb-1" @click="$emit('back')"
                  aria-label="Back to all projects">&larr; All projects</button>
          <h1 class="page-title">{{ projectId || 'All projects' }}</h1>
          <div class="page-subtitle">Timeline, kanban board and work breakdown structure.</div>
        </div>
      </div>

      <div v-if="loading && !data" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="card notice-error">{{ error }}</div>
      <div v-else>
        <div class="tab-bar">
          <button class="tab-btn" :class="{ active: activeTab === 'timeline' }" @click="activeTab = 'timeline'">
            Timeline ({{ data?.timeline?.length ?? 0 }})
          </button>
          <button class="tab-btn" :class="{ active: activeTab === 'kanban' }" @click="activeTab = 'kanban'">
            Kanban
          </button>
          <button class="tab-btn" :class="{ active: activeTab === 'wbs' }" @click="activeTab = 'wbs'">
            WBS ({{ data?.wbs?.length ?? 0 }})
          </button>
        </div>
        <div class="card">
          <timeline-tab v-if="activeTab === 'timeline'" :entries="data?.timeline ?? []" />
          <kanban-tab v-else-if="activeTab === 'kanban'" :columns="data?.kanban ?? []" />
          <wbs-tab v-else :nodes="data?.wbs ?? []" />
        </div>
      </div>
    </div>
  `,
};

// ── PendenzenScreen ────────────────────────────────────────────────────────
const PendenzenScreen = {
  props: ['data', 'loading', 'error'],
  setup(props) {
    const query = ref('');
    const filterSource = ref('');
    const filterPriority = ref('');
    const filterStatus = ref('');
    const sortKey = ref('priority');
    const sortDir = ref(1);

    const sources = computed(
      () => [...new Set((props.data?.pendenzen ?? []).map(r => r.source))].sort()
    );
    const statuses = computed(
      () => [...new Set((props.data?.pendenzen ?? []).map(r => r.status))].sort()
    );

    const filtered = computed(() => {
      const q = query.value.trim().toLowerCase();
      let rows = props.data?.pendenzen ?? [];
      if (q) {
        rows = rows.filter(
          r => String(r.title ?? '').toLowerCase().includes(q)
            || String(r.owner ?? '').toLowerCase().includes(q)
        );
      }
      if (filterSource.value) rows = rows.filter(r => r.source === filterSource.value);
      if (filterPriority.value) rows = rows.filter(r => r.priority === filterPriority.value);
      if (filterStatus.value) rows = rows.filter(r => r.status === filterStatus.value);
      return [...rows].sort((a, b) => {
        if (sortKey.value === 'priority') {
          const diff = (PRIO_RANK[a.priority] ?? 9) - (PRIO_RANK[b.priority] ?? 9);
          return sortDir.value * diff;
        }
        return sortDir.value
          * String(a[sortKey.value] ?? '').localeCompare(String(b[sortKey.value] ?? ''));
      });
    });

    function toggleSort(key) {
      if (sortKey.value === key) sortDir.value *= -1;
      else { sortKey.value = key; sortDir.value = 1; }
    }

    function sortIcon(key) {
      return sortKey.value === key ? (sortDir.value === 1 ? ' ↑' : ' ↓') : '';
    }

    function statusBadgeClass(s) {
      const map = { open: 'badge-open', closed: 'badge-closed', blocked: 'badge-blocked' };
      return `badge ${map[s] ?? 'badge-open'}`;
    }

    function resetFilters() {
      query.value = '';
      filterSource.value = '';
      filterPriority.value = '';
      filterStatus.value = '';
    }

    return {
      query, filterSource, filterPriority, filterStatus, sources, statuses,
      filtered, toggleSort, sortIcon, statusBadgeClass, resetFilters,
    };
  },
  template: `
    <div>
      <div class="page-header">
        <div>
          <h1 class="page-title">Pendenzen</h1>
          <div class="page-subtitle">Open items gathered from meetings, reviews and the task tree.</div>
        </div>
      </div>

      <div v-if="loading && !data" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="card notice-error">{{ error }}</div>
      <div v-else>
        <div class="filter-bar">
          <input class="text-input" type="search" v-model="query"
                 placeholder="Search title or owner…" aria-label="Search pendenzen"
                 data-testid="pendenzen-search">
          <select class="filter-select" v-model="filterSource" aria-label="Filter by source"
                  data-testid="risk-filter-source">
            <option value="">All sources</option>
            <option v-for="s in sources" :key="s" :value="s">{{ s }}</option>
          </select>
          <select class="filter-select" v-model="filterPriority" aria-label="Filter by priority">
            <option value="">All priorities</option>
            <option value="blocker">Blocker</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select class="filter-select" v-model="filterStatus" aria-label="Filter by status">
            <option value="">All statuses</option>
            <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
          </select>
          <span class="result-count">{{ filtered.length }} of {{ data?.pendenzen?.length ?? 0 }}</span>
        </div>

        <div v-if="!filtered.length" class="card">
          <div class="empty-state">
            <div class="empty-state-title">Nothing matches these filters</div>
            <button class="btn mt-2" @click="resetFilters">Reset filters</button>
          </div>
        </div>
        <div v-else class="card card-flush overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th @click="toggleSort('title')">Title{{ sortIcon('title') }}</th>
                <th @click="toggleSort('source')">Source{{ sortIcon('source') }}</th>
                <th @click="toggleSort('priority')">Priority{{ sortIcon('priority') }}</th>
                <th @click="toggleSort('status')">Status{{ sortIcon('status') }}</th>
                <th @click="toggleSort('owner')">Owner{{ sortIcon('owner') }}</th>
                <th @click="toggleSort('due_date')">Due{{ sortIcon('due_date') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in filtered" :key="r.id">
                <td class="max-w-xs truncate" :title="r.title">{{ r.title }}</td>
                <td><span class="badge badge-open">{{ r.source }}</span></td>
                <td>
                  <span class="inline-flex items-center gap-1">
                    <span :class="['prio-dot', r.priority]"></span>{{ r.priority }}
                  </span>
                </td>
                <td><span :class="statusBadgeClass(r.status)">{{ r.status }}</span></td>
                <td class="text-gray-400">{{ r.owner || '—' }}</td>
                <td class="font-mono text-xs">{{ r.due_date || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
};

// ── RisksScreen ───────────────────────────────────────────────────────────
const RisksScreen = {
  props: ['data', 'loading', 'error'],
  setup(props) {
    const query = ref('');
    const filterStatus = ref('');
    const sortKey = ref('score');
    const sortDir = ref(-1);

    const filtered = computed(() => {
      const q = query.value.trim().toLowerCase();
      let rows = props.data?.risks ?? [];
      if (q) rows = rows.filter(r => String(r.title ?? '').toLowerCase().includes(q));
      if (filterStatus.value) rows = rows.filter(r => r.status === filterStatus.value);
      return [...rows].sort((a, b) => {
        const av = a[sortKey.value];
        const bv = b[sortKey.value];
        if (typeof av === 'number' && typeof bv === 'number') return sortDir.value * (av - bv);
        return sortDir.value * String(av ?? '').localeCompare(String(bv ?? ''));
      });
    });

    const openCount = computed(() => (props.data?.risks ?? []).filter(r => r.status === 'open').length);

    function toggleSort(key) {
      if (sortKey.value === key) sortDir.value *= -1;
      else { sortKey.value = key; sortDir.value = -1; }
    }

    function sortIcon(key) {
      return sortKey.value === key ? (sortDir.value === 1 ? ' ↑' : ' ↓') : '';
    }

    function statusClass(s) {
      const map = {
        open: 'risk-open',
        mitigated: 'risk-mitigated',
        accepted: 'risk-accepted',
        closed: 'risk-closed',
      };
      return map[s] ?? '';
    }

    function scoreBand(score) {
      if (score >= 15) return 'critical';
      if (score >= 9) return 'high';
      if (score >= 4) return 'medium';
      return 'low';
    }

    return { query, filterStatus, filtered, openCount, toggleSort, sortIcon, statusClass, scoreBand };
  },
  template: `
    <div>
      <div class="page-header">
        <div>
          <h1 class="page-title">Risks</h1>
          <div class="page-subtitle">{{ openCount }} open of {{ data?.risks?.length ?? 0 }} recorded.</div>
        </div>
      </div>

      <div v-if="loading && !data" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="card notice-error">{{ error }}</div>
      <div v-else>
        <div class="filter-bar">
          <input class="text-input" type="search" v-model="query"
                 placeholder="Search risks…" aria-label="Search risks">
          <select class="filter-select" v-model="filterStatus" aria-label="Filter by status">
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="mitigated">Mitigated</option>
            <option value="accepted">Accepted</option>
            <option value="closed">Closed</option>
          </select>
          <span class="result-count">
            <span data-testid="risks-count">{{ data?.risks?.length ?? 0 }}</span> risks
          </span>
        </div>

        <div v-if="!filtered.length" class="card">
          <div class="empty-state">
            <div class="empty-state-title">No risks match</div>
            <p class="text-sm">Import a JSON export or add risks with <code>hermes risk-add</code>.</p>
          </div>
        </div>
        <div v-else class="card card-flush overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th @click="toggleSort('title')">Title{{ sortIcon('title') }}</th>
                <th @click="toggleSort('severity')">Severity{{ sortIcon('severity') }}</th>
                <th @click="toggleSort('likelihood')" class="text-right">Likelihood{{ sortIcon('likelihood') }}</th>
                <th @click="toggleSort('score')">Score{{ sortIcon('score') }}</th>
                <th @click="toggleSort('status')">Status{{ sortIcon('status') }}</th>
                <th @click="toggleSort('updated_at')">Updated{{ sortIcon('updated_at') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in filtered" :key="r.id">
                <td class="max-w-xs truncate" :title="r.title">{{ r.title }}</td>
                <td>{{ r.severity }}</td>
                <td class="text-right tabular-nums">{{ r.likelihood }}</td>
                <td>
                  <span class="score-bar">
                    <span class="score-track">
                      <span class="score-fill"
                            :class="scoreBand(r.score)"
                            :style="{ width: Math.min(100, (r.score / 25) * 100) + '%' }"></span>
                    </span>
                    <span class="tabular-nums font-semibold">{{ r.score }}</span>
                  </span>
                </td>
                <td><span :class="statusClass(r.status)">{{ r.status }}</span></td>
                <td class="font-mono text-xs">{{ (r.updated_at || '').substring(0, 10) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
};

// ── ReviewsScreen ──────────────────────────────────────────────────────────
const ReviewsScreen = {
  props: ['data', 'loading', 'error'],
  setup(props) {
    const filterVerdict = ref('');
    const selectedReview = ref(null);

    const filtered = computed(() => {
      const rows = props.data?.reviews ?? [];
      return filterVerdict.value ? rows.filter(r => r.verdict === filterVerdict.value) : rows;
    });

    function verdictClass(v) {
      if (!v) return '';
      if (v === 'pass') return 'verdict-pass';
      if (v.includes('comment')) return 'verdict-partial';
      return 'verdict-fail';
    }

    return {
      filterVerdict, filtered, selectedReview,
      openReview(r) { selectedReview.value = r; },
      closeReview() { selectedReview.value = null; },
      verdictClass,
    };
  },
  template: `
    <div>
      <div class="page-header">
        <div>
          <h1 class="page-title">Reviews</h1>
          <div class="page-subtitle">Rubric verdicts from completed review jobs.</div>
        </div>
      </div>

      <div v-if="loading && !data" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="card notice-error">{{ error }}</div>
      <div v-else>
        <div class="filter-bar">
          <select class="filter-select" v-model="filterVerdict" aria-label="Filter by verdict">
            <option value="">All verdicts</option>
            <option value="pass">Pass</option>
            <option value="pass_with_comments">Pass with comments</option>
            <option value="fail">Fail</option>
          </select>
          <span class="result-count">{{ filtered.length }} reviews</span>
        </div>

        <div v-if="!filtered.length" class="card">
          <div class="empty-state">
            <span class="empty-state-icon" aria-hidden="true">✓</span>
            <div class="empty-state-title">No completed reviews</div>
            <p class="text-sm">Run <code>hermes review --wait</code> to produce one.</p>
          </div>
        </div>
        <div v-else class="card card-flush overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Rubric</th>
                <th>Verdict</th>
                <th class="text-right">Blockers</th>
                <th class="text-right">Majors</th>
                <th class="text-right">Minors</th>
                <th>Deliverable</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in filtered" :key="r.job_id" class="is-clickable" @click="openReview(r)">
                <td class="font-mono text-xs">{{ r.job_id.substring(0, 12) }}&hellip;</td>
                <td>{{ r.rubric_id }}</td>
                <td><span :class="verdictClass(r.verdict)">{{ r.verdict }}</span></td>
                <td class="text-right tabular-nums" :class="r.blockers > 0 ? 'text-red-500 font-bold' : ''">{{ r.blockers }}</td>
                <td class="text-right tabular-nums" :class="r.majors > 0 ? 'text-orange-500 font-semibold' : ''">{{ r.majors }}</td>
                <td class="text-right tabular-nums">{{ r.minors }}</td>
                <td class="font-mono text-xs">{{ r.deliverable }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Review detail -->
        <div v-if="selectedReview" class="modal-overlay" @click.self="closeReview"
             role="dialog" aria-modal="true" aria-label="Review detail">
          <div class="modal-box" style="max-width:460px">
            <div class="flex justify-between items-center mb-4">
              <h3 class="modal-title">Review detail</h3>
              <button class="modal-close" @click="closeReview" aria-label="Close">&times;</button>
            </div>
            <table class="text-sm w-full">
              <tbody>
                <tr><td class="text-gray-400 pr-4 py-1.5 w-28">Job ID</td><td class="font-mono text-xs break-all">{{ selectedReview.job_id }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Rubric</td><td>{{ selectedReview.rubric_id }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Verdict</td>
                    <td><span :class="verdictClass(selectedReview.verdict)">{{ selectedReview.verdict }}</span></td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Blockers</td>
                    <td :class="selectedReview.blockers > 0 ? 'text-red-500 font-bold' : ''">{{ selectedReview.blockers }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Majors</td>
                    <td :class="selectedReview.majors > 0 ? 'text-orange-500' : ''">{{ selectedReview.majors }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Minors</td><td>{{ selectedReview.minors }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Deliverable</td><td class="font-mono text-xs break-all">{{ selectedReview.deliverable }}</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `,
};

global.OverviewScreen = OverviewScreen;
global.ProjectListScreen = ProjectListScreen;
global.ProjectDetailScreen = ProjectDetailScreen;
global.PendenzenScreen = PendenzenScreen;
global.RisksScreen = RisksScreen;
global.ReviewsScreen = ReviewsScreen;
global.TimelineTab = TimelineTab;
global.KanbanTab = KanbanTab;
}(window));
