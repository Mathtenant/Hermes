/* HERMES Dashboard — Screen components.
 * Loaded after components.js and before app.js.
 *
 * Wrapped in an IIFE (and exported on `window`) because classic <script> tags
 * share one global lexical scope — see the note at the top of components.js.
 */
/* global Vue */
(function (global) {
'use strict';

const { ref, computed, nextTick, onMounted, watch } = Vue;

// Shared: rank used wherever priorities are ordered.
const PRIO_RANK = { blocker: 0, high: 1, medium: 2, low: 3 };

// Plain sentinel rather than a control character: it travels through a
// checkbox value, a test fixture and a URL without anyone having to escape
// it, and no real role or name looks like this.
const UNASSIGNED = '__ohne__';

/** Multi-select owner filter, shared by the timeline and the list.
 *
 * Both screens ask the same question ("whose work is this?") and used to
 * answer it with a single-value select each — so "Meier and Brunner" took two
 * passes. One factory keeps the selection semantics identical in both places
 * rather than letting two copies drift.
 */
function createOwnerFilter() {
  const selected = ref([]);

  function toggleOwner(name) {
    const next = [...selected.value];
    const at = next.indexOf(name);
    if (at >= 0) next.splice(at, 1);
    else next.push(name);
    selected.value = next;
  }

  function clearOwners() {
    selected.value = [];
  }

  /** An empty selection means "everyone", not "nobody": the filter is off. */
  function matchesOwner(owner) {
    if (!selected.value.length) return true;
    if (selected.value.includes(UNASSIGNED) && !owner) return true;
    return selected.value.includes(owner);
  }

  const ownerLabel = computed(() => {
    const picked = selected.value;
    if (!picked.length) return 'Alle Verantwortlichen';
    if (picked.length === 1) {
      return picked[0] === UNASSIGNED ? 'Ohne Verantwortliche' : picked[0];
    }
    return `${picked.length} Verantwortliche`;
  });

  return { selected, toggleOwner, clearOwners, matchesOwner, ownerLabel };
}

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
        <!-- One hero figure: the open work a lead actually acts on.

             The six tiles that used to sit beside it — Projects, Timeline
             items, Arbeitspakete, Risks, Reviews, Todos gesamt — were the
             sidebar's own count badges, restated. The sidebar is on screen at
             all times and is already the way to those screens, so the grid
             was a second navigation showing second copies of five numbers.
             What it uniquely held (the 22/98 split behind the "Timeline &
             WBS" badge, and how many todos are closed) moved into this tile's
             hint and the panels below, which say something the badges cannot:
             WHICH items need attention. -->
        <div class="overview-head is-single">
          <button class="hero-tile" @click="$emit('navigate', 'work')">
            <span class="hero-label">Offene Todos</span>
            <span class="hero-value">{{ openPendenzen.length }}</span>
            <span class="hero-hint" :class="{ 'is-alert': blockers.length > 0 }">
              <template v-if="blockers.length">
                {{ blockers.length }} blocker<template v-if="blockers.length !== 1">s</template>
              </template>
              <template v-else-if="counts.pendenzen">nichts blockiert</template>
              <template v-else>keine Todos erfasst</template>
              <!-- The closed count was the one thing the removed "Todos
                   gesamt" tile said that the sidebar badge does not. -->
              <template v-if="counts.pendenzen > openPendenzen.length">
                · {{ counts.pendenzen - openPendenzen.length }} erledigt
              </template>
            </span>
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
              <h2 class="text-base font-semibold">Braucht Aufmerksamkeit</h2>
              <button class="btn-link" @click="$emit('navigate', 'work')">Todos &rarr;</button>
            </div>
            <div v-if="!urgentPendenzen.length" class="text-sm text-gray-400 py-2">
              Keine offenen Todos.
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
  emits: ['select-project', 'delete-project'],
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
                <td class="text-right row-actions">
                  <!-- .stop: the whole row navigates, and deleting is not a
                       reason to also open what you just deleted. -->
                  <button class="icon-btn is-danger"
                          data-testid="delete-project"
                          :aria-label="'Projekt ' + p.project_id + ' löschen'"
                          :title="'Projekt ' + p.project_id + ' löschen'"
                          @click.stop="$emit('delete-project', p.project_id)"
                          @keydown.enter.stop
                          @keydown.space.stop>&times;</button>
                  <span class="text-gray-400" aria-hidden="true">&rsaquo;</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
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
  components: { KanbanTab },
  setup() {
    const activeTab = ref('kanban');
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
          <button class="tab-btn" :class="{ active: activeTab === 'kanban' }" @click="activeTab = 'kanban'">
            Kanban
          </button>
          <button class="tab-btn" :class="{ active: activeTab === 'wbs' }" @click="activeTab = 'wbs'">
            WBS ({{ data?.wbs?.length ?? 0 }})
          </button>
        </div>
        <div class="card">
          <kanban-tab v-if="activeTab === 'kanban'" :columns="data?.kanban ?? []"
                      @changed="$emit('changed')" />
          <wbs-tab v-else :nodes="data?.wbs ?? []" />
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
            <!-- This used to name a "hermes risk-add" command, which does not
                 exist. Risks currently enter only through a JSON import. -->
            <p class="text-sm">Import a JSON export to populate the risk register.</p>
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
  // `embedded` suppresses this screen's own page header when it is rendered
  // as a lens inside another screen.
  props: ['data', 'loading', 'error', 'embedded'],
  emits: ['changed'],
  setup(props, { emit }) {
    const filterPhase = ref('');
    const filterStatus = ref('');
    const filterLevel = ref('');
    const filterSource = ref('');
    // A cross-source sweep reaches years out — a contract date, a parked
    // item, a typo'd year. Fitting the axis to the full extent then crushes
    // everything real into a few pixels at one end, with no way back except
    // deleting data. The window is centred on today rather than starting
    // there, because the sweep deliberately includes what is already done.
    const filterWindow = ref('heute');
    const {
      selected: filterOwners, toggleOwner, clearOwners,
      matchesOwner: ownerMatches, ownerLabel,
    } = createOwnerFilter();

    // ── Zoom ────────────────────────────────────────────────────────────
    // Zoom is a TIME SCALE, not a magnification factor. The old control
    // scaled the track to 150% / 200% / 400% and left the axis labelled in
    // months at every step, so zooming in made the bars longer without ever
    // telling you which week you were looking at.
    //
    // Each scale sets both how much room a day gets AND how the axis is
    // labelled, so "hineinzoomen" means "Wochenansicht" the way a calendar
    // means it. Distinct from the time window, which changes *which rows*
    // are shown; zoom only changes how much room the same rows get.
    const SCALES = [
      { key: 'jahr',    label: 'Jahr',    pxPerDay: 1.2,  tick: 'year' },
      { key: 'quartal', label: 'Quartal', pxPerDay: 3,    tick: 'quarter' },
      { key: 'monat',   label: 'Monat',   pxPerDay: 8,    tick: 'month' },
      { key: 'woche',   label: 'Woche',   pxPerDay: 26,   tick: 'week' },
      { key: 'tag',     label: 'Tag',     pxPerDay: 70,   tick: 'day' },
    ];
    // Default to month: the whole point of the sweep is a project-length
    // view, and a week view of a two-year plan opens on a wall of scrolling.
    const scaleIndex = ref(SCALES.findIndex((s) => s.key === 'monat'));
    const scale = computed(() => SCALES[scaleIndex.value]);

    const editingOwner = ref(null);   // row id currently being edited
    const ownerDraft = ref('');
    const ownerError = ref('');
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

    // Altitude, for the cross-source sweep. A Go-Live and "check an invoice"
    // both belong in one dated list, but a lead needs to be able to collapse
    // to just the gates.
    const LEVELS = {
      meilenstein: 'Meilensteine',
      arbeitspaket: 'Arbeitspakete',
      aufgabe: 'Aufgaben',
    };
    const LEVEL_ORDER = ['meilenstein', 'arbeitspaket', 'aufgabe'];

    // months back, months forward
    // The default used to reach three months BACK, so a plan opened onto a
    // wall of finished work with today pushed off the right-hand edge — months
    // of green bars nobody needs to look at again.
    //
    // "Ab heute" is not "drop everything before today": an OVERDUE item is in
    // the past and is the most urgent thing on the board. Finished past work
    // is what is irrelevant, so the rule is by STATUS, not by date alone.
    const WINDOWS = {
      'heute': { label: 'Ab heute (12 Monate)', mode: 'forward', fwd: 12 },
      '12': { label: '15 Monate um heute', back: 3, fwd: 12 },
      '36': { label: '3 Jahre um heute', back: 12, fwd: 24 },
      'all': { label: 'Ganzer Zeitraum', back: null, fwd: null },
    };
    const WINDOW_ORDER = ['heute', '12', '36', 'all'];

    function windowBounds() {
      const w = WINDOWS[filterWindow.value];
      if (!w || w.mode === 'forward' || w.back === null) return null;
      const from = new Date();
      from.setUTCMonth(from.getUTCMonth() - w.back);
      const to = new Date();
      to.setUTCMonth(to.getUTCMonth() + w.fwd);
      return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
    }

    function inWindow(r) {
      const w = WINDOWS[filterWindow.value];
      if (w?.mode === 'forward') {
        const today = todayISO();
        const end = r.end || '';
        // Overdue stays, however far back it is dated: that is what overdue
        // MEANS, and hiding it would empty the screen of exactly the rows a
        // lead opens the plan to find.
        if (r.status !== 'erledigt' && end && end < today) return true;
        // Forward is still BOUNDED. Dropping the upper limit let a single
        // typo'd year (a 2099 date in the fixtures) stretch the axis 33 years
        // and squeeze every real bar into a few pixels — the exact failure the
        // window was introduced to prevent. Anything past the bound is counted
        // in outsideWindow and reachable via "Ganzer Zeitraum".
        const to = new Date();
        to.setUTCMonth(to.getUTCMonth() + w.fwd);
        const limit = to.toISOString().slice(0, 10);
        return end >= today && (r.start || end) <= limit;
      }
      const b = windowBounds();
      if (!b) return true;
      // An item overlaps the window if it has not ended before it starts and
      // does not begin after it ends — a long bar spanning the window counts.
      return (r.end >= b.from) && ((r.start || r.end) <= b.to);
    }

    /** Today as YYYY-MM-DD, for comparing against the ISO dates rows carry. */
    function todayISO() {
      return new Date().toISOString().slice(0, 10);
    }

    const rows = computed(() => props.data?.ablaufplan ?? []);

    const phases = computed(() => {
      const seen = [];
      for (const r of rows.value) {
        const name = r.phase || 'Ohne Phase';
        if (!seen.includes(name)) seen.push(name);
      }
      return seen;
    });

    // Which documents the dates came from. Only worth offering as a filter
    // once a sweep has actually pulled from more than one.
    const sources = computed(() => {
      const seen = [];
      for (const r of rows.value) {
        if (r.source_hint && !seen.includes(r.source_hint)) seen.push(r.source_hint);
      }
      return seen.sort();
    });

    // Everyone who owns at least one dated obligation. "Ohne" is a real
    // choice, not an omission: unassigned work is exactly what a lead hunts
    // for, so it gets its own entry rather than being invisible.
    const owners = computed(() => {
      const seen = [];
      for (const r of rows.value) {
        const name = r.owner || '';
        if (name && !seen.includes(name)) seen.push(name);
      }
      return seen.sort((a, b) => a.localeCompare(b));
    });


    function matchesOwner(r) {
      return ownerMatches(r.owner);
    }

    const filtered = computed(() => rows.value.filter(
      r => (!filterPhase.value || (r.phase || 'Ohne Phase') === filterPhase.value)
        && (!filterStatus.value || r.status === filterStatus.value)
        && (!filterLevel.value || r.level === filterLevel.value)
        && (!filterSource.value || r.source_hint === filterSource.value)
        && matchesOwner(r)
        && inWindow(r)
    ));

    // Never hide rows silently: whatever the window leaves out is counted and
    // offered as one click back to the full extent.
    const outsideWindow = computed(() => {
      if (filterWindow.value === 'all') return 0;
      return rows.value.filter(
        r => (!filterPhase.value || (r.phase || 'Ohne Phase') === filterPhase.value)
          && (!filterStatus.value || r.status === filterStatus.value)
          && (!filterLevel.value || r.level === filterLevel.value)
          && (!filterSource.value || r.source_hint === filterSource.value)
          && matchesOwner(r)
          && !inWindow(r)
      ).length;
    });

    const levelCounts = computed(() => {
      const out = {};
      for (const k of LEVEL_ORDER) out[k] = 0;
      for (const r of filtered.value) {
        if (out[r.level] !== undefined) out[r.level] += 1;
      }
      return out;
    });

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
      // Today is always inside the domain, even when every dated item sits in
      // the past or the future. Without this the "heute" marker silently
      // disappears exactly when it matters most — a plan whose work is all
      // ahead of it would draw no line to say where "now" is, and the reader
      // has no anchor to judge the bars against.
      points.push(todayMs());
      const pad = 3 * DAY_MS;
      let min = Math.min(...points) - pad;
      let max = Math.max(...points) + pad;

      // Clamp the AXIS to the chosen window, not just the row set.
      //
      // This is the bug behind "it still shows June": selecting rows and
      // sizing the axis are two different jobs, and only the first was
      // respecting the window. One overdue bar that STARTED on 1 July is
      // rightly kept — it is not finished — but its start date was then
      // dragging the whole axis back two months, so a plan opened on
      // Jun/Jul/Aug with today squeezed to the right. The bar still shows;
      // it is clipped at the edge instead of stretching the ruler.
      const b = windowBounds();
      const from = b ? toMs(b.from) : (forwardStartMs());
      const to = b ? toMs(b.to) : (forwardEndMs());
      if (from !== null) min = Math.max(min, from);
      if (to !== null) max = Math.min(max, to);
      if (max <= min) max = min + DAY_MS;

      return { min, max, span: Math.max(max - min, DAY_MS) };
    });

    /** Left edge of the forward window: today, exactly.
     *
     * It used to reach back to the oldest overdue deadline so that an overdue
     * item which had also ENDED before today still had somewhere to draw. That
     * bought one bar its lane at the cost of the whole ruler: a deadline missed
     * in July put July on the axis, which is precisely the "why am I looking at
     * June?" the window exists to prevent. The past is now off the axis
     * entirely, and those bars are drawn as a stub pinned to the left edge
     * (see barStyle) rather than given real estate on the ruler.
     */
    function forwardStartMs() {
      if (WINDOWS[filterWindow.value]?.mode !== 'forward') return null;
      return todayMs();
    }

    /** Right edge of the forward window. */
    function forwardEndMs() {
      const w = WINDOWS[filterWindow.value];
      if (w?.mode !== 'forward') return null;
      const to = new Date();
      to.setUTCMonth(to.getUTCMonth() + w.fwd);
      return toMs(to.toISOString().slice(0, 10));
    }

    /** Midnight UTC today, as ms. One definition, used by domain and marker. */
    function todayMs() {
      return Date.parse(new Date().toISOString().slice(0, 10) + 'T00:00:00Z');
    }

    /** How wide the track is, in px, at the current scale. */
    const trackWidthPx = computed(() => {
      const d = domain.value;
      if (!d) return 0;
      return Math.round((d.span / DAY_MS) * scale.value.pxPerDay);
    });

    function pct(ms) {
      const d = domain.value;
      if (!d || ms === null) return 0;
      return ((ms - d.min) / d.span) * 100;
    }

    /** pct(), held inside the track. Used for bars, which may overhang. */
    function clampedPct(ms) {
      return Math.min(100, Math.max(0, pct(ms)));
    }

    /** ISO week number, for the week-scale axis labels. */
    function isoWeek(date) {
      const d = new Date(Date.UTC(
        date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()
      ));
      // Thursday decides the year an ISO week belongs to.
      d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
      const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
      return Math.ceil(((d - yearStart) / DAY_MS + 1) / 7);
    }

    // Axis ticks follow the SCALE, not a fixed month grid. Zooming into a week
    // view and still reading "Mär … Apr" is the thing that made the old zoom
    // useless: the bars got longer and the axis said nothing new.
    const ticks = computed(() => {
      const d = domain.value;
      if (!d) return [];
      const kind = scale.value.tick;
      const out = [];
      const cur = new Date(d.min);
      cur.setUTCHours(0, 0, 0, 0);

      if (kind === 'day') {
        cur.setUTCDate(cur.getUTCDate());
      } else if (kind === 'week') {
        // Snap back to Monday so week labels line up with real weeks.
        const dow = cur.getUTCDay() || 7;
        cur.setUTCDate(cur.getUTCDate() - (dow - 1));
      } else {
        cur.setUTCDate(1);
        if (kind === 'quarter') {
          cur.setUTCMonth(Math.floor(cur.getUTCMonth() / 3) * 3);
        } else if (kind === 'year') {
          cur.setUTCMonth(0);
        }
      }

      // Bounded rather than while(true): a corrupt date can otherwise spin
      // here forever and take the whole page with it. The cap scales with the
      // granularity — a day axis over two years needs far more than 240.
      const maxTicks = kind === 'day' ? 800 : 400;
      for (let i = 0; i < maxTicks; i++) {
        const ms = cur.getTime();
        if (ms > d.max) break;
        if (ms >= d.min) {
          let label;
          let isYearStart = false;
          if (kind === 'day') {
            label = String(cur.getUTCDate());
            isYearStart = cur.getUTCDate() === 1;
          } else if (kind === 'week') {
            label = `KW ${isoWeek(cur)}`;
            isYearStart = isoWeek(cur) === 1;
          } else if (kind === 'quarter') {
            label = `Q${Math.floor(cur.getUTCMonth() / 3) + 1}`;
            isYearStart = cur.getUTCMonth() === 0;
          } else if (kind === 'year') {
            // The year IS the label here, so isYearStart stays false rather
            // than printing it twice.
            label = String(cur.getUTCFullYear());
          } else {
            label = MONTHS_DE[cur.getUTCMonth()];
            isYearStart = cur.getUTCMonth() === 0;
          }
          out.push({ left: pct(ms), label, year: cur.getUTCFullYear(), isYearStart });
        }
        if (kind === 'day') cur.setUTCDate(cur.getUTCDate() + 1);
        else if (kind === 'week') cur.setUTCDate(cur.getUTCDate() + 7);
        else if (kind === 'quarter') cur.setUTCMonth(cur.getUTCMonth() + 3);
        else if (kind === 'year') cur.setUTCFullYear(cur.getUTCFullYear() + 1);
        else cur.setUTCMonth(cur.getUTCMonth() + 1);
      }

      // Label the start of the axis whenever no tick already falls near it.
      //
      // Two cases, one cure. A coarse scale over a short plan can produce NO
      // tick at all — a domain inside one calendar year has its snapped
      // 1-January boundaries on either side of it, so both are skipped and the
      // axis renders blank. And now that the axis begins on TODAY rather than
      // a month boundary, the stretch from today to the 1st of next month is
      // unlabelled: an axis opening "Okt · Nov · Dez" silently drops the weeks
      // the reader is actually standing in.
      const nearStart = out.length && out[0].left < 4;
      if (!nearStart) {
        const start = new Date(d.min);
        let label;
        if (kind === 'year') label = String(start.getUTCFullYear());
        else if (kind === 'quarter') label = `Q${Math.floor(start.getUTCMonth() / 3) + 1}`;
        else if (kind === 'week') label = `KW ${isoWeek(start)}`;
        else if (kind === 'day') label = String(start.getUTCDate());
        else label = MONTHS_DE[start.getUTCMonth()];
        out.unshift({
          left: 0,
          label,
          year: start.getUTCFullYear(),
          isYearStart: false,
        });
      }
      return out;
    });

    // Never null now: domain always contains today (see above), so the marker
    // is always drawable and the reader always has an anchor.
    const todayLeft = computed(() => (domain.value ? pct(todayMs()) : null));

    function barStyle(r) {
      const s = toMs(r.start || r.end);
      const e = toMs(r.end);
      if (s === null || e === null) return { display: 'none' };
      const d = domain.value;
      // +1 day so a task that starts and ends on the same date still shows a
      // bar rather than a hairline.
      const endMs = e + DAY_MS;
      // Off the right-hand end there is genuinely nothing to say yet, so draw
      // nothing. Off the LEFT end is different: the row is on screen because
      // it is overdue and still open, and an empty lane hides exactly the
      // finding the reader came for. Those get a stub against the edge —
      // see isBeforeWindow / the .is-past styling.
      if (d && s > d.max) return { display: 'none' };
      if (d && endMs < d.min) return { left: '0%', width: '0.9%' };
      const left = clampedPct(s);
      const right = clampedPct(endMs);
      return { left: left + '%', width: Math.max(right - left, 0.6) + '%' };
    }

    /** True when a bar runs past the left edge of the window and is cut off. */
    function isClipped(r) {
      const d = domain.value;
      const s = toMs(r.start || r.end);
      return !!(d && s !== null && s < d.min);
    }

    /** True when the whole item lies before the window — deadline already
     *  missed. Drawn as a stub at the edge, not on the ruler. */
    function isBeforeWindow(r) {
      const d = domain.value;
      const e = toMs(r.end);
      return !!(d && e !== null && e + DAY_MS < d.min);
    }

    function milestoneStyle(r) {
      const e = toMs(r.end);
      const d = domain.value;
      if (e === null) return { display: 'none' };
      if (d && e > d.max) return { display: 'none' };
      // A missed date pins to the edge for the same reason a missed bar does:
      // it is on this screen precisely because it is late.
      if (d && e < d.min) return { left: '0%' };
      return { left: pct(e) + '%' };
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

    async function saveOwner(row) {
      const next = ownerDraft.value.trim();
      editingOwner.value = null;
      if (next === (row.owner || '')) return;
      ownerError.value = '';
      try {
        const resp = await fetch(
          `/api/schedule/${encodeURIComponent(row.project_id)}`
          + `/items/${encodeURIComponent(row.id)}/owner`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ owner: next }),
          }
        );
        if (!resp.ok) {
          const detail = await resp.json().catch(() => ({}));
          throw new Error(detail.detail || `Server returned ${resp.status}`);
        }
        const body = await resp.json();
        // The server redacts anything that would later trip the response
        // guard, so say when what was stored is not what was typed.
        if (body.redacted && body.redacted.length) {
          ownerError.value = 'Gespeichert, aber bereinigt: ' + body.redacted.join(', ');
        }
        emit('changed');
      } catch (err) {
        ownerError.value = String(err.message || err);
      }
    }

    function beginEdit(row) {
      editingOwner.value = row.id;
      ownerDraft.value = row.owner || '';
    }

    // Escape has to put the draft back before closing the editor. Unmounting a
    // focused input fires `blur`, so a bare `editingOwner = null` would run the
    // save on the way out and Escape would commit the very edit it is meant to
    // abandon. Restoring the original first makes that trailing save a no-op,
    // because saveOwner returns early when nothing changed.
    function cancelEdit(row) {
      ownerDraft.value = row.owner || '';
      editingOwner.value = null;
    }

    // ── Zoom & follow-today ─────────────────────────────────────────────
    const scrollEl = ref(null);

    /** Put today in the middle of the visible track.
     *
     * The track is wider than its container at every scale but the coarsest,
     * so without this a zoom lands wherever the previous scroll position
     * happened to be — usually the start of the project, months away from
     * anything anyone is working on. Centring rather than left-aligning keeps
     * the near past visible, which is where overdue items live.
     */
    function scrollToToday() {
      const el = scrollEl.value;
      if (!el || todayLeft.value === null) return;
      const target = (todayLeft.value / 100) * el.scrollWidth;
      el.scrollLeft = Math.max(0, target - el.clientWidth / 2);
    }

    /** Re-centre after the DOM has taken the new width. */
    function recentre() {
      nextTick(() => requestAnimationFrame(scrollToToday));
    }

    function zoomBy(step) {
      const next = Math.min(SCALES.length - 1, Math.max(0, scaleIndex.value + step));
      if (next === scaleIndex.value) return;
      scaleIndex.value = next;
      // Keep the same moment under the reader's eye across a zoom, rather
      // than making them re-find today at every step.
      recentre();
    }

    // ── Drag to pan ─────────────────────────────────────────────────────
    // The track scrolls with a wheel or a trackpad, but grabbing and dragging
    // it — the thing everyone tries first on a timeline — did nothing.
    //
    // Pointer events rather than mouse events, so a touchscreen and a pen work
    // the same way, with setPointerCapture so a drag that leaves the element
    // still tracks instead of freezing halfway.
    const dragging = ref(false);
    let _dragStartX = 0;
    let _dragStartScroll = 0;

    function onTrackPointerDown(ev) {
      // Left button only, and never start a pan on a control. The track holds
      // no buttons today, but the table lens beside it does; the guard is here
      // so adding one to a row cannot silently make it undraggable-to-click.
      if (ev.button !== 0) return;
      if (ev.target.closest('button, input, select, a')) return;
      const el = scrollEl.value;
      if (!el || el.scrollWidth <= el.clientWidth) return;  // nothing to pan

      dragging.value = true;
      _dragStartX = ev.clientX;
      _dragStartScroll = el.scrollLeft;
      ev.currentTarget.setPointerCapture?.(ev.pointerId);
    }

    function onTrackPointerMove(ev) {
      if (!dragging.value) return;
      const el = scrollEl.value;
      if (!el) return;
      const dx = ev.clientX - _dragStartX;
      el.scrollLeft = _dragStartScroll - dx;
      // Suppress text selection while panning; without it the drag paints the
      // whole plan blue instead of moving it.
      ev.preventDefault();
    }

    function onTrackPointerUp(ev) {
      if (!dragging.value) return;
      dragging.value = false;
      ev.currentTarget.releasePointerCapture?.(ev.pointerId);
    }

    function setScale(key) {
      const i = SCALES.findIndex((s) => s.key === key);
      if (i < 0 || i === scaleIndex.value) return;
      scaleIndex.value = i;
      recentre();
    }

    // On first paint, and whenever the row set changes the domain under us.
    onMounted(recentre);
    watch(() => [trackWidthPx.value, asTable.value], recentre);

    return {
      filterPhase, filterStatus, filterLevel, filterSource, asTable, hovered,
      filterWindow, outsideWindow, WINDOWS, WINDOW_ORDER,
      filterOwners, owners, UNASSIGNED, toggleOwner, clearOwners, ownerLabel,
      SCALES, scale, scaleIndex, zoomBy, setScale, scrollEl,
      dragging, onTrackPointerDown, onTrackPointerMove, onTrackPointerUp,
      trackWidthPx, scrollToToday,
      editingOwner, ownerDraft, ownerError, beginEdit, cancelEdit, saveOwner,
      rows, phases, sources, filtered, groups, ticks, todayLeft, barStyle,
      milestoneStyle, isClipped, isBeforeWindow, fmt, duration, isLate,
      lateCount, nextMilestone,
      daysToNext, statusCounts, levelCounts,
      STATUS, STATUS_ORDER, LEVEL_ORDER,
      statusLabel: (s) => (STATUS[s] || {}).label || s,
      statusClass: (s) => (STATUS[s] || {}).cls || 'is-open',
      levelLabel: (l) => LEVELS[l] || l,
      resetFilters() {
        filterPhase.value = '';
        filterStatus.value = '';
        filterLevel.value = '';
        filterSource.value = '';
        filterOwners.value = [];
        // Back to the default, not to "everything": resetting the filters
        // should return the screen someone started from, and that screen does
        // not open onto months of finished work.
        filterWindow.value = 'heute';
      },
    };
  },
  template: `
    <div>
      <!-- Hidden when embedded as a lens of Planung: that screen
           already carries the page title, and two <h1>s stacked would be
           wrong both visually and for a screen reader walking the headings. -->
      <div v-if="!embedded" class="page-header">
        <div>
          <h1 class="page-title">Termine &amp; Fristen</h1>
          <div class="page-subtitle">
            Alles mit einem Datum — quer über alle Quellen, vom Meilenstein
            bis zur einzelnen Aufgabe.
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
          <div class="empty-state-title">Nichts Datiertes importiert</div>
          <p class="text-sm">
            Hol dir mit <strong>Import JSON → Alle Termine &amp; To-dos</strong>
            einen Querschnitt über alle Projektdokumente, oder importiere den
            <code>Projektablaufplan_Detail</code> allein.
          </p>
        </div>
      </div>

      <template v-else>
        <!-- One line where a hero card and six tiles used to stand.

             The card said "41 days to Abnahme Fachtest" directly above a
             timeline on which that milestone is a diamond you can see and
             point at — a headline restating the picture below it, costing
             160px on the screen the app opens on. The four status tiles
             restated the bar colours the legend already names; they moved
             into the status filter, where the level filter had been carrying
             its counts all along. A count you can act on beats one you can
             only read.

             What survives is what the plan itself cannot say at a glance:
             how much is in view, how much is late, and how long to the next
             gate. -->
        <p class="plan-summary" data-testid="plan-summary">
          <strong>{{ filtered.length }}</strong>
          {{ filtered.length === 1 ? 'Vorgang' : 'Vorgänge' }}
          in {{ phases.length }} {{ phases.length === 1 ? 'Phase' : 'Phasen' }}
          <template v-if="lateCount">
            · <span class="is-alert"><strong>{{ lateCount }}</strong> überfällig</span>
          </template>
          <template v-if="nextMilestone && daysToNext !== null">
            · nächster Meilenstein in <strong>{{ daysToNext }}</strong>
            {{ daysToNext === 1 ? 'Tag' : 'Tagen' }}:
            {{ nextMilestone.title }} ({{ fmt(nextMilestone.end) }})
          </template>
        </p>


        <div class="filter-bar">
          <select class="filter-select" v-model="filterPhase" aria-label="Phase filtern">
            <option value="">Alle Phasen</option>
            <option v-for="p in phases" :key="p" :value="p">{{ p }}</option>
          </select>
          <select class="filter-select" v-model="filterStatus" aria-label="Status filtern">
            <option value="">Alle Status</option>
            <option v-for="s in STATUS_ORDER" :key="s" :value="s">
              {{ statusLabel(s) }} ({{ statusCounts[s] }})
            </option>
          </select>
          <select class="filter-select" v-model="filterLevel" aria-label="Ebene filtern">
            <option value="">Jede Flughöhe</option>
            <option v-for="l in LEVEL_ORDER" :key="l" :value="l">
              {{ levelLabel(l) }} ({{ levelCounts[l] }})
            </option>
          </select>
          <!-- Only offered once a sweep has actually pulled from more than
               one document; on a single-source import it is noise. -->
          <select v-if="sources.length > 1" class="filter-select" v-model="filterSource"
                  aria-label="Quelle filtern">
            <option value="">Alle Quellen</option>
            <option v-for="q in sources" :key="q" :value="q">{{ q }}</option>
          </select>
          <!-- A native <select multiple> shows every name as a permanently
               open list box and needs ctrl-click to combine, which nobody
               discovers. A disclosure with checkboxes reads as what it is. -->
          <details class="filter-multi" data-testid="filter-owner">
            <summary class="filter-select" role="button"
                     aria-label="Verantwortliche filtern">
              {{ ownerLabel }}
            </summary>
            <div class="filter-multi-panel">
              <label class="filter-multi-item">
                <input type="checkbox"
                       :checked="filterOwners.includes(UNASSIGNED)"
                       data-testid="owner-option-unassigned"
                       @change="toggleOwner(UNASSIGNED)">
                <span>— ohne Verantwortlichen —</span>
              </label>
              <label v-for="o in owners" :key="o" class="filter-multi-item">
                <input type="checkbox" :checked="filterOwners.includes(o)"
                       :data-testid="'owner-option'"
                       @change="toggleOwner(o)">
                <span>{{ o }}</span>
              </label>
              <button v-if="filterOwners.length" class="btn-link mt-1"
                      data-testid="owner-clear" @click="clearOwners">
                Auswahl aufheben
              </button>
            </div>
          </details>
          <select class="filter-select" v-model="filterWindow" aria-label="Zeitraum">
            <option v-for="w in WINDOW_ORDER" :key="w" :value="w">{{ WINDOWS[w].label }}</option>
          </select>
          <button v-if="filterPhase || filterStatus || filterLevel || filterSource || filterOwners.length"
                  class="btn btn-ghost" @click="resetFilters">
            Filter zurücksetzen
          </button>
          <!-- The table view is the accessible equal of the chart, not a
               fallback: every value the bars encode is readable as text. -->
          <!-- Zoom reads as a time scale, because that is what it is: the
               level name tells you what the axis is about to say. -->
          <div v-if="!asTable" class="zoom-control ml-auto" role="group" aria-label="Zoom">
            <button class="btn btn-ghost" :disabled="scaleIndex === 0"
                    aria-label="Herauszoomen" title="Herauszoomen"
                    data-testid="zoom-out" @click="zoomBy(-1)">−</button>
            <select class="filter-select zoom-scale" :value="scale.key"
                    aria-label="Zeitskala" data-testid="zoom-level"
                    @change="setScale($event.target.value)">
              <option v-for="sc in SCALES" :key="sc.key" :value="sc.key">
                {{ sc.label }}
              </option>
            </select>
            <button class="btn btn-ghost"
                    :disabled="scaleIndex === SCALES.length - 1"
                    aria-label="Hineinzoomen" title="Hineinzoomen"
                    data-testid="zoom-in" @click="zoomBy(1)">+</button>
            <button class="btn btn-ghost" title="Auf heute zentrieren"
                    aria-label="Auf heute zentrieren"
                    data-testid="jump-today" @click="scrollToToday">Heute</button>
          </div>
          <div class="segmented" :class="{ 'ml-auto': asTable }" role="group"
               aria-label="Darstellung">
            <button :class="{ active: !asTable }" @click="asTable = false">Balkenplan</button>
            <button :class="{ active: asTable }" @click="asTable = true">Tabelle</button>
          </div>
        </div>

        <!-- Whatever the window leaves out is said out loud, with one click
             back to the full extent. A line rather than a boxed card: the
             screen already stacks this directly beneath a second "what you
             are not seeing" notice, and two framed boxes in a row read as an
             error state rather than a footnote. -->
        <p v-if="outsideWindow" class="notice-inline" data-testid="window-notice">
          {{ outsideWindow }}
          {{ outsideWindow === 1 ? 'Eintrag liegt' : 'Einträge liegen' }}
          ausserhalb des gewählten Zeitraums —
          <button class="link-btn" @click="filterWindow = 'all'">
            ganzen Zeitraum zeigen</button>.
        </p>

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
            <span class="gantt-key is-termin" aria-hidden="true"></span>
            Termin ohne Dauer
          </span>
          <span class="gantt-legend-item">
            <span class="gantt-key is-today" aria-hidden="true"></span>
            Heute
          </span>
        </div>

        <!-- ── Balkenplan ────────────────────────────────────────────── -->
        <div v-if="ownerError" class="notice notice-warn mb-3">{{ ownerError }}</div>

        <div v-if="!asTable" class="card card-flush gantt-scroll" ref="scrollEl"
             :class="{ 'is-dragging': dragging }"
             @pointerdown="onTrackPointerDown"
             @pointermove="onTrackPointerMove"
             @pointerup="onTrackPointerUp"
             @pointercancel="onTrackPointerUp">
          <!-- Width in px, derived from the scale's px-per-day, so a day at
               "Woche" is the same width whatever the plan's total length. A
               percentage width made a two-year plan and a two-month plan look
               identical at the same zoom level. min-width keeps a short plan
               from collapsing narrower than its container. -->
          <div class="gantt"
               :style="{ width: Math.max(trackWidthPx, 0) + 'px', minWidth: '100%' }">
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
                          :class="[statusClass(r.status),
                                   { 'is-late': isLate(r), 'is-past': isBeforeWindow(r) }]"
                          :style="milestoneStyle(r)"
                          :aria-label="r.title + ' — Meilenstein am ' + fmt(r.end)
                                       + (isBeforeWindow(r) ? ' (Termin verstrichen)' : '')"></span>
                  </template>
                  <!-- A dated obligation with no span: a to-do with a
                       deadline. Its own mark, so it cannot be mistaken for a
                       project gate. -->
                  <template v-else-if="r.kind === 'termin'">
                    <span class="gantt-termin"
                          :class="[statusClass(r.status),
                                   { 'is-late': isLate(r), 'is-past': isBeforeWindow(r) }]"
                          :style="milestoneStyle(r)"
                          :aria-label="r.title + ' — faellig am ' + fmt(r.end)
                                       + (isBeforeWindow(r) ? ' (Termin verstrichen)' : '')"></span>
                  </template>
                  <template v-else>
                    <!-- is-clipped: the bar began before the window and is cut
                         at the edge. is-past: it ENDED before it too, so the
                         stub against the edge is all there is. Without either
                         marker the bar would read as work happening today,
                         which is a different claim. -->
                    <span class="gantt-bar"
                          :class="[statusClass(r.status),
                                   { 'is-late': isLate(r), 'is-clipped': isClipped(r),
                                     'is-past': isBeforeWindow(r) }]"
                          :style="barStyle(r)"
                          :aria-label="r.title + ' — ' + fmt(r.start) + ' bis ' + fmt(r.end)
                                       + (isBeforeWindow(r) ? ' (Frist verstrichen)'
                                          : isClipped(r) ? ' (beginnt vor dem Zeitraum)' : '')">
                      <span v-if="r.progress_pct !== null && r.progress_pct !== undefined"
                            class="gantt-progress"
                            :style="{ width: r.progress_pct + '%' }"></span>
                    </span>
                  </template>

                  <span v-if="hovered === r.id" class="gantt-tip"
                        :style="{ left: barStyle(r).left }">
                    <strong>{{ r.title }}</strong>
                    <span>{{ statusLabel(r.status) }}<template v-if="isLate(r)"> · überfällig</template></span>
                    <span v-if="!r.start">fällig {{ fmt(r.end) }}</span>
                    <span v-else>{{ fmt(r.start) }} – {{ fmt(r.end) }} · {{ duration(r) }}</span>
                    <span v-if="r.owner">{{ r.owner }}</span>
                    <span v-if="r.source_hint">Quelle: {{ r.source_hint }}</span>
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
                <th>Phase</th><th>Vorgang</th><th>Ebene</th>
                <th>Start</th><th>Fällig</th><th>Verantwortlich</th>
                <th>Quelle</th><th>Status</th><th class="text-right">Fortschritt</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in filtered" :key="r.id">
                <td class="text-gray-400">{{ r.phase || '—' }}</td>
                <td class="max-w-xs truncate" :title="r.title">{{ r.title }}</td>
                <td class="text-gray-400">{{ levelLabel(r.level) }}</td>
                <td class="font-mono text-xs">{{ fmt(r.start) }}</td>
                <td class="font-mono text-xs">
                  {{ fmt(r.end) }}
                  <span v-if="isLate(r)" class="gantt-late-tag">überfällig</span>
                </td>
                <td class="owner-cell">
                  <input v-if="editingOwner === r.id"
                         class="text-input owner-input"
                         v-model="ownerDraft"
                         :ref="el => el && el.focus()"
                         @keydown.enter="saveOwner(r)"
                         @keydown.esc="cancelEdit(r)"
                         @blur="saveOwner(r)"
                         aria-label="Verantwortlich bearbeiten">
                  <button v-else class="owner-button" @click="beginEdit(r)"
                          :title="'Verantwortlich für ' + r.title + ' ändern'">
                    {{ r.owner || '— zuweisen —' }}
                  </button>
                </td>
                <td class="text-gray-400 max-w-xs truncate" :title="r.source_hint">
                  {{ r.source_hint || '—' }}
                </td>
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


// ── WorkScreen ─────────────────────────────────────────────────────────────
// "Planung" — the merge of the old Todo and Termine & Fristen tabs.
//
// Those two were never two kinds of thing. They were one question — what does
// somebody owe, and by when — split by whether an item happened to carry a
// date. In this project's own data that split is 9 dated to-dos against 137
// undated ones, with ZERO title overlap between the two tabs: strictly
// additive, and strictly arbitrary from the reader's side. Answering "what is
// next" meant checking two places and merging them in your head.
//
// So: one dataset, two lenses over it.
//
//   Liste     — everything, bucketed by urgency. The undated items get a real
//               home ("Ohne Termin") instead of a separate tab, and overdue
//               work is the first thing on screen.
//   Zeitstrahl— the existing Gantt, unchanged, for the dated items.
//
// The TIMELINE is the default: the first question on opening the dashboard is
// "what is coming", and that is a shape, not a list. The list was the default
// while it was the only lens that could show every item — the timeline
// structurally cannot show an undated one — but a count chip above the track
// says how many items it is therefore not showing and links straight to the
// list, so the lens does not lie by omission. Whoever wants the full inventory
// is one click away; whoever wants the plan is already there.
const WorkScreen = {
  // The Gantt is 660 lines of working timeline code with its own filters,
  // zoom and inline owner editing. It is reused whole as the timeline lens
  // rather than reimplemented — the merge is about where things live, not
  // about rewriting what already works.
  components: { AblaufplanScreen },
  props: ['data', 'loading', 'error'],
  emits: ['delete-task', 'changed'],
  setup(props) {
    const lens = ref('zeitstrahl');
    const query = ref('');
    const {
      selected: filterOwners, toggleOwner, clearOwners,
      matchesOwner: ownerMatches, ownerLabel,
    } = createOwnerFilter();
    const filterStatus = ref('');
    const filterKind = ref('');


    // Both sources describe the same four states in different vocabularies.
    // Normalising once here is what lets one row template render both.
    const STATUS_FROM_TODO = {
      open: 'offen',
      in_progress: 'laufend',
      done: 'erledigt',
      closed: 'erledigt',
      blocked: 'blockiert',
    };
    const STATUS_LABEL = {
      offen: 'Offen',
      laufend: 'Laufend',
      erledigt: 'Erledigt',
      blockiert: 'Blockiert',
    };
    const STATUS_ORDER = ['offen', 'laufend', 'blockiert', 'erledigt'];

    function todayISO() {
      return new Date().toISOString().slice(0, 10);
    }

    /** The data the timeline lens sees: imported schedule rows PLUS every
     *  to-do that carries a deadline.
     *
     * The Gantt reads `data.ablaufplan`, which holds only what a sweep
     * imported. That was invisible while the list was the landing lens and
     * to-dos were created rarely. It is not invisible now: the timeline opens
     * first, and a to-do you just gave a deadline to would not be on it — the
     * one place you would go looking for it. So the lens is handed an
     * augmented copy rather than the raw payload.
     *
     * Dated to-dos map to `kind: 'termin'`, the mark the Gantt already has for
     * "a dated obligation with no span" — which is exactly what a to-do with a
     * deadline is. No new mark, no new legend entry.
     */
    const timelineData = computed(() => {
      const base = props.data || {};
      const extra = [];
      for (const p of base.pendenzen ?? []) {
        if (!p.due_date) continue;                 // undated: the notice covers it
        extra.push({
          id: `todo:${p.id}`,                      // namespaced: ids collide otherwise
          title: p.title,
          owner: p.owner || '',
          phase: 'Todos',
          start: p.due_date,
          end: p.due_date,
          status: STATUS_FROM_TODO[p.status] || 'offen',
          level: 'todo',
          kind: 'termin',
          source_hint: p.source || 'Todo',
          progress_pct: null,
        });
      }
      if (!extra.length) return base;
      return { ...base, ablaufplan: [...(base.ablaufplan ?? []), ...extra] };
    });

    /** Both sources, flattened into one row shape. */
    const rows = computed(() => {
      const out = [];
      for (const p of props.data?.pendenzen ?? []) {
        out.push({
          id: p.id,
          title: p.title,
          owner: p.owner || '',
          date: p.due_date || '',
          status: STATUS_FROM_TODO[p.status] || 'offen',
          kind: 'todo',
          detail: p.priority || '',
          origin: p.source || '',
          raw: p,
        });
      }
      for (const g of props.data?.ablaufplan ?? []) {
        out.push({
          id: g.id,
          title: g.title,
          owner: g.owner || '',
          // A bar's deadline is when it ENDS; a milestone has end === start.
          date: g.end || g.start || '',
          status: g.status || 'offen',
          kind: 'termin',
          detail: g.level || '',
          origin: g.source_hint || '',
          raw: g,
        });
      }
      return out;
    });

    const owners = computed(() => {
      const seen = [];
      for (const r of rows.value) {
        if (r.owner && !seen.includes(r.owner)) seen.push(r.owner);
      }
      return seen.sort((a, b) => a.localeCompare(b));
    });

    const statuses = computed(
      () => STATUS_ORDER.filter((s) => rows.value.some((r) => r.status === s))
    );

    function matches(r) {
      const q = query.value.trim().toLowerCase();
      if (q && !(`${r.title} ${r.owner}`.toLowerCase().includes(q))) return false;
      if (filterStatus.value && r.status !== filterStatus.value) return false;
      if (filterKind.value && r.kind !== filterKind.value) return false;
      if (!ownerMatches(r.owner)) return false;
      return true;
    }

    const filtered = computed(() => rows.value.filter(matches));

    const undatedCount = computed(
      () => filtered.value.filter((r) => !r.date).length
    );

    // Buckets answer "what is next" without the reader doing date arithmetic.
    // Erledigt is pulled out of the time buckets on purpose: a done item is
    // not upcoming work, and leaving it in "Überfällig" would cry wolf.
    const BUCKETS = [
      { key: 'overdue', label: 'Überfällig', tone: 'is-overdue' },
      { key: 'week', label: 'Diese Woche', tone: 'is-soon' },
      { key: 'month', label: 'Diesen Monat', tone: '' },
      { key: 'later', label: 'Später', tone: '' },
      { key: 'undated', label: 'Ohne Termin', tone: '' },
      { key: 'done', label: 'Erledigt', tone: 'is-done' },
    ];

    function bucketOf(r) {
      if (r.status === 'erledigt') return 'done';
      if (!r.date) return 'undated';
      const today = todayISO();
      if (r.date < today) return 'overdue';
      const in7 = new Date();
      in7.setUTCDate(in7.getUTCDate() + 7);
      if (r.date <= in7.toISOString().slice(0, 10)) return 'week';
      const in30 = new Date();
      in30.setUTCDate(in30.getUTCDate() + 30);
      if (r.date <= in30.toISOString().slice(0, 10)) return 'month';
      return 'later';
    }

    const grouped = computed(() => {
      const byKey = {};
      for (const b of BUCKETS) byKey[b.key] = [];
      for (const r of filtered.value) byKey[bucketOf(r)].push(r);
      for (const key of Object.keys(byKey)) {
        byKey[key].sort((a, b) => {
          // Undated rows have no date to sort on, so they fall back to title
          // rather than clumping in whatever order the import produced.
          if (!a.date && !b.date) return a.title.localeCompare(b.title);
          if (!a.date) return 1;
          if (!b.date) return -1;
          return a.date.localeCompare(b.date);
        });
      }
      return BUCKETS.map((b) => ({ ...b, rows: byKey[b.key] })).filter(
        (b) => b.rows.length
      );
    });

    function statusChip(s) {
      return `chip chip-${s}`;
    }

    function resetFilters() {
      query.value = '';
      filterOwners.value = [];
      filterStatus.value = '';
      filterKind.value = '';
    }

    function relativeDays(iso) {
      if (!iso) return '';
      const days = Math.round(
        (Date.parse(iso + 'T00:00:00Z') - Date.parse(todayISO() + 'T00:00:00Z'))
        / 86400000
      );
      if (days === 0) return 'heute';
      if (days === 1) return 'morgen';
      if (days === -1) return 'gestern';
      return days < 0 ? `vor ${-days} Tagen` : `in ${days} Tagen`;
    }

    // ── Beschlüsse ───────────────────────────────────────────────────────
    // A third lens rather than a lost view: a decision and the to-dos it set
    // in motion are read together, and the follow-up count is the link
    // between this lens and the list.
    const DECISION_STATUS = {
      beschlossen: { label: 'Beschlossen', cls: 'chip-open',      mark: 'mark-ring' },
      umgesetzt:   { label: 'Umgesetzt',   cls: 'chip-closed',    mark: 'mark-dot' },
      aufgehoben:  { label: 'Aufgehoben',  cls: 'chip-blocked',   mark: 'mark-square' },
      vertagt:     { label: 'Vertagt',     cls: 'chip-mitigated', mark: 'mark-bar' },
    };

    const decisionQuery = ref('');

    const decisions = computed(() => {
      const q = decisionQuery.value.trim().toLowerCase();
      const all = props.data?.decisions ?? [];
      if (!q) return all;
      return all.filter(
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
      lens, query, timelineData, filterOwners, filterStatus, filterKind,
      toggleOwner, clearOwners, ownerLabel,
      owners, statuses, UNASSIGNED, STATUS_LABEL,
      rows, filtered, grouped, undatedCount,
      statusChip, resetFilters, relativeDays,
      decisions, decisionQuery, openFollowUps, fmtDate,
      decisionLabel: (s) => (DECISION_STATUS[s] || {}).label || s,
      decisionClass: (s) => (DECISION_STATUS[s] || {}).cls || 'chip-open',
      decisionMark: (s) => (DECISION_STATUS[s] || {}).mark || 'mark-ring',
    };
  },
  template: `
    <div class="screen">
      <div class="page-head">
        <div>
          <h1 class="page-title">Planung</h1>
          <div class="page-subtitle">
            Alles, was jemand schuldet — mit und ohne Datum, aus allen Quellen.
          </div>
        </div>
      </div>

      <div v-if="loading && !data" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="card notice-error">{{ error }}</div>
      <div v-else-if="!rows.length" class="card">
        <div class="empty-state">
          <span class="empty-state-icon" aria-hidden="true">▤</span>
          <div class="empty-state-title">Nichts erfasst</div>
          <p class="text-sm">
            Importiere einen Copilot-Export oder lege einen Eintrag über
            <strong>Neu</strong> an.
          </p>
        </div>
      </div>

      <div v-else>
        <!-- Lens switch. Same data, two ways of reading it. -->
        <div class="lens-bar" role="tablist" aria-label="Ansicht">
          <button class="lens-btn" role="tab"
                  :class="{ 'is-active': lens === 'liste' }"
                  :aria-selected="lens === 'liste'"
                  data-testid="lens-liste"
                  @click="lens = 'liste'">Liste</button>
          <button class="lens-btn" role="tab"
                  :class="{ 'is-active': lens === 'zeitstrahl' }"
                  :aria-selected="lens === 'zeitstrahl'"
                  data-testid="lens-zeitstrahl"
                  @click="lens = 'zeitstrahl'">Zeitstrahl</button>
          <button class="lens-btn" role="tab"
                  :class="{ 'is-active': lens === 'beschluesse' }"
                  :aria-selected="lens === 'beschluesse'"
                  data-testid="lens-beschluesse"
                  @click="lens = 'beschluesse'">
            Beschlüsse
            <span v-if="data?.decisions?.length" class="lens-count">
              {{ data.decisions.length }}
            </span>
          </button>
        </div>

        <!-- ── Liste ────────────────────────────────────────────────────── -->
        <div v-if="lens === 'liste'">
          <div class="filter-bar">
            <input class="text-input" type="search" v-model="query"
                   placeholder="Titel oder Verantwortliche suchen…"
                   aria-label="Suchen" data-testid="work-search">
            <details class="filter-multi" data-testid="work-filter-owner">
              <summary class="filter-select" role="button"
                       aria-label="Nach Verantwortlichen filtern">
                {{ ownerLabel }}
              </summary>
              <div class="filter-multi-panel">
                <label class="filter-multi-item">
                  <input type="checkbox"
                         :checked="filterOwners.includes(UNASSIGNED)"
                         data-testid="work-owner-unassigned"
                         @change="toggleOwner(UNASSIGNED)">
                  <span>Ohne Verantwortliche</span>
                </label>
                <label v-for="o in owners" :key="o" class="filter-multi-item">
                  <input type="checkbox" :checked="filterOwners.includes(o)"
                         data-testid="work-owner-option"
                         @change="toggleOwner(o)">
                  <span>{{ o }}</span>
                </label>
                <button v-if="filterOwners.length" class="btn-link mt-1"
                        data-testid="work-owner-clear" @click="clearOwners">
                  Auswahl aufheben
                </button>
              </div>
            </details>
            <select class="filter-select" v-model="filterStatus" aria-label="Nach Status filtern">
              <option value="">Alle Status</option>
              <option v-for="s in statuses" :key="s" :value="s">{{ STATUS_LABEL[s] }}</option>
            </select>
            <select class="filter-select" v-model="filterKind" aria-label="Nach Art filtern"
                    data-testid="work-filter-kind">
              <option value="">To-dos und Termine</option>
              <option value="todo">Nur To-dos</option>
              <option value="termin">Nur Termine</option>
            </select>
            <span class="result-count">{{ filtered.length }} von {{ rows.length }}</span>
          </div>

          <div v-if="!filtered.length" class="card">
            <div class="empty-state">
              <div class="empty-state-title">Nichts passt zu diesen Filtern</div>
              <button class="btn mt-2" @click="resetFilters">Filter zurücksetzen</button>
            </div>
          </div>

          <div v-for="b in grouped" :key="b.key" class="bucket">
            <h2 class="bucket-head" :class="b.tone">
              {{ b.label }}
              <span class="bucket-count">{{ b.rows.length }}</span>
            </h2>
            <div class="card card-flush table-scroll">
              <table class="data-table">
                <tbody>
                  <tr v-for="r in b.rows" :key="r.kind + r.id">
                    <td class="w-1">
                      <span class="kind-chip" :class="'is-' + r.kind"
                            :title="r.kind === 'todo' ? 'To-do' : 'Termin'">
                        {{ r.kind === 'todo' ? 'To-do' : 'Termin' }}
                      </span>
                    </td>
                    <td class="max-w-xs truncate" :title="r.title">{{ r.title }}</td>
                    <!-- Priority for a to-do, altitude for a dated item. The
                         old Todo table showed priority and the merge dropped
                         it at first — with 137 of 146 to-dos carrying no date,
                         priority is the only thing left to triage them by, so
                         losing it would have made the merged list worse than
                         the tab it replaced. -->
                    <td class="text-gray-400 whitespace-nowrap">
                      <span v-if="r.kind === 'todo' && r.detail"
                            class="inline-flex items-center gap-2">
                        <span :class="['prio-dot', r.detail]"></span>{{ r.detail }}
                      </span>
                      <span v-else-if="r.detail">{{ r.detail }}</span>
                      <span v-else>—</span>
                    </td>
                    <td class="text-gray-400">{{ r.owner || '—' }}</td>
                    <td>
                      <span :class="statusChip(r.status)">{{ STATUS_LABEL[r.status] }}</span>
                    </td>
                    <td class="font-mono text-xs">
                      {{ r.date || '—' }}
                      <span v-if="r.date" class="text-gray-400">· {{ relativeDays(r.date) }}</span>
                    </td>
                    <td class="text-right row-actions">
                      <button class="icon-btn is-danger"
                              data-testid="delete-work"
                              :aria-label="r.title + ' löschen'"
                              title="Löschen"
                              @click="$emit('delete-task', r.raw)">&times;</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- ── Beschlüsse ───────────────────────────────────────────────── -->
        <div v-else-if="lens === 'beschluesse'">
          <div v-if="!(data?.decisions ?? []).length" class="card">
            <div class="empty-state">
              <span class="empty-state-icon" aria-hidden="true">◵</span>
              <div class="empty-state-title">Keine Beschlüsse importiert</div>
              <p class="text-sm">
                Importiere die <code>Pendenzen- und Beschlussliste</code> über
                <strong>Import JSON → Todos &amp; Beschlüsse</strong>.
              </p>
            </div>
          </div>
          <template v-else>
            <div class="filter-bar">
              <input class="text-input" type="search" v-model="decisionQuery"
                     placeholder="Beschluss, Gremium oder Bereich…"
                     aria-label="Beschlüsse durchsuchen">
              <span class="result-count">
                {{ decisions.length }} Beschlüsse · {{ openFollowUps }} offene Todos daraus
              </span>
            </div>

            <!-- One row per decision: what was decided, by whom, when, and
                 what it still owes. The follow-up count is the reason this
                 belongs beside the list rather than on its own tab. -->
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
                      {{ d.pendenzen_open }} von {{ d.pendenzen_total }} Todos offen
                    </span>
                    <span v-else class="text-gray-400">keine Todos</span>
                  </div>
                </div>
              </li>
            </ol>
          </template>
        </div>

        <!-- ── Zeitstrahl ───────────────────────────────────────────────── -->
        <div v-else>
          <!-- The timeline cannot place an undated item, so say how many it is
               leaving out rather than letting the lens quietly lose them. -->
          <p v-if="undatedCount" class="notice-inline" data-testid="undated-notice">
            {{ undatedCount }} Einträge ohne Termin erscheinen hier nicht —
            <button class="link-btn" @click="lens = 'liste'">in der Liste ansehen</button>.
          </p>
          <ablaufplan-screen
            :data="timelineData" :loading="loading" :error="error" :embedded="true"
            @changed="$emit('changed')" />
        </div>
      </div>
    </div>
  `,
};

global.AblaufplanScreen = AblaufplanScreen;
global.WorkScreen = WorkScreen;
global.OverviewScreen = OverviewScreen;
global.ProjectListScreen = ProjectListScreen;
global.ProjectDetailScreen = ProjectDetailScreen;
global.RisksScreen = RisksScreen;
global.ReviewsScreen = ReviewsScreen;
global.KanbanTab = KanbanTab;
}(window));
