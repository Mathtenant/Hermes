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
        && (props.counts?.tasks ?? 0) === 0
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
        <!-- Headline: one hero figure — the open work a lead actually acts
             on — with the remaining counts as secondary tiles. Each is a
             shortcut into its screen. -->
        <div class="overview-head">
          <button class="hero-tile" @click="$emit('navigate', 'pendenzen')">
            <span class="hero-label">Open pendenzen</span>
            <span class="hero-value">{{ openPendenzen.length }}</span>
            <span class="hero-hint" :class="{ 'is-alert': blockers.length > 0 }">
              <template v-if="blockers.length">
                {{ blockers.length }} blocker<template v-if="blockers.length !== 1">s</template>
              </template>
              <template v-else-if="counts.pendenzen">nothing blocking</template>
              <template v-else>no pendenzen recorded</template>
            </span>
          </button>

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

            <button class="stat-tile" @click="$emit('navigate', 'detail')">
              <span class="stat-label">Arbeitspakete</span>
              <span class="stat-value" data-testid="tasks-count">{{ counts.tasks }}</span>
              <span class="stat-hint">Strukturplan &amp; Kanban</span>
            </button>

            <button class="stat-tile" @click="$emit('navigate', 'risks')">
              <span class="stat-label">Risks</span>
              <span class="stat-value" data-testid="risks-count">{{ counts.risks }}</span>
              <span class="stat-hint">{{ openRisks.length }} open</span>
            </button>

            <button class="stat-tile" @click="$emit('navigate', 'reviews')">
              <span class="stat-label">Reviews</span>
              <span class="stat-value">{{ counts.reviews }}</span>
              <span class="stat-hint">Rubric verdicts</span>
            </button>

            <button class="stat-tile" @click="$emit('navigate', 'pendenzen')">
              <span class="stat-label">Pendenzen total</span>
              <span class="stat-value">{{ counts.pendenzen }}</span>
              <span class="stat-hint">
                {{ counts.pendenzen - openPendenzen.length }} closed
              </span>
            </button>
          </div>
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
                <span class="text-xs score-value">{{ r.score }}</span>
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

        <div class="card card-flush table-scroll">
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
  emits: ['changed'],
  setup(props, { emit }) {
    const selectedCard = ref(null);
    const busyId = ref(null);
    const moveError = ref('');

    // Cards arrive grouped by column and carry no status of their own, so the
    // column they were opened from is what tells us where they currently sit.
    function openCard(card, status) {
      selectedCard.value = { ...card, status };
    }

    async function setStatus(card, status) {
      if (!card || card.status === status || busyId.value) return;
      busyId.value = card.id;
      moveError.value = '';
      try {
        const resp = await fetch(
          `/api/tasks/${encodeURIComponent(card.id)}/status`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status }),
          }
        );
        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}));
          throw new Error(detail.detail || `Server returned ${resp.status}`);
        }
        if (selectedCard.value?.id === card.id) selectedCard.value = null;
        // The board is derived server-side (a card's column *is* its status),
        // so re-fetch rather than moving the card locally and risking a view
        // that disagrees with the database.
        emit('changed');
      } catch (err) {
        moveError.value = String(err.message || err);
      } finally {
        busyId.value = null;
      }
    }

    const STATUS_LABELS = { open: 'To Do', blocked: 'Blocked', closed: 'Done' };

    return {
      selectedCard, busyId, moveError, openCard, setStatus,
      statusLabel: (s) => STATUS_LABELS[s] ?? s,
      closeCard() { selectedCard.value = null; },
    };
  },
  template: `
    <div>
      <div v-if="moveError" class="notice notice-error mb-3">{{ moveError }}</div>
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
          <div class="kanban-cards">
            <div v-for="card in col.cards"
                 :key="card.id"
                 class="kanban-card"
                 :class="[card.priority ? 'prio-' + card.priority : '',
                          busyId === card.id ? 'is-busy' : '']"
                 tabindex="0"
                 @click="openCard(card, col.status)"
                 @keydown.enter="openCard(card, col.status)">
              <div class="kanban-card-row">
                <!-- Done toggle. Stops propagation so ticking a card off does
                     not also open its detail modal. -->
                <button
                  class="card-check"
                  :class="{ 'is-done': col.status === 'closed' }"
                  :disabled="busyId === card.id"
                  :aria-label="col.status === 'closed'
                    ? 'Reopen ' + card.title : 'Mark ' + card.title + ' done'"
                  :title="col.status === 'closed' ? 'Reopen' : 'Mark done'"
                  @click.stop="setStatus({ ...card, status: col.status },
                                         col.status === 'closed' ? 'open' : 'closed')"
                >
                  <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                    <path d="M4 8.5l2.5 2.5L12 5.5" />
                  </svg>
                </button>
                <div class="kanban-card-title" :title="card.title">
                  <span v-if="card.wbs_number" class="kanban-card-wbs">{{ card.wbs_number }}</span>{{ card.title }}
                </div>
              </div>
              <div v-if="card.owner || card.priority" class="kanban-card-meta">
                <span v-if="card.owner" class="truncate">{{ card.owner }}</span>
                <span v-if="card.priority" class="ml-auto shrink-0">{{ card.priority }}</span>
              </div>
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

          <div class="modal-status">
            <span class="stat-label mb-3" style="display:block">Status</span>
            <div class="segmented" role="group" aria-label="Task status">
              <button v-for="s in ['open', 'blocked', 'closed']"
                      :key="s"
                      :class="{ active: selectedCard.status === s }"
                      :disabled="busyId === selectedCard.id"
                      :aria-pressed="String(selectedCard.status === s)"
                      @click="setStatus(selectedCard, s)">
                {{ statusLabel(s) }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
};

// ── ProjectDetailScreen ────────────────────────────────────────────────────
// WbsTab / WbsNodeItem are registered globally in app.js.
const ProjectDetailScreen = {
  props: ['data', 'loading', 'error', 'projectId'],
  emits: ['back', 'changed'],
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
          <kanban-tab v-else-if="activeTab === 'kanban'" :columns="data?.kanban ?? []"
                      @changed="$emit('changed')" />
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
      const map = { open: 'chip-open', closed: 'chip-closed', blocked: 'chip-blocked' };
      return `chip ${map[s] ?? 'chip-open'}`;
    }

    function statusMark(s) {
      const map = { open: 'mark-ring', closed: 'mark-dot', blocked: 'mark-square' };
      return map[s] ?? 'mark-ring';
    }

    function resetFilters() {
      query.value = '';
      filterSource.value = '';
      filterPriority.value = '';
      filterStatus.value = '';
    }

    // ── Beschlüsse ───────────────────────────────────────────────────────
    // Same source document as the Pendenzen, so the same screen — a decision
    // and the actions it set in motion are read together or not at all.
    const activeTab = ref('pendenzen');

    const DECISION_STATUS = {
      beschlossen: { label: 'Beschlossen', cls: 'chip-open',    mark: 'mark-ring' },
      umgesetzt:   { label: 'Umgesetzt',   cls: 'chip-closed',  mark: 'mark-dot' },
      aufgehoben:  { label: 'Aufgehoben',  cls: 'chip-blocked', mark: 'mark-square' },
      vertagt:     { label: 'Vertagt',     cls: 'chip-mitigated', mark: 'mark-bar' },
    };

    const decisionQuery = ref('');

    const decisions = computed(() => {
      const q = decisionQuery.value.trim().toLowerCase();
      const rows = props.data?.decisions ?? [];
      if (!q) return rows;
      return rows.filter(
        d => String(d.title ?? '').toLowerCase().includes(q)
          || String(d.decided_by ?? '').toLowerCase().includes(q)
          || String(d.affects ?? '').toLowerCase().includes(q)
      );
    });

    const openFollowUps = computed(
      () => (props.data?.decisions ?? []).reduce((n, d) => n + d.pendenzen_open, 0)
    );

    function fmtDate(iso) {
      if (!iso) return '—';
      const [y, m, d] = iso.split('-');
      return `${d}.${m}.${y}`;
    }

    return {
      query, filterSource, filterPriority, filterStatus, sources, statuses,
      filtered, toggleSort, sortIcon, statusBadgeClass, statusMark, resetFilters,
      activeTab, decisions, decisionQuery, openFollowUps, fmtDate,
      decisionLabel: (s) => (DECISION_STATUS[s] || {}).label || s,
      decisionClass: (s) => (DECISION_STATUS[s] || {}).cls || 'chip-open',
      decisionMark: (s) => (DECISION_STATUS[s] || {}).mark || 'mark-ring',
    };
  },
  template: `
    <div>
      <div class="page-header">
        <div>
          <h1 class="page-title">Pendenzen &amp; Beschlüsse</h1>
          <div class="page-subtitle">
            Offene Punkte aus Sitzungen und Reviews, und die Entscheide, aus
            denen sie folgen.
          </div>
        </div>
      </div>

      <div v-if="loading && !data" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="card notice-error">{{ error }}</div>
      <div v-else>
        <div class="tab-bar">
          <button class="tab-btn" :class="{ active: activeTab === 'pendenzen' }"
                  @click="activeTab = 'pendenzen'" data-testid="tab-pendenzen">
            Pendenzen ({{ data?.pendenzen?.length ?? 0 }})
          </button>
          <button class="tab-btn" :class="{ active: activeTab === 'beschluesse' }"
                  @click="activeTab = 'beschluesse'" data-testid="tab-beschluesse">
            Beschlüsse ({{ data?.decisions?.length ?? 0 }})
          </button>
        </div>

      <!-- ── Beschlüsse ────────────────────────────────────────────────── -->
      <div v-if="activeTab === 'beschluesse'">
        <div v-if="!(data?.decisions ?? []).length" class="card">
          <div class="empty-state">
            <span class="empty-state-icon" aria-hidden="true">◵</span>
            <div class="empty-state-title">Keine Beschlüsse importiert</div>
            <p class="text-sm">
              Importiere die <code>Pendenzen- und Beschlussliste</code> über
              <strong>Import JSON → Pendenzen &amp; Beschlüsse</strong>.
            </p>
          </div>
        </div>
        <template v-else>
          <div class="filter-bar">
            <input class="text-input" type="search" v-model="decisionQuery"
                   placeholder="Beschluss, Gremium oder Bereich…"
                   aria-label="Beschlüsse durchsuchen">
            <span class="result-count">
              {{ decisions.length }} Beschlüsse · {{ openFollowUps }} offene Pendenzen daraus
            </span>
          </div>

          <!-- One row per decision: what was decided, by whom, when, and what
               it still owes. The follow-up count is the reason the two lists
               belong on one screen. -->
          <ol class="decision-list">
            <li v-for="d in decisions" :key="d.id" class="decision-item">
              <div class="decision-date">
                <span class="decision-day">{{ fmtDate(d.decided_on) }}</span>
              </div>
              <div class="decision-body">
                <div class="decision-head">
                  <span class="decision-title">{{ d.title }}</span>
                  <span class="chip shrink-0" :class="decisionClass(d.decision_status)">
                    <span class="chip-mark" :class="decisionMark(d.decision_status)"
                          aria-hidden="true"></span>
                    {{ decisionLabel(d.decision_status) }}
                  </span>
                </div>
                <div class="decision-meta">
                  <span v-if="d.decided_by">{{ d.decided_by }}</span>
                  <span v-if="d.affects" class="decision-affects">{{ d.affects }}</span>
                  <span v-if="d.pendenzen_total" class="decision-followups"
                        :class="{ 'is-alert': d.pendenzen_open > 0 }">
                    {{ d.pendenzen_open }} von {{ d.pendenzen_total }} Pendenzen offen
                  </span>
                  <span v-else class="text-gray-400">keine Pendenzen</span>
                </div>
              </div>
            </li>
          </ol>
        </template>
      </div>

      <!-- ── Pendenzen ─────────────────────────────────────────────────── -->
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
        <div v-else class="card card-flush table-scroll">
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
                <td class="text-gray-400">{{ r.source }}</td>
                <td>
                  <span class="inline-flex items-center gap-2">
                    <span :class="['prio-dot', r.priority]"></span>{{ r.priority }}
                  </span>
                </td>
                <td>
                  <span :class="statusBadgeClass(r.status)">
                    <span class="chip-mark" :class="statusMark(r.status)" aria-hidden="true"></span>
                    {{ r.status }}
                  </span>
                </td>
                <td class="text-gray-400">{{ r.owner || '—' }}</td>
                <td class="font-mono text-xs">{{ r.due_date || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
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

    // Each status gets its own silhouette as well as its own fill, so the
    // state is still readable in greyscale, in print, and to a reader who
    // cannot separate the hues.
    function statusMark(s) {
      const map = {
        open: 'mark-ring',
        mitigated: 'mark-square',
        accepted: 'mark-bar',
        closed: 'mark-dot',
      };
      return map[s] ?? 'mark-dot';
    }

    function scoreBand(score) {
      if (score >= 15) return 'critical';
      if (score >= 9) return 'high';
      if (score >= 4) return 'medium';
      return 'low';
    }

    // Severity arrives as free text; map the words we know onto the same
    // sequential scale the score meter uses, and fall back to the lightest
    // step for anything unrecognised rather than inventing a level.
    function severityBand(severity) {
      const s = String(severity ?? '').toLowerCase();
      if (s.startsWith('crit') || s.startsWith('block')) return 'critical';
      if (s.startsWith('high') || s.startsWith('hoch')) return 'high';
      if (s.startsWith('med') || s.startsWith('mit')) return 'medium';
      return 'low';
    }

    return {
      query, filterStatus, filtered, openCount, toggleSort, sortIcon,
      statusMark, scoreBand, severityBand,
    };
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
        <div v-else class="card card-flush table-scroll">
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
                <td>
                  <span class="sev">
                    <span class="sev-dot" :class="severityBand(r.severity)" aria-hidden="true"></span>
                    {{ r.severity }}
                  </span>
                </td>
                <td class="text-right tabular-nums">{{ r.likelihood }}</td>
                <td>
                  <span class="score-bar">
                    <span class="score-track">
                      <span class="score-fill"
                            :class="scoreBand(r.score)"
                            :style="{ width: Math.min(100, (r.score / 25) * 100) + '%' }"></span>
                    </span>
                    <span class="score-value">{{ r.score }}</span>
                  </span>
                </td>
                <td>
                  <span class="chip" :class="'chip-' + r.status">
                    <span class="chip-mark" :class="statusMark(r.status)" aria-hidden="true"></span>
                    {{ r.status }}
                  </span>
                </td>
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
        <div v-else class="card card-flush table-scroll">
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

// ── AblaufplanScreen ───────────────────────────────────────────────────────
// The Projektablaufplan_Detail as a bar chart. Unlike the Timeline tab — which
// plots points, one per due date — every activity here carries a real span, so
// the question "what overlaps what, and what is late" is answerable at a
// glance instead of by reading dates off a list.
const AblaufplanScreen = {
  props: ['data', 'loading', 'error'],
  setup(props) {
    const filterPhase = ref('');
    const filterStatus = ref('');
    const asTable = ref(false);
    const hovered = ref(null);

    const DAY_MS = 86400000;
    const MONTHS_DE = [
      'Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
      'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez',
    ];

    // Status is a state, so it gets a label and a legend entry, never colour
    // alone. Only `erledigt` and `blockiert` take a status hue — those are the
    // two that genuinely mean good and bad. "In flight" and "not started" are
    // neither, so they take the accent and a neutral instead of borrowing a
    // reserved colour to mean something it does not mean.
    const STATUS = {
      erledigt:  { label: 'Erledigt',  cls: 'is-done' },
      laufend:   { label: 'Laufend',   cls: 'is-running' },
      offen:     { label: 'Offen',     cls: 'is-open' },
      blockiert: { label: 'Blockiert', cls: 'is-blocked' },
    };
    const STATUS_ORDER = ['laufend', 'offen', 'blockiert', 'erledigt'];

    const rows = computed(() => props.data?.ablaufplan ?? []);

    const phases = computed(() => {
      const seen = [];
      for (const r of rows.value) {
        const name = r.phase || 'Ohne Phase';
        if (!seen.includes(name)) seen.push(name);
      }
      return seen;
    });

    const filtered = computed(() => rows.value.filter(
      r => (!filterPhase.value || (r.phase || 'Ohne Phase') === filterPhase.value)
        && (!filterStatus.value || r.status === filterStatus.value)
    ));

    // Group the filtered rows under their phase, preserving phase order.
    const groups = computed(() => {
      const byPhase = new Map();
      for (const r of filtered.value) {
        const name = r.phase || 'Ohne Phase';
        if (!byPhase.has(name)) byPhase.set(name, []);
        byPhase.get(name).push(r);
      }
      return [...byPhase.entries()].map(([name, items]) => ({ name, items }));
    });

    function toMs(iso) {
      const t = Date.parse(iso + 'T00:00:00Z');
      return Number.isNaN(t) ? null : t;
    }

    // The time axis every bar is positioned against. Padded by a few days so a
    // bar that starts on the first day of the plan is not flush against the
    // frame, and floored to a non-zero span so a single-day plan cannot divide
    // by zero.
    const domain = computed(() => {
      const points = [];
      for (const r of filtered.value) {
        const s = toMs(r.start || r.end);
        const e = toMs(r.end);
        if (s !== null) points.push(s);
        if (e !== null) points.push(e);
      }
      if (!points.length) return null;
      const pad = 3 * DAY_MS;
      const min = Math.min(...points) - pad;
      const max = Math.max(...points) + pad;
      return { min, max, span: Math.max(max - min, DAY_MS) };
    });

    function pct(ms) {
      const d = domain.value;
      if (!d || ms === null) return 0;
      return ((ms - d.min) / d.span) * 100;
    }

    // Month boundaries for the scale header and the background gridlines.
    const ticks = computed(() => {
      const d = domain.value;
      if (!d) return [];
      const out = [];
      const cur = new Date(d.min);
      cur.setUTCDate(1);
      cur.setUTCHours(0, 0, 0, 0);
      // Bounded rather than while(true): a corrupt date can otherwise spin
      // here forever and take the whole page with it.
      for (let i = 0; i < 240; i++) {
        const ms = cur.getTime();
        if (ms > d.max) break;
        if (ms >= d.min) {
          out.push({
            left: pct(ms),
            label: MONTHS_DE[cur.getUTCMonth()],
            year: cur.getUTCFullYear(),
            isYearStart: cur.getUTCMonth() === 0,
          });
        }
        cur.setUTCMonth(cur.getUTCMonth() + 1);
      }
      return out;
    });

    const todayLeft = computed(() => {
      const d = domain.value;
      if (!d) return null;
      const now = Date.parse(new Date().toISOString().slice(0, 10) + 'T00:00:00Z');
      if (now < d.min || now > d.max) return null;  // outside the plan — no marker
      return pct(now);
    });

    function barStyle(r) {
      const s = toMs(r.start || r.end);
      const e = toMs(r.end);
      if (s === null || e === null) return { display: 'none' };
      const left = pct(s);
      // +1 day so a task that starts and ends on the same date still shows a
      // bar rather than a hairline.
      const right = pct(e + DAY_MS);
      return { left: left + '%', width: Math.max(right - left, 0.6) + '%' };
    }

    function milestoneStyle(r) {
      const e = toMs(r.end);
      return e === null ? { display: 'none' } : { left: pct(e) + '%' };
    }

    function fmt(iso) {
      if (!iso) return '—';
      const [y, m, d] = iso.split('-');
      return `${d}.${m}.${y}`;
    }

    function duration(r) {
      const s = toMs(r.start);
      const e = toMs(r.end);
      if (s === null || e === null) return '';
      return Math.round((e - s) / DAY_MS) + 1 + ' Tage';
    }

    // A plan's own status is authoritative; "late" is a separate fact derived
    // from the calendar, so an overdue task reads as late *and* still open
    // rather than being silently recoloured.
    function isLate(r) {
      const today = new Date().toISOString().slice(0, 10);
      return r.status !== 'erledigt' && r.end < today;
    }

    const lateCount = computed(() => filtered.value.filter(isLate).length);

    const nextMilestone = computed(() => {
      const today = new Date().toISOString().slice(0, 10);
      return rows.value
        .filter(r => r.kind === 'meilenstein' && r.status !== 'erledigt' && r.end >= today)
        .sort((a, b) => a.end.localeCompare(b.end))[0] || null;
    });

    const daysToNext = computed(() => {
      if (!nextMilestone.value) return null;
      const now = Date.parse(new Date().toISOString().slice(0, 10) + 'T00:00:00Z');
      return Math.round((toMs(nextMilestone.value.end) - now) / DAY_MS);
    });

    const statusCounts = computed(() => {
      const out = {};
      for (const k of STATUS_ORDER) out[k] = 0;
      for (const r of filtered.value) {
        if (out[r.status] !== undefined) out[r.status] += 1;
      }
      return out;
    });

    return {
      filterPhase, filterStatus, asTable, hovered, rows, phases, filtered,
      groups, ticks, todayLeft, barStyle, milestoneStyle, fmt, duration,
      isLate, lateCount, nextMilestone, daysToNext, statusCounts,
      STATUS, STATUS_ORDER,
      statusLabel: (s) => (STATUS[s] || {}).label || s,
      statusClass: (s) => (STATUS[s] || {}).cls || 'is-open',
      resetFilters() { filterPhase.value = ''; filterStatus.value = ''; },
    };
  },
  template: `
    <div>
      <div class="page-header">
        <div>
          <h1 class="page-title">Ablaufplan</h1>
          <div class="page-subtitle">
            Projektablaufplan Detail — Phasen, Vorgänge und Meilensteine als Balkenplan.
          </div>
        </div>
      </div>

      <div v-if="loading && !data" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="card notice-error">{{ error }}</div>

      <div v-else-if="!rows.length" class="card">
        <div class="empty-state">
          <span class="empty-state-icon" aria-hidden="true">◵</span>
          <div class="empty-state-title">Kein Ablaufplan importiert</div>
          <p class="text-sm">
            Importiere den <code>Projektablaufplan_Detail</code> über
            <strong>Import JSON → Ablaufplan</strong>.
          </p>
        </div>
      </div>

      <template v-else>
        <!-- One hero figure: the next gate, and how long there is left. -->
        <div class="overview-head">
          <div class="hero-tile" style="cursor:default">
            <span class="hero-label">
              {{ nextMilestone ? 'Bis zum nächsten Meilenstein' : 'Meilensteine' }}
            </span>
            <span class="hero-value" v-if="daysToNext !== null">{{ daysToNext }}</span>
            <span class="hero-value" v-else>—</span>
            <span class="hero-hint" v-if="nextMilestone">
              Tage · {{ nextMilestone.title }} am {{ fmt(nextMilestone.end) }}
            </span>
            <span class="hero-hint" v-else>keine offenen Meilensteine</span>
          </div>

          <div class="stat-grid" style="grid-template-columns:repeat(2,1fr)">
            <div class="stat-tile" style="cursor:default">
              <span class="stat-label">Vorgänge</span>
              <span class="stat-value">{{ filtered.length }}</span>
              <span class="stat-hint">in {{ phases.length }} Phasen</span>
            </div>
            <div class="stat-tile" style="cursor:default">
              <span class="stat-label">Terminlage</span>
              <span class="stat-value">{{ lateCount }}</span>
              <span class="stat-hint" :class="{ 'is-alert': lateCount > 0 }">
                {{ lateCount === 1 ? 'Vorgang überfällig' : 'Vorgänge überfällig' }}
              </span>
            </div>
            <div v-for="s in STATUS_ORDER" :key="s"
                 class="stat-tile" style="cursor:default; grid-column: span 1">
              <span class="stat-label">{{ statusLabel(s) }}</span>
              <span class="stat-value">{{ statusCounts[s] }}</span>
            </div>
          </div>
        </div>

        <div class="filter-bar">
          <select class="filter-select" v-model="filterPhase" aria-label="Phase filtern">
            <option value="">Alle Phasen</option>
            <option v-for="p in phases" :key="p" :value="p">{{ p }}</option>
          </select>
          <select class="filter-select" v-model="filterStatus" aria-label="Status filtern">
            <option value="">Alle Status</option>
            <option v-for="s in STATUS_ORDER" :key="s" :value="s">{{ statusLabel(s) }}</option>
          </select>
          <button v-if="filterPhase || filterStatus" class="btn btn-ghost" @click="resetFilters">
            Filter zurücksetzen
          </button>
          <!-- The table view is the accessible equal of the chart, not a
               fallback: every value the bars encode is readable as text. -->
          <div class="segmented ml-auto" role="group" aria-label="Darstellung">
            <button :class="{ active: !asTable }" @click="asTable = false">Balkenplan</button>
            <button :class="{ active: asTable }" @click="asTable = true">Tabelle</button>
          </div>
        </div>

        <!-- Legend — identity never rests on colour alone. -->
        <div class="gantt-legend" v-if="!asTable">
          <span v-for="s in STATUS_ORDER" :key="s" class="gantt-legend-item">
            <span class="gantt-key" :class="statusClass(s)" aria-hidden="true"></span>
            {{ statusLabel(s) }}
          </span>
          <span class="gantt-legend-item">
            <span class="gantt-key is-milestone" aria-hidden="true"></span>
            Meilenstein
          </span>
          <span class="gantt-legend-item">
            <span class="gantt-key is-today" aria-hidden="true"></span>
            Heute
          </span>
        </div>

        <!-- ── Balkenplan ────────────────────────────────────────────── -->
        <div v-if="!asTable" class="card card-flush gantt-scroll">
          <div class="gantt">
            <div class="gantt-head">
              <div class="gantt-label-col">Vorgang</div>
              <div class="gantt-track-col">
                <span v-for="(t, i) in ticks" :key="i"
                      class="gantt-tick-label" :style="{ left: t.left + '%' }">
                  {{ t.label }}<template v-if="t.isYearStart"> {{ t.year }}</template>
                </span>
              </div>
            </div>

            <div v-for="g in groups" :key="g.name" class="gantt-group">
              <div class="gantt-phase">
                <div class="gantt-label-col">{{ g.name }}</div>
                <div class="gantt-track-col"></div>
              </div>

              <div v-for="r in g.items" :key="r.id"
                   class="gantt-row"
                   @mouseenter="hovered = r.id" @mouseleave="hovered = null">
                <div class="gantt-label-col" :title="r.title">
                  <span class="gantt-row-title">{{ r.title }}</span>
                  <span v-if="r.owner" class="gantt-row-owner">{{ r.owner }}</span>
                </div>
                <div class="gantt-track-col">
                  <span v-for="(t, i) in ticks" :key="'g' + i"
                        class="gantt-grid" :style="{ left: t.left + '%' }"></span>

                  <template v-if="r.kind === 'meilenstein'">
                    <span class="gantt-milestone"
                          :class="[statusClass(r.status), { 'is-late': isLate(r) }]"
                          :style="milestoneStyle(r)"
                          :aria-label="r.title + ' — Meilenstein am ' + fmt(r.end)"></span>
                  </template>
                  <template v-else>
                    <span class="gantt-bar"
                          :class="[statusClass(r.status), { 'is-late': isLate(r) }]"
                          :style="barStyle(r)"
                          :aria-label="r.title + ' — ' + fmt(r.start) + ' bis ' + fmt(r.end)">
                      <span v-if="r.progress_pct !== null && r.progress_pct !== undefined"
                            class="gantt-progress"
                            :style="{ width: r.progress_pct + '%' }"></span>
                    </span>
                  </template>

                  <span v-if="hovered === r.id" class="gantt-tip"
                        :style="{ left: barStyle(r).left }">
                    <strong>{{ r.title }}</strong>
                    <span>{{ statusLabel(r.status) }}<template v-if="isLate(r)"> · überfällig</template></span>
                    <span v-if="r.kind === 'meilenstein'">{{ fmt(r.end) }}</span>
                    <span v-else>{{ fmt(r.start) }} – {{ fmt(r.end) }} · {{ duration(r) }}</span>
                    <span v-if="r.owner">{{ r.owner }}</span>
                    <span v-if="r.progress_pct !== null && r.progress_pct !== undefined">
                      {{ r.progress_pct }}% erledigt
                    </span>
                  </span>
                </div>
              </div>
            </div>

            <span v-if="todayLeft !== null" class="gantt-today"
                  :style="{ left: 'calc(var(--gantt-label-w) + ' + todayLeft + '% * var(--gantt-track-f))' }"
                  aria-hidden="true"></span>
          </div>
        </div>

        <!-- ── Tabelle ───────────────────────────────────────────────── -->
        <div v-else class="card card-flush table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>Phase</th><th>Vorgang</th><th>Art</th>
                <th>Start</th><th>Ende</th><th>Verantwortlich</th>
                <th>Status</th><th class="text-right">Fortschritt</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in filtered" :key="r.id">
                <td class="text-gray-400">{{ r.phase || '—' }}</td>
                <td class="max-w-xs truncate" :title="r.title">{{ r.title }}</td>
                <td class="text-gray-400">{{ r.kind === 'meilenstein' ? 'Meilenstein' : 'Vorgang' }}</td>
                <td class="font-mono text-xs">{{ fmt(r.start) }}</td>
                <td class="font-mono text-xs">
                  {{ fmt(r.end) }}
                  <span v-if="isLate(r)" class="gantt-late-tag">überfällig</span>
                </td>
                <td class="text-gray-400">{{ r.owner || '—' }}</td>
                <td>
                  <span class="chip" :class="'chip-plan-' + r.status">
                    <span class="chip-mark" :class="statusClass(r.status)" aria-hidden="true"></span>
                    {{ statusLabel(r.status) }}
                  </span>
                </td>
                <td class="text-right">
                  <span v-if="r.progress_pct !== null && r.progress_pct !== undefined"
                        class="score-bar">
                    <span class="score-track">
                      <span class="score-fill high" :style="{ width: r.progress_pct + '%' }"></span>
                    </span>
                    <span class="score-value">{{ r.progress_pct }}</span>
                  </span>
                  <span v-else class="text-gray-400">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  `,
};

global.AblaufplanScreen = AblaufplanScreen;
global.OverviewScreen = OverviewScreen;
global.ProjectListScreen = ProjectListScreen;
global.ProjectDetailScreen = ProjectDetailScreen;
global.PendenzenScreen = PendenzenScreen;
global.RisksScreen = RisksScreen;
global.ReviewsScreen = ReviewsScreen;
global.TimelineTab = TimelineTab;
global.KanbanTab = KanbanTab;
}(window));
