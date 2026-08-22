/* HERMES Dashboard — Screen component definitions (Vue 3, loaded before app.js) */
/* global Vue */
'use strict';

const { ref, computed } = Vue;

// ── ProjectListScreen ──────────────────────────────────────────────────────
const ProjectListScreen = {
  props: ['data', 'loading', 'error'],
  emits: ['select-project'],
  setup(props) {
    const sortKey = ref('project_id');
    const sortDir = ref(1);

    const sorted = computed(() => {
      const rows = props.data?.projects ?? [];
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
      return sortKey.value === key ? (sortDir.value === 1 ? ' ↑' : ' ↓') : ' ⇕';
    }

    function tlCount(pid) {
      return (props.data?.timeline ?? []).filter(e => e.project_id === pid).length;
    }

    return { sorted, toggleSort, sortIcon, tlCount };
  },
  template: `
    <div>
      <h2 class="text-xl font-bold mb-4">Projects</h2>
      <div v-if="loading" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="text-red-500 p-4 card">{{ error }}</div>
      <div v-else-if="!data?.projects?.length" class="text-gray-400 p-6 card">
        No projects found. Create a directory under <code class="bg-gray-100 dark:bg-gray-700 px-1 rounded">data/projects/</code>.
      </div>
      <div v-else class="card overflow-x-auto">
        <table class="data-table">
          <thead>
            <tr>
              <th @click="toggleSort('project_id')">Project{{ sortIcon('project_id') }}</th>
              <th @click="toggleSort('label')">Label{{ sortIcon('label') }}</th>
              <th class="text-right">Timeline</th>
              <th class="text-right">Pendenzen</th>
              <th class="text-right">Reviews</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in sorted" :key="p.project_id" @click="$emit('select-project', p.project_id)">
              <td class="font-mono text-blue-500 font-medium">{{ p.project_id }}</td>
              <td>{{ p.label || '—' }}</td>
              <td class="text-right tabular-nums">{{ tlCount(p.project_id) }}</td>
              <td class="text-right tabular-nums">{{ (data?.pendenzen ?? []).length }}</td>
              <td class="text-right tabular-nums">{{ (data?.reviews ?? []).length }}</td>
            </tr>
          </tbody>
        </table>
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
        <select class="filter-select" v-model="filterStatus">
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
          <option value="blocked">Blocked</option>
          <option value="future">Future</option>
        </select>
        <span class="text-sm text-gray-400">{{ filtered.length }} items</span>
      </div>
      <div v-if="!filtered.length" class="text-gray-400 py-4">
        No timeline items. Run <code class="bg-gray-100 dark:bg-gray-700 px-1 rounded">hermes schedule</code> to derive one.
      </div>
      <div v-for="e in filtered" :key="e.date + e.label" class="tl-entry">
        <span class="tl-date">{{ e.date }}</span>
        <span :class="['tl-dot', e.status]" :aria-label="e.status"></span>
        <span :class="labelClass(e.status)" class="flex-1">{{ e.label }}</span>
        <span class="text-gray-400 text-xs shrink-0">{{ e.kind }}</span>
        <span class="text-gray-400 text-xs shrink-0 ml-2">{{ e.project_id }}</span>
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
      <div v-if="!columns?.length" class="text-gray-400 py-4">No kanban data.</div>
      <div v-else class="kanban-board">
        <div v-for="col in columns" :key="col.status" class="kanban-col">
          <div class="kanban-col-header">
            <span>{{ col.label }}</span>
            <span class="text-xs px-2 py-0.5 rounded-full"
                  style="background:var(--c-bg);border:1px solid var(--c-border)">
              {{ col.cards.length + col.overflow }}
            </span>
          </div>
          <div v-if="!col.cards.length && !col.overflow" class="text-gray-400 text-sm italic text-center py-2">
            Empty
          </div>
          <div
            v-for="card in col.cards"
            :key="card.id"
            class="kanban-card"
            @click="openCard(card)"
          >
            <div class="text-gray-400 font-mono text-xs mb-0.5">{{ card.wbs_number }}</div>
            <div class="font-medium text-sm leading-snug">{{ card.title }}</div>
            <div class="flex items-center gap-2 mt-1">
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

      <!-- Card detail modal -->
      <div v-if="selectedCard" class="modal-overlay" @click.self="closeCard">
        <div class="modal-box">
          <div class="flex justify-between items-start mb-4">
            <h3 class="font-semibold text-base leading-tight pr-4">{{ selectedCard.title }}</h3>
            <button @click="closeCard" class="text-gray-400 hover:text-gray-600 text-2xl leading-none" aria-label="Close">&times;</button>
          </div>
          <table class="text-sm w-full">
            <tbody>
              <tr v-for="[k, v] in [['WBS', selectedCard.wbs_number || '—'], ['Kind', selectedCard.kind], ['Owner', selectedCard.owner || '—'], ['Priority', selectedCard.priority || '—']]" :key="k">
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
// WbsNodeItem and WbsTab are defined in components.js (loaded before this file)
const ProjectDetailScreen = {
  props: ['data', 'loading', 'error', 'projectId'],
  emits: ['back'],
  // WbsTab is globally registered in app.js via vueApp.component()
  components: { TimelineTab, KanbanTab },
  setup() {
    const activeTab = ref('timeline');
    return { activeTab };
  },
  template: `
    <div>
      <div class="flex items-center gap-3 mb-4">
        <button @click="$emit('back')" class="text-blue-500 hover:underline text-sm" aria-label="Back to projects">
          &larr; Projects
        </button>
        <h2 class="text-xl font-bold">{{ projectId || 'All Projects' }}</h2>
      </div>
      <div v-if="loading" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="text-red-500 p-4 card">{{ error }}</div>
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
    const filterSource = ref('');
    const filterPriority = ref('');
    const filterStatus = ref('');
    const sortKey = ref('priority');
    const sortDir = ref(1);

    const sources = computed(() => [...new Set((props.data?.pendenzen ?? []).map(r => r.source))].sort());
    const statuses = computed(() => [...new Set((props.data?.pendenzen ?? []).map(r => r.status))].sort());

    const _PRIO_RANK = { blocker: 0, high: 1, medium: 2, low: 3 };

    const filtered = computed(() => {
      let rows = props.data?.pendenzen ?? [];
      if (filterSource.value) rows = rows.filter(r => r.source === filterSource.value);
      if (filterPriority.value) rows = rows.filter(r => r.priority === filterPriority.value);
      if (filterStatus.value) rows = rows.filter(r => r.status === filterStatus.value);
      return [...rows].sort((a, b) => {
        if (sortKey.value === 'priority') {
          const diff = (_PRIO_RANK[a.priority] ?? 9) - (_PRIO_RANK[b.priority] ?? 9);
          return sortDir.value * diff;
        }
        return sortDir.value * String(a[sortKey.value] ?? '').localeCompare(String(b[sortKey.value] ?? ''));
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
      return 'badge ' + (map[s] ?? 'badge-open');
    }

    return {
      filterSource, filterPriority, filterStatus, sources, statuses,
      filtered, toggleSort, sortIcon, statusBadgeClass,
    };
  },
  template: `
    <div>
      <h2 class="text-xl font-bold mb-4">Pendenzen</h2>
      <div v-if="loading" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="text-red-500 p-4 card">{{ error }}</div>
      <div v-else>
        <div class="filter-bar">
          <select class="filter-select" v-model="filterSource">
            <option value="">All sources</option>
            <option v-for="s in sources" :key="s" :value="s">{{ s }}</option>
          </select>
          <select class="filter-select" v-model="filterPriority">
            <option value="">All priorities</option>
            <option value="blocker">Blocker</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select class="filter-select" v-model="filterStatus">
            <option value="">All statuses</option>
            <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
          </select>
          <span class="text-sm text-gray-400">{{ filtered.length }} items</span>
        </div>
        <div v-if="!filtered.length" class="text-gray-400 p-4">
          No pendenzen match the current filters.
        </div>
        <div v-else class="card overflow-x-auto">
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
                  <span class="inline-flex items-center gap-1 text-sm">
                    <span :class="['prio-dot', r.priority]"></span>{{ r.priority }}
                  </span>
                </td>
                <td><span :class="statusBadgeClass(r.status)">{{ r.status }}</span></td>
                <td class="text-gray-400 text-sm">{{ r.owner || '—' }}</td>
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
    const filterStatus = ref('');
    const sortKey = ref('score');
    const sortDir = ref(-1);

    const filtered = computed(() => {
      let rows = props.data?.risks ?? [];
      if (filterStatus.value) rows = rows.filter(r => r.status === filterStatus.value);
      return [...rows].sort((a, b) => {
        const av = typeof a[sortKey.value] === 'number' ? a[sortKey.value] : String(a[sortKey.value] ?? '');
        const bv = typeof b[sortKey.value] === 'number' ? b[sortKey.value] : String(b[sortKey.value] ?? '');
        if (typeof av === 'number' && typeof bv === 'number') return sortDir.value * (av - bv);
        return sortDir.value * String(av).localeCompare(String(bv));
      });
    });

    function toggleSort(key) {
      if (sortKey.value === key) sortDir.value *= -1;
      else { sortKey.value = key; sortDir.value = -1; }
    }

    function sortIcon(key) {
      return sortKey.value === key ? (sortDir.value === 1 ? ' ↑' : ' ↓') : '';
    }

    function statusClass(s) {
      const map = { open: 'risk-open', mitigated: 'risk-mitigated', accepted: 'risk-accepted', closed: 'risk-closed' };
      return map[s] ?? '';
    }

    return { filterStatus, filtered, toggleSort, sortIcon, statusClass };
  },
  template: `
    <div>
      <h2 class="text-xl font-bold mb-4">Risks</h2>
      <div v-if="loading" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="text-red-500 p-4 card">{{ error }}</div>
      <div v-else>
        <div class="filter-bar">
          <select class="filter-select" v-model="filterStatus">
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="mitigated">Mitigated</option>
            <option value="accepted">Accepted</option>
            <option value="closed">Closed</option>
          </select>
          <span class="text-sm text-gray-400">{{ filtered.length }} risks</span>
        </div>
        <div v-if="!filtered.length" class="text-gray-400 p-4">No risks recorded.</div>
        <div v-else class="card overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th @click="toggleSort('title')">Title{{ sortIcon('title') }}</th>
                <th @click="toggleSort('severity')">Severity{{ sortIcon('severity') }}</th>
                <th @click="toggleSort('likelihood')" class="text-right">Likelihood{{ sortIcon('likelihood') }}</th>
                <th @click="toggleSort('score')" class="text-right">Score{{ sortIcon('score') }}</th>
                <th @click="toggleSort('status')">Status{{ sortIcon('status') }}</th>
                <th @click="toggleSort('updated_at')">Updated{{ sortIcon('updated_at') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in filtered" :key="r.id">
                <td class="max-w-xs truncate" :title="r.title">{{ r.title }}</td>
                <td>{{ r.severity }}</td>
                <td class="text-right tabular-nums">{{ r.likelihood }}</td>
                <td class="text-right tabular-nums font-semibold">{{ r.score }}</td>
                <td><span :class="statusClass(r.status)">{{ r.status }}</span></td>
                <td class="font-mono text-xs">{{ r.updated_at.substring(0, 10) }}</td>
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
      <h2 class="text-xl font-bold mb-4">Reviews</h2>
      <div v-if="loading" class="flex items-center gap-2 py-8 text-gray-400">
        <span class="spinner"></span> Loading&hellip;
      </div>
      <div v-else-if="error" class="text-red-500 p-4 card">{{ error }}</div>
      <div v-else>
        <div class="filter-bar">
          <select class="filter-select" v-model="filterVerdict">
            <option value="">All verdicts</option>
            <option value="pass">Pass</option>
            <option value="pass_with_comments">Pass with comments</option>
            <option value="fail">Fail</option>
          </select>
          <span class="text-sm text-gray-400">{{ filtered.length }} reviews</span>
        </div>
        <div v-if="!filtered.length" class="text-gray-400 p-4">
          No completed reviews.
          Use <code class="bg-gray-100 dark:bg-gray-700 px-1 rounded">hermes review --wait</code> to run one.
        </div>
        <div v-else class="card overflow-x-auto">
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
              <tr v-for="r in filtered" :key="r.job_id" @click="openReview(r)">
                <td class="font-mono text-xs">{{ r.job_id.substring(0, 12) }}&hellip;</td>
                <td>{{ r.rubric_id }}</td>
                <td><span :class="verdictClass(r.verdict)">{{ r.verdict }}</span></td>
                <td class="text-right tabular-nums" :class="r.blockers > 0 ? 'text-red-500 font-bold' : ''">{{ r.blockers }}</td>
                <td class="text-right tabular-nums" :class="r.majors > 0 ? 'text-orange-500 font-semibold' : ''">{{ r.majors }}</td>
                <td class="text-right tabular-nums">{{ r.minors }}</td>
                <td class="text-sm font-mono">{{ r.deliverable }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Review detail modal -->
        <div v-if="selectedReview" class="modal-overlay" @click.self="closeReview">
          <div class="modal-box">
            <div class="flex justify-between items-center mb-4">
              <h3 class="font-semibold">Review Detail</h3>
              <button @click="closeReview" class="text-gray-400 hover:text-gray-600 text-2xl leading-none" aria-label="Close">&times;</button>
            </div>
            <table class="text-sm w-full">
              <tbody>
                <tr><td class="text-gray-400 pr-4 py-1.5 w-28">Job ID</td><td class="font-mono text-xs break-all">{{ selectedReview.job_id }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Rubric</td><td>{{ selectedReview.rubric_id }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Verdict</td>
                    <td><span :class="['font-semibold', verdictClass(selectedReview.verdict)]">{{ selectedReview.verdict }}</span></td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Blockers</td>
                    <td :class="selectedReview.blockers > 0 ? 'text-red-500 font-bold' : ''">{{ selectedReview.blockers }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Majors</td>
                    <td :class="selectedReview.majors > 0 ? 'text-orange-500' : ''">{{ selectedReview.majors }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Minors</td><td>{{ selectedReview.minors }}</td></tr>
                <tr><td class="text-gray-400 pr-4 py-1.5">Deliverable</td><td class="font-mono text-xs">{{ selectedReview.deliverable }}</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `,
};
