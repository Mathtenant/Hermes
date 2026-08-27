/* HERMES Dashboard — Shared sub-components (loaded before screens.js).
 *
 * Each dashboard script runs in an IIFE and publishes its components on
 * `window`. Classic <script> tags share one global lexical scope, so
 * top-level `const { ref } = Vue` in more than one file would throw
 * "Identifier 'ref' has already been declared" and abort the whole app.
 */
/* global Vue */
(function (global) {
'use strict';

const { ref } = Vue;

// ── WbsNodeItem (recursive tree node) ─────────────────────────────────────
// Registered globally in app.js so WbsTab can use it recursively without
// an explicit local components: {} declaration on each parent.
const WbsNodeItem = {
  name: 'WbsNodeItem',
  props: ['node', 'isExpanded', 'toggle', 'statusIcon'],
  template: `
    <div class="wbs-node">
      <div class="wbs-item">
        <button
          v-if="node.children?.length"
          class="wbs-toggle"
          @click="toggle(node.id)"
          :aria-expanded="String(isExpanded(node.id))"
          :aria-label="isExpanded(node.id) ? 'Collapse' : 'Expand'"
        >{{ isExpanded(node.id) ? '▾' : '▸' }}</button>
        <span v-else style="width:20px;display:inline-block"></span>
        <span class="wbs-status" :class="node.status" :title="node.status">{{ statusIcon(node.status) }}</span>
        <span class="wbs-num">{{ node.wbs_number }}</span>
        <span class="flex-1 truncate" :title="node.title">{{ node.title }}</span>
        <span class="text-gray-400 text-xs shrink-0">{{ node.kind }}</span>
        <span v-if="node.owner" class="text-gray-400 text-xs ml-2 shrink-0">{{ node.owner }}</span>
      </div>
      <template v-if="node.children?.length && isExpanded(node.id)">
        <wbs-node-item
          v-for="child in node.children"
          :key="child.id"
          :node="child"
          :is-expanded="isExpanded"
          :toggle="toggle"
          :status-icon="statusIcon"
        />
      </template>
    </div>
  `,
};

// ── WbsTab ─────────────────────────────────────────────────────────────────
const WbsTab = {
  name: 'WbsTab',
  props: ['nodes'],
  components: { WbsNodeItem },
  setup() {
    // `expanded` holds only the nodes the user has explicitly toggled;
    // everything else follows `defaultExpanded`. Keeping the default as its
    // own piece of state is what makes "Collapse all" work on a tree nobody
    // has touched yet: the old version wrote `false` for the ids already in
    // the dict, which on a fresh render was none of them, so the button did
    // nothing at all. It also means neither button has to walk the tree.
    const expanded = ref({});
    const defaultExpanded = ref(true);

    function isExpanded(id) {
      const override = expanded.value[id];
      return override === undefined ? defaultExpanded.value : override;
    }

    function toggle(id) {
      expanded.value = { ...expanded.value, [id]: !isExpanded(id) };
    }

    function statusIcon(s) {
      return s === 'closed' ? '✓' : s === 'blocked' ? '!' : '○';
    }

    function setAll(val) {
      defaultExpanded.value = val;
      expanded.value = {};  // drop per-node overrides so the default wins
    }

    return { toggle, isExpanded, statusIcon, setAll };
  },
  template: `
    <div>
      <div class="filter-bar">
        <button class="btn-link" @click="setAll(true)">Expand all</button>
        <span class="text-gray-300">/</span>
        <button class="btn-link" @click="setAll(false)">Collapse all</button>
        <span class="result-count">{{ nodes?.length ?? 0 }} root nodes</span>
      </div>
      <div v-if="!nodes?.length" class="empty-state">
        <div class="empty-state-title">No tasks</div>
        <p class="text-sm">Use <code>hermes task-add</code> to create tasks.</p>
      </div>
      <div class="wbs-tree" v-else>
        <wbs-node-item
          v-for="node in nodes"
          :key="node.id"
          :node="node"
          :is-expanded="isExpanded"
          :toggle="toggle"
          :status-icon="statusIcon"
        />
      </div>
    </div>
  `,
};

global.WbsNodeItem = WbsNodeItem;
global.WbsTab = WbsTab;
}(window));
