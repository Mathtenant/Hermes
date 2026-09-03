/* HERMES Dashboard — Main application.
 *
 * Requires (in load order): vendor/vue.global.prod.js, components.js, screens.js
 */
/* global Vue, OverviewScreen, ProjectListScreen, ProjectDetailScreen,
          ReviewsScreen, RisksScreen, WorkScreen,
          WbsNodeItem, WbsTab, KanbanTab */
(function () {
'use strict';

const {
  createApp, ref, reactive, computed, onMounted, onUnmounted, watch, nextTick,
} = Vue;

// Screens that can be reached from the sidebar / hash router.
// 'plan' and 'pendenzen' used to be two entries. They were never two kinds of
// thing — one question ("what is owed, by when") split by whether an item
// happened to carry a date — so they are one screen now, keyed 'work'. The
// old keys stay resolvable in resolveScreen() so existing links and stored
// sidebar orders keep working.
const SCREENS = [
  'overview', 'projects', 'detail', 'work', 'risks', 'reviews',
];

// Retired screen keys → where they live now. Bookmarks and the persisted
// sidebar order both hold raw keys, so dropping a key without a forwarding
// address would silently strand them.
const SCREEN_ALIASES = { plan: 'work', pendenzen: 'work' };

// Sidebar icons: SVG path data on a 24×24 grid, drawn as strokes so they
// inherit the nav item's colour and stay optically consistent with each other
// (the previous Unicode glyphs were rendered by whichever fallback font
// happened to carry them, at whatever weight that font used).
const NAV_ICONS = {
  overview:  'M4 5h7v6H4zM13 5h7v4h-7zM13 11h7v8h-7zM4 13h7v6H4z',
  projects:  'M4 6h16M4 12h16M4 18h16',
  detail:    'M4 6h9M4 12h13M4 18h7M19 5v4M17 7h4',
  work:      'M4 6h9M8 12h10M4 18h7M4 4v16',
  risks:     'M12 4l8.5 15h-17zM12 10v4M12 17.2v.1',
  reviews:   'M4.5 12.5l4.5 4.5 10.5-11',
};

// ── Sidebar order ──────────────────────────────────────────────────────────
// The order is the user's, so it is stored rather than derived. It is stored
// as a list of keys and reconciled against the canonical screen list on every
// read: a screen added in a later version appears at the end instead of
// vanishing, and one that was removed drops out instead of leaving a hole.
const NAV_ORDER_KEY = 'hermes-nav-order';

function readNavOrder() {
  try {
    const raw = JSON.parse(localStorage.getItem(NAV_ORDER_KEY) || '[]');
    return Array.isArray(raw) ? raw.filter((k) => typeof k === 'string') : [];
  } catch {
    return [];
  }
}

function reconcileOrder(stored, canonical) {
  // Map retired keys onto their replacement FIRST, so a merged screen keeps
  // the slot its predecessor held instead of being treated as brand new and
  // appended at the bottom of someone's carefully arranged sidebar. Two old
  // keys can map to one new one, so de-duplicate after mapping.
  const mapped = stored.map((k) => SCREEN_ALIASES[k] || k);
  const known = [...new Set(mapped)].filter((k) => canonical.includes(k));
  return [...known, ...canonical.filter((k) => !known.includes(k))];
}

const navOrder = ref(reconcileOrder(readNavOrder(), SCREENS));

function persistNavOrder() {
  try {
    localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(navOrder.value));
  } catch {
    /* storage unavailable — the order still applies for this session */
  }
}

function moveNav(key, delta) {
  const order = [...navOrder.value];
  const from = order.indexOf(key);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= order.length) return false;
  order.splice(to, 0, order.splice(from, 1)[0]);
  navOrder.value = order;
  persistNavOrder();
  return true;
}

function dropNav(dragKey, targetKey) {
  if (!dragKey || dragKey === targetKey) return;
  const order = [...navOrder.value];
  const from = order.indexOf(dragKey);
  const to = order.indexOf(targetKey);
  if (from < 0 || to < 0) return;
  order.splice(to, 0, order.splice(from, 1)[0]);
  navOrder.value = order;
  persistNavOrder();
}

// ── Global reactive state ──────────────────────────────────────────────────
const state = reactive({
  screen: 'overview',  // one of SCREENS
  projectId: null,     // currently selected project ID
  data: null,          // DashboardData from API
  loading: false,
  error: null,
  lastRefresh: null,
  showHelp: false,
  showImport: false,
  showCreate: false,
});

// ── Theme ──────────────────────────────────────────────────────────────────
function preferredTheme() {
  const stored = localStorage.getItem('hermes-theme');
  if (stored === 'dark' || stored === 'light') return stored;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

const theme = ref(preferredTheme());

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try {
    localStorage.setItem('hermes-theme', t);
  } catch {
    /* storage unavailable (private mode) — theme still applies for this session */
  }
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark';
  applyTheme(theme.value);
}

// ── Toast notifications ────────────────────────────────────────────────────
// A toast can carry one action, which is how Undo reaches the user: the moment
// after a delete is the only moment they are still thinking about it, so the
// way back belongs there rather than in a separate trash screen.
const toast = reactive({ message: null, isError: false, undo: null });
let _toastTimer = null;

// Undo gets longer than a plain notice — 4s is enough to read "saved", not
// enough to decide you did not mean to delete something.
const TOAST_MS = 4000;
const UNDO_TOAST_MS = 12000;

function showToast(msg, isError = false, undo = null) {
  toast.message = msg;
  toast.isError = isError;
  toast.undo = undo;
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(
    () => { toast.message = null; toast.undo = null; },
    undo ? UNDO_TOAST_MS : TOAST_MS,
  );
}

function dismissToast() {
  if (_toastTimer) clearTimeout(_toastTimer);
  toast.message = null;
  toast.undo = null;
}

/** Run the pending toast's undo action, then report what happened. */
async function runUndo() {
  const action = toast.undo;
  if (!action) return;
  // Clear first: a second click while the request is in flight would restore
  // twice, and the second restore has nothing left to do but confuse.
  dismissToast();
  try {
    const resp = await fetch(action.url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(action.body),
    });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      showToast(detail.detail || 'Undo failed', true);
      return;
    }
    showToast(action.okMessage || 'Restored');
    await refresh();
  } catch {
    showToast('Undo failed — is the server still running?', true);
  }
}

// ── API fetch ──────────────────────────────────────────────────────────────
async function loadDashboard(projectId) {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  const resp = await fetch(`/api/dashboard${qs}`);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

async function fetchData(projectId) {
  state.loading = true;
  state.error = null;
  try {
    state.data = await loadDashboard(projectId);
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

// ── App version ────────────────────────────────────────────────────────────
// Served by /api/health from hermes_assistant.__version__, so the frontend
// never carries its own copy of the version string.
const version = ref('');

async function loadVersion() {
  try {
    const resp = await fetch('/api/health');
    if (!resp.ok) return;
    const body = await resp.json();
    if (body.version) version.value = body.version;
  } catch {
    // Version is cosmetic — leave it blank rather than surfacing an error
  }
}

// ── Create (todo / task / project) ─────────────────────────────────────────
// Everything on the dashboard arrived by import, which left it read-only for
// anything that came up between exports — exactly when a to-do is born.
const CREATE_KINDS = [
  { key: 'todo', label: 'Todo', hint: 'Offener Punkt mit Verantwortlichem und Termin' },
  { key: 'task', label: 'Arbeitspaket', hint: 'Knoten im Strukturplan / auf dem Board' },
  { key: 'project', label: 'Projekt', hint: 'Neues, leeres Projektverzeichnis' },
];

const createKind = ref('todo');
const createForm = reactive({
  title: '', owner: '', priority: 'medium', due_date: '', description: '',
  node_kind: 'task', status: 'open', project_id: '',
});
const createBusy = ref(false);
const createError = ref('');

function openCreate() {
  createError.value = '';
  state.showCreate = true;
}

function closeCreate() {
  state.showCreate = false;
}

function resetCreateForm() {
  Object.assign(createForm, {
    title: '', owner: '', priority: 'medium', due_date: '', description: '',
    node_kind: 'task', status: 'open', project_id: '',
  });
}

function createPayload() {
  if (createKind.value === 'project') {
    return { project_id: createForm.project_id.trim() };
  }
  if (createKind.value === 'task') {
    return {
      title: createForm.title.trim(),
      owner: createForm.owner.trim(),
      node_kind: createForm.node_kind,
      status: createForm.status,
    };
  }
  return {
    title: createForm.title.trim(),
    owner: createForm.owner.trim(),
    priority: createForm.priority,
    due_date: createForm.due_date,
    description: createForm.description.trim(),
  };
}

const createValid = computed(() => (createKind.value === 'project'
  ? createForm.project_id.trim().length > 0
  : createForm.title.trim().length > 0));

async function submitCreate() {
  if (!createValid.value || createBusy.value) return;
  createBusy.value = true;
  createError.value = '';
  const endpoint = { todo: '/api/todos', task: '/api/tasks', project: '/api/projects' }[
    createKind.value
  ];
  try {
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(createPayload()),
    });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || `HTTP ${resp.status}`);
    }
    const kindLabel = (CREATE_KINDS.find((k) => k.key === createKind.value) || {}).label;
    showToast(`${kindLabel} angelegt`);
    resetCreateForm();
    closeCreate();
    await refresh();
  } catch (e) {
    createError.value = String(e.message || e);
  } finally {
    createBusy.value = false;
  }
}

// ── Delete ─────────────────────────────────────────────────────────────────
// Both deletes are recoverable server-side, so the confirm step is about
// intent, not safety. The project confirm is the blunter of the two because a
// project directory holds the user's own documents.

/** Delete a to-do or work package, offering Undo in the toast. */
async function deleteTask(task) {
  if (!task || !task.id) return;
  const label = task.title || 'Eintrag';
  if (!window.confirm(`"${label}" löschen?`)) return;
  try {
    const resp = await fetch(`/api/tasks/${encodeURIComponent(task.id)}`, {
      method: 'DELETE',
    });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      showToast(detail.detail || 'Löschen fehlgeschlagen', true);
      return;
    }
    const body = await resp.json();
    // A subtree delete removes more than the row that was clicked; say so,
    // otherwise the count in the sidebar drops by more than the user expects.
    const extra = body.deleted > 1 ? ` (mit ${body.deleted - 1} Unterpunkten)` : '';
    await refresh();
    showToast(`"${label}" gelöscht${extra}`, false, {
      url: '/api/tasks/restore',
      body: body.undo,
      okMessage: `"${label}" wiederhergestellt`,
    });
  } catch {
    showToast('Löschen fehlgeschlagen — läuft der Server noch?', true);
  }
}

/** Delete a project directory (moved to trash), offering Undo in the toast. */
async function deleteProject(projectId) {
  if (!projectId) return;
  if (!window.confirm(
    `Projekt "${projectId}" löschen?\n\n` +
    'Der Ordner wird in den Papierkorb verschoben, nicht gelöscht. ' +
    'Deine Dokumente bleiben erhalten.'
  )) return;
  try {
    const resp = await fetch(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: 'DELETE',
    });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      showToast(detail.detail || 'Löschen fehlgeschlagen', true);
      return;
    }
    const body = await resp.json();
    // The detail screen would be pointing at a project that is no longer there.
    if (state.projectId === projectId) {
      state.projectId = null;
      goTo('projects');
    }
    await refresh();
    showToast(`Projekt "${projectId}" gelöscht`, false, {
      url: '/api/projects/restore',
      body: body.undo,
      okMessage: `Projekt "${projectId}" wiederhergestellt`,
    });
  } catch {
    showToast('Löschen fehlgeschlagen — läuft der Server noch?', true);
  }
}

// ── Navigation (hash-routed so screens are linkable and survive reload) ────
function syncHash() {
  const hash = state.projectId && state.screen === 'detail'
    ? `#/detail/${encodeURIComponent(state.projectId)}`
    : `#/${state.screen}`;
  if (window.location.hash !== hash) {
    // replaceState avoids polluting history with every sidebar click
    window.history.replaceState(null, '', hash);
  }
}

/** Map a possibly-retired screen key onto a live one, or '' if unknown. */
function resolveScreen(screen) {
  const target = SCREEN_ALIASES[screen] || screen;
  return SCREENS.includes(target) ? target : '';
}

function goTo(rawScreen) {
  const screen = resolveScreen(rawScreen);
  if (!screen) return;
  // "Project detail" without a selection means the all-projects rollup.
  state.screen = screen;
  if (screen === 'projects' || screen === 'overview') {
    if (state.projectId !== null) {
      state.projectId = null;
      fetchData(null);
    }
  }
  syncHash();
}

function selectProject(projectId) {
  state.projectId = projectId;
  state.screen = 'detail';
  syncHash();
  fetchData(projectId);
}

function clearProject() {
  state.projectId = null;
  state.screen = 'projects';
  syncHash();
  fetchData(null);
}

function applyHash() {
  const raw = window.location.hash.replace(/^#\/?/, '');
  if (!raw) return false;
  const [rawScreen, encodedId] = raw.split('/');
  // An old #/pendenzen or #/plan bookmark lands on the merged screen rather
  // than falling through to the default and looking broken.
  const screen = resolveScreen(rawScreen);
  if (!screen) return false;
  state.screen = screen;
  state.projectId = encodedId ? decodeURIComponent(encodedId) : null;
  return true;
}

// ── Live polling (5 s, silent — only swaps data if generated_at changed) ───
let _pollTimer = null;

function startPolling() {
  stopPolling();
  _pollTimer = setInterval(async () => {
    if (state.loading || document.hidden) return;
    try {
      const fresh = await loadDashboard(state.projectId);
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

// ── JSON Import wizard ─────────────────────────────────────────────────────
// Step 1 hands the user a ready-to-paste M365 Copilot prompt; step 2 accepts
// the JSON Copilot produced.
const importStep = ref(1);
const importMode = ref('text');        // 'text' | 'file'
const importText = ref('');
const importFilename = ref('');
const importFileContent = ref('');
const importLoading = ref(false);
const importResult = ref(null);
const importError = ref('');
const importPreview = ref(null);
const copilotPrompt = ref('');
const isDragOver = ref(false);

// One prompt per screen. Asking Copilot for a single view is much faster than
// the whole-project export and yields far fewer schema mistakes, because the
// schema it has to honour is a fraction of the size. Kanban is deliberately
// absent: it and the WBS are two renderings of one task tree, so a single
// work-breakdown export feeds both.
const PROMPT_KINDS = [
  { key: 'wbs', label: 'Strukturplan & Kanban', file: 'copilot_wbs',
    hint: 'Arbeitspakete als Baum — speist WBS und Kanban' },
  { key: 'faelligkeiten', label: 'Alle Termine & To-dos', file: 'copilot_faelligkeiten',
    hint: 'Querschnitt über ALLE Quellen — alles mit Datum, jede Flughöhe' },
  { key: 'risks', label: 'Risiken', file: 'copilot_risks',
    hint: 'Risikoregister' },
  { key: 'pendenzen', label: 'Todos', file: 'copilot_pendenzen',
    hint: 'Offene Punkte und Action Items ohne Datum' },
  { key: 'beschluesse', label: 'Todos & Beschlüsse', file: 'copilot_beschluesse',
    hint: 'Beschlussliste — Entscheide plus die Todos daraus' },
  { key: 'full', label: 'Alles (Gesamtexport)', file: 'copilot_state_export',
    hint: 'Einmaliger Rundum-Export — langsamer, fehleranfälliger' },
];

const promptKind = ref('faelligkeiten');
const _promptCache = new Map();

async function loadCopilotPrompt() {
  const kind = PROMPT_KINDS.find((k) => k.key === promptKind.value) || PROMPT_KINDS[0];
  if (_promptCache.has(kind.key)) {
    copilotPrompt.value = _promptCache.get(kind.key);
    return;
  }
  copilotPrompt.value = '';
  try {
    const resp = await fetch(`/static/prompts/${kind.file}.txt`);
    if (!resp.ok) return;
    const text = await resp.text();
    _promptCache.set(kind.key, text);
    // Guard against a slow fetch landing after the user picked another kind.
    if (promptKind.value === kind.key) copilotPrompt.value = text;
  } catch {
    /* prompt is a convenience — the paste step works without it */
  }
}

function currentJsonString() {
  return (importMode.value === 'text' ? importText.value : importFileContent.value).trim();
}

function computePreview(jsonStr) {
  if (!jsonStr.trim()) return null;
  let data;
  try {
    data = JSON.parse(jsonStr);
  } catch {
    return null;
  }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return null;
  const counts = {};
  for (const [k, v] of Object.entries(data)) {
    if (Array.isArray(v)) counts[k] = v.length;
  }
  return Object.keys(counts).length > 0 ? counts : null;
}

/** Re-validate whatever is currently staged, updating preview + inline error. */
function validateStaged() {
  const raw = currentJsonString();
  importResult.value = null;
  if (!raw) {
    importError.value = '';
    importPreview.value = null;
    return;
  }
  try {
    JSON.parse(raw);
    importError.value = '';
    importPreview.value = computePreview(raw);
  } catch (e) {
    importError.value = `Invalid JSON: ${e.message}`;
    importPreview.value = null;
  }
}

function openImport() {
  state.showImport = true;
  importStep.value = 1;
  importMode.value = 'text';
  importText.value = '';
  importFilename.value = '';
  importFileContent.value = '';
  importLoading.value = false;
  importResult.value = null;
  importError.value = '';
  importPreview.value = null;
  isDragOver.value = false;
  loadCopilotPrompt();
}

function closeImport() {
  // Drop any pending auto-close: a dialog the user reopened must not be shut
  // again by a timer the previous import left running.
  cancelAutoClose();
  state.showImport = false;
}

function clearImportForm() {
  importText.value = '';
  importFileContent.value = '';
  importFilename.value = '';
  importError.value = '';
  importPreview.value = null;
  importResult.value = null;
}

async function copyPrompt() {
  try {
    await navigator.clipboard.writeText(copilotPrompt.value);
    showToast('Prompt copied — paste it into M365 Copilot');
  } catch {
    showToast('Copy failed — select the prompt and copy manually', true);
  }
}

function readImportFile(file) {
  if (!file) return;
  importFilename.value = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  const reader = new FileReader();
  reader.onload = (ev) => {
    importFileContent.value = String(ev.target.result || '');
    validateStaged();
  };
  reader.readAsText(file);
}

function onImportFile(e) {
  readImportFile(e.target.files && e.target.files[0]);
}

function onDrop(e) {
  isDragOver.value = false;
  const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (file) {
    importMode.value = 'file';
    readImportFile(file);
  }
}

// Where each imported entity type shows up. Counts alone do not say what
// landed or where to look for it, which made a work-breakdown import feel
// like nothing had happened.
const ENTITY_DESTINATIONS = {
  tasks: { label: 'Arbeitspakete', screen: 'Strukturplan & Kanban' },
  schedule: { label: 'Termine & Fristen', screen: 'Aufgaben & Termine → Zeitstrahl' },
  beschluesse: { label: 'Beschlüsse', screen: 'Aufgaben & Termine → Beschlüsse' },
  risks: { label: 'Risiken', screen: 'Risks' },
  pendenzen: { label: 'Todos', screen: 'Aufgaben & Termine → Liste' },
  projects: { label: 'Projekte', screen: 'Projects' },
  plans: { label: 'Plan-Versionen', screen: 'nicht im Dashboard sichtbar' },
};

/** Turn an import result's entity counts into "3 Todos → Aufgaben & Termine". */
function describeImportDestinations(result) {
  const counts = result && result.entity_counts;
  if (!counts) return [];
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([type, n]) => ({
      type,
      count: n,
      label: (ENTITY_DESTINATIONS[type] || {}).label || type,
      screen: (ENTITY_DESTINATIONS[type] || {}).screen || type,
    }));
}

// Long enough for the green success panel to register as an answer rather
// than a flicker, short enough that nobody reaches for the close button first.
const IMPORT_AUTO_CLOSE_MS = 1200;
let _importCloseTimer = null;
// Counts imports, so a pending timer can tell whether it still belongs to the
// result on screen. Identity comparison against importResult.value does NOT
// work: assigning an object to a Vue ref stores a reactive Proxy, so
// `importResult.value === data` is false even for the very object just
// assigned, and the timer would never fire.
let _importSeq = 0;

function cancelAutoClose() {
  if (_importCloseTimer) {
    clearTimeout(_importCloseTimer);
    _importCloseTimer = null;
  }
}

/** Close the import dialog after a clean import, and only after a clean one.
 *
 * "Clean" excludes a partial success. The server can return ok with a list of
 * items it could not import, and that list exists only inside this dialog —
 * closing on top of it would report success while hiding what was dropped.
 * The whole point of auto-closing is to save a click on the boring path, not
 * to hurry someone past the one screen that says something went wrong.
 */
function maybeAutoClose(result, seq) {
  cancelAutoClose();
  if (!result || !result.ok) return;
  if (Array.isArray(result.errors) && result.errors.length) return;

  _importCloseTimer = setTimeout(() => {
    _importCloseTimer = null;
    // Only close if this is still the import the user is looking at: they may
    // have closed and reopened the dialog, or started another import.
    if (state.showImport && _importSeq === seq) closeImport();
  }, IMPORT_AUTO_CLOSE_MS);
}

async function runImport() {
  if (importLoading.value) return;
  // A second import must not be closed by the first one's pending timer.
  cancelAutoClose();
  const seq = ++_importSeq;
  const jsonStr = currentJsonString();
  if (!jsonStr) {
    importError.value = 'No JSON provided.';
    return;
  }
  try {
    JSON.parse(jsonStr);
  } catch (e) {
    importError.value = `Invalid JSON: ${e.message}`;
    return;
  }

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
      // The dialog says two things the toast did not: where each entity type
      // landed, and which individual items had problems. Closing must not
      // silently take either away — so the destinations move into the toast,
      // and a partial success keeps the dialog open (see maybeAutoClose).
      const where = describeImportDestinations(data)
        .map((w) => `${w.count} ${w.label} → ${w.screen}`)
        .join(' · ');
      showToast(
        `Import done — ${data.created} created, ${data.updated} updated`
        + (data.skipped ? `, ${data.skipped} skipped` : '')
        + (where ? `. ${where}` : '')
      );
      await refresh();
      maybeAutoClose(data, seq);
    }
  } catch (e) {
    importError.value = String(e.message || e);
  } finally {
    importLoading.value = false;
  }
}

// ── Keyboard shortcuts ─────────────────────────────────────────────────────
function onKeydown(e) {
  if (e.key === 'Escape') {
    state.showHelp = false;
    if (state.showCreate) closeCreate();
    if (state.showImport) closeImport();
    return;
  }

  // Ignore the single-letter shortcuts while typing in a form control
  const tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || e.target.isContentEditable) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  // Don't navigate away from an open dialog
  if (state.showImport || state.showHelp || state.showCreate) return;

  // Digits map to screens positionally in the canonical order, never in the
  // user's rearranged one: a key that moved with its row would be
  // unlearnable. Derived rather than hand-listed because the switch, the nav
  // items and the help dialog were three copies of this mapping and had
  // already drifted — 4 went to Todo while the help promised Termine &
  // Fristen, and 7 did nothing at all.
  if (/^[1-9]$/.test(e.key)) {
    const target = SCREENS[Number(e.key) - 1];
    if (target) goTo(target);
    return;
  }

  switch (e.key) {
    case 'r': refresh(); break;
    case 'd': toggleTheme(); break;
    case 'i': openImport(); break;
    case 'n': openCreate(); break;
    case '?': state.showHelp = true; break;
    default: break;
  }
}

// ── Root App component ─────────────────────────────────────────────────────
const App = {
  components: {
    OverviewScreen,
    ProjectListScreen,
    ProjectDetailScreen,
    ReviewsScreen,
    RisksScreen,
    WorkScreen,
  },
  setup() {
    // Surface API errors as a toast
    watch(() => state.error, (err) => { if (err) showToast(err, true); });

    // Live validation + preview as the user types or switches mode
    watch([importText, importMode], validateStaged);

    // Keep the URL hash in step with in-app navigation and vice versa
    function onHashChange() {
      const before = state.projectId;
      if (applyHash() && before !== state.projectId) fetchData(state.projectId);
    }

    onMounted(() => {
      applyTheme(theme.value);
      document.addEventListener('keydown', onKeydown);
      window.addEventListener('hashchange', onHashChange);
      applyHash();
      syncHash();
      fetchData(state.projectId);
      startPolling();
      loadCopilotPrompt();
      loadVersion();
    });

    onUnmounted(() => {
      document.removeEventListener('keydown', onKeydown);
      window.removeEventListener('hashchange', onHashChange);
      stopPolling();
    });

    // Counts drive both the sidebar badges and the overview tiles
    // `wbs` carries only the root nodes, so counting the array would report 6
    // for a 66-node breakdown. Walk the tree for the real total: without it,
    // importing a work breakdown changed no number anywhere on the dashboard
    // and looked like nothing had happened.
    function countTree(nodes) {
      return (nodes ?? []).reduce(
        (total, node) => total + 1 + countTree(node.children), 0
      );
    }

    const counts = computed(() => ({
      projects: state.data?.projects?.length ?? 0,
      timeline: state.data?.timeline?.length ?? 0,
      tasks: countTree(state.data?.wbs),
      pendenzen: state.data?.pendenzen?.length ?? 0,
      ablaufplan: state.data?.ablaufplan?.length ?? 0,
      decisions: state.data?.decisions?.length ?? 0,
      risks: state.data?.risks?.length ?? 0,
      reviews: state.data?.reviews?.length ?? 0,
    }));

    // No `shortcut` field: the digits are positional in this very list,
    // so storing them here would be a copy that can disagree with it.
    const navItems = computed(() => [
      { key: 'overview',  label: 'Overview',  icon: NAV_ICONS.overview,  count: null },
      { key: 'projects',  label: 'Projects',  icon: NAV_ICONS.projects,  count: counts.value.projects },
      { key: 'detail',    label: 'Timeline & WBS', icon: NAV_ICONS.detail,
        count: counts.value.tasks + counts.value.timeline },
      { key: 'work', label: 'Aufgaben & Termine', icon: NAV_ICONS.work,
        count: counts.value.ablaufplan + counts.value.pendenzen },
      { key: 'risks',     label: 'Risks',     icon: NAV_ICONS.risks,     count: counts.value.risks },
      { key: 'reviews',   label: 'Reviews',   icon: NAV_ICONS.reviews,   count: counts.value.reviews },
    ]);

    // Definitions stay canonical; the user's order is applied on top, so the
    // shortcut digits keep pointing at the same screens however the sidebar is
    // arranged — a key that moved with the row would be unlearnable.
    const orderedNavItems = computed(() => {
      const byKey = new Map(navItems.value.map((i) => [i.key, i]));
      return navOrder.value.map((k) => byKey.get(k)).filter(Boolean);
    });

    const draggingKey = ref(null);
    const dragOverKey = ref(null);

    function onNavDragStart(key, event) {
      draggingKey.value = key;
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        // Firefox refuses to start a drag unless some data is set.
        event.dataTransfer.setData('text/plain', key);
      }
    }

    function onNavDrop(key) {
      dropNav(draggingKey.value, key);
      draggingKey.value = null;
      dragOverKey.value = null;
    }

    // Built from the same canonical order the key handler indexes into, so
    // the help can no longer promise a binding the handler does not have.
    const shortcuts = computed(() => [
      ...navItems.value.map((item, i) => [String(i + 1), item.label]),
      ['r', 'Refresh data'],
      ['i', 'Import JSON'],
      ['n', 'Neu anlegen'],
      ['d', 'Toggle dark / light theme'],
      ['?', 'Show this help'],
      ['Esc', 'Close dialog'],
      ['Alt+↑/↓', 'Reihenfolge der Seitenleiste ändern'],
    ]);

    function focusTextarea() {
      nextTick(() => {
        const el = document.querySelector('[data-testid="raw-json-input"]');
        if (el) el.focus();
      });
    }

    function goToPasteStep() {
      importStep.value = 2;
      importMode.value = 'text';
      focusTextarea();
    }

    function selectPromptKind(key) {
      promptKind.value = key;
      loadCopilotPrompt();
    }

    // Where each imported entity type becomes visible. Without this the user
    // is told "66 updated" with no hint that the result lives two clicks away
    // on another screen.
    // Module-level: the dialog renders this list and runImport folds the same
    // list into the toast, so both must read one definition. See
    // describeImportDestinations().
    const importedWhere = computed(
      () => describeImportDestinations(importResult.value)
    );

    const activePromptHint = computed(() => {
      const kind = PROMPT_KINDS.find((k) => k.key === promptKind.value);
      return kind ? kind.hint : '';
    });

    return {
      state, theme, toast, navItems, shortcuts, counts, version,
      toggleTheme, refresh, goTo, selectProject, clearProject,
      // Delete & undo
      deleteTask, deleteProject, runUndo,
      // Import wizard
      openImport, closeImport, clearImportForm, onImportFile, onDrop,
      runImport, copyPrompt, goToPasteStep,
      promptKind, promptKinds: PROMPT_KINDS, selectPromptKind, activePromptHint,
      importedWhere,
      importStep, importMode, importText, importFilename, importLoading,
      importResult, importError, importPreview, copilotPrompt, isDragOver,
      // Sidebar order
      orderedNavItems, draggingKey, dragOverKey, moveNav,
      onNavDragStart, onNavDrop,
      // Create dialog
      openCreate, closeCreate, submitCreate, createKind, createForm,
      createBusy, createError, createValid, CREATE_KINDS,
    };
  },
  template: `
    <div class="hermes-layout">

      <!-- ── Topbar ─────────────────────────────────────────────────────── -->
      <nav class="hermes-navbar" role="banner">
        <span class="brand select-none">
          <span class="brand-mark" aria-hidden="true">H</span>
          HERMES
        </span>
        <span v-if="version"
              class="app-version"
              data-testid="app-version"
              :title="'HERMES Local Assistant version ' + version">v{{ version }}</span>
        <span class="text-slate-400 text-xs hidden sm:block">Local Dashboard</span>

        <span v-if="state.projectId" class="text-slate-300 text-xs hidden md:block">
          Project&nbsp;<strong class="font-mono">{{ state.projectId }}</strong>
        </span>

        <span class="flex-1"></span>

        <button
          class="tb-btn"
          @click="refresh"
          :disabled="state.loading"
          :aria-label="state.loading ? 'Refreshing…' : 'Refresh data (r)'"
          title="Refresh (r)"
        >
          <span v-if="state.loading" class="spinner" style="width:12px;height:12px;border-width:1.5px"></span>
          <span v-else aria-hidden="true">↻</span>
          <span class="hidden sm:block">Refresh</span>
        </button>

        <button
          class="tb-btn"
          @click="toggleTheme"
          :aria-label="'Toggle theme (d) — currently ' + theme"
          title="Toggle theme (d)"
        >{{ theme === 'dark' ? '☀' : '☾' }}</button>

        <button
          class="tb-btn"
          @click="state.showHelp = true"
          aria-label="Keyboard shortcuts (?)"
          title="Keyboard shortcuts (?)"
        >?</button>

        <button
          class="tb-btn"
          @click="openImport"
          aria-label="Import JSON (i)"
          title="Import JSON (i)"
        >Import JSON</button>

        <button
          class="tb-btn tb-btn-primary"
          @click="openCreate"
          aria-label="Neu anlegen (n)"
          title="Neu anlegen (n)"
          data-testid="open-create"
        >+ Neu</button>
      </nav>

      <!-- ── Sidebar ────────────────────────────────────────────────────── -->
      <aside class="hermes-sidebar" role="navigation" aria-label="Main navigation">
        <span class="sidebar-label">Navigate</span>
        <button
          v-for="item in orderedNavItems"
          :key="item.key"
          class="nav-btn"
          :class="{
            active: state.screen === item.key,
            'is-dragging': draggingKey === item.key,
            'is-drop-target': dragOverKey === item.key && draggingKey !== item.key,
          }"
          :aria-current="state.screen === item.key ? 'page' : undefined"
          :data-testid="'nav-' + item.key"
          draggable="true"
          @click="goTo(item.key)"
          @dragstart="onNavDragStart(item.key, $event)"
          @dragover.prevent="dragOverKey = item.key"
          @dragleave="dragOverKey === item.key && (dragOverKey = null)"
          @drop.prevent="onNavDrop(item.key)"
          @dragend="draggingKey = null; dragOverKey = null"
          @keydown.up.alt.prevent="moveNav(item.key, -1)"
          @keydown.down.alt.prevent="moveNav(item.key, 1)"
        >
          <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path :d="item.icon" />
          </svg>
          <span>{{ item.label }}</span>
          <span v-if="item.count !== null" class="nav-count">{{ item.count }}</span>
          <!-- Drag is not the only way in: Alt+↑/↓ moves the focused item, so
               the order is reachable without a pointer. -->
          <span class="nav-grip" aria-hidden="true" title="Ziehen zum Sortieren">⠿</span>
        </button>
      </aside>

      <!-- ── Main content ───────────────────────────────────────────────── -->
      <main class="hermes-main" role="main">
        <overview-screen
          v-if="state.screen === 'overview'"
          :data="state.data"
          :loading="state.loading"
          :error="state.error"
          :counts="counts"
          @navigate="goTo"
          @select-project="selectProject"
          @import="openImport"
        />
        <project-list-screen
          v-else-if="state.screen === 'projects'"
          :data="state.data"
          :loading="state.loading"
          :error="state.error"
          @select-project="selectProject"
          @delete-project="deleteProject"
        />
        <project-detail-screen
          v-else-if="state.screen === 'detail'"
          :data="state.data"
          :loading="state.loading"
          :error="state.error"
          :project-id="state.projectId"
          @back="clearProject"
          @changed="refresh"
        />
        <work-screen
          v-else-if="state.screen === 'work'"
          :data="state.data"
          :loading="state.loading"
          :error="state.error"
          @delete-task="deleteTask"
          @changed="refresh"
        />
        <risks-screen
          v-else-if="state.screen === 'risks'"
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
        <footer class="status-bar">
          <span>Last refresh: {{ state.lastRefresh || '—' }}</span>
          <span v-if="state.data?.generated_at">Server: {{ state.data.generated_at }}</span>
          <span v-if="state.data?.scope">Scope: {{ state.data.scope }}</span>
          <span v-if="state.loading" class="flex items-center gap-1">
            <span class="spinner" style="width:10px;height:10px;border-width:1.5px"></span> Updating&hellip;
          </span>
        </footer>
      </main>

      <!-- ── Create dialog ──────────────────────────────────────────────── -->
      <div v-if="state.showCreate"
           class="modal-overlay"
           @click.self="closeCreate"
           role="dialog" aria-modal="true" aria-label="Neu anlegen">
        <div class="modal-box" style="max-width:520px">
          <div class="flex justify-between items-start mb-4">
            <h3 class="modal-title">Neu anlegen</h3>
            <button class="modal-close" @click="closeCreate" aria-label="Schliessen">&times;</button>
          </div>

          <div class="prompt-kinds mb-4" role="group" aria-label="Was anlegen">
            <button v-for="k in CREATE_KINDS" :key="k.key"
                    class="prompt-kind"
                    :class="{ active: createKind === k.key }"
                    :data-testid="'create-kind-' + k.key"
                    @click="createKind = k.key; createError = ''">{{ k.label }}</button>
          </div>
          <p class="text-xs text-gray-400 mb-4">
            {{ (CREATE_KINDS.find(k => k.key === createKind) || {}).hint }}
          </p>

          <div v-if="createError" class="notice notice-error mb-3">{{ createError }}</div>

          <!-- Project needs only an id; it becomes a directory name. -->
          <template v-if="createKind === 'project'">
            <label class="form-row">
              <span class="form-label">Projekt-ID</span>
              <input class="text-input w-full" v-model="createForm.project_id"
                     placeholder="webshop-relaunch" data-testid="create-project-id"
                     @keydown.enter="submitCreate">
            </label>
            <p class="text-xs text-gray-400 mt-1">
              Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich — der Wert
              wird als Verzeichnisname verwendet.
            </p>
          </template>

          <template v-else>
            <label class="form-row">
              <span class="form-label">Titel</span>
              <input class="text-input w-full" v-model="createForm.title"
                     placeholder="Was ist zu tun?" data-testid="create-title"
                     @keydown.enter="submitCreate">
            </label>

            <label class="form-row">
              <span class="form-label">Verantwortlich</span>
              <input class="text-input w-full" v-model="createForm.owner"
                     placeholder="Rolle oder Name (optional)"
                     data-testid="create-owner">
            </label>

            <template v-if="createKind === 'todo'">
              <div class="form-grid">
                <label class="form-row">
                  <span class="form-label">Priorität</span>
                  <select class="filter-select w-full" v-model="createForm.priority"
                          data-testid="create-priority">
                    <option value="blocker">Blocker</option>
                    <option value="high">Hoch</option>
                    <option value="medium">Mittel</option>
                    <option value="low">Tief</option>
                  </select>
                </label>
                <label class="form-row">
                  <span class="form-label">Termin</span>
                  <input class="text-input w-full" type="date"
                         v-model="createForm.due_date" data-testid="create-due">
                </label>
              </div>
              <label class="form-row">
                <span class="form-label">Beschreibung</span>
                <textarea class="text-input w-full" rows="2"
                          v-model="createForm.description"
                          placeholder="Optional"></textarea>
              </label>
            </template>

            <div v-else class="form-grid">
              <label class="form-row">
                <span class="form-label">Art</span>
                <select class="filter-select w-full" v-model="createForm.node_kind"
                        data-testid="create-node-kind">
                  <option value="task">Aufgabe</option>
                  <option value="deliverable">Liefergegenstand</option>
                  <option value="milestone">Meilenstein</option>
                </select>
              </label>
              <label class="form-row">
                <span class="form-label">Status</span>
                <select class="filter-select w-full" v-model="createForm.status">
                  <option value="open">To Do</option>
                  <option value="blocked">Blockiert</option>
                  <option value="closed">Erledigt</option>
                </select>
              </label>
            </div>
          </template>

          <div class="modal-actions">
            <button class="btn" @click="closeCreate">Abbrechen</button>
            <button class="btn btn-primary"
                    :disabled="!createValid || createBusy"
                    data-testid="create-submit"
                    @click="submitCreate">
              <span v-if="createBusy" class="spinner"
                    style="width:11px;height:11px;border-width:1.5px"></span>
              Anlegen
            </button>
          </div>
        </div>
      </div>

      <!-- ── Help modal ─────────────────────────────────────────────────── -->
      <div v-if="state.showHelp"
           class="modal-overlay"
           @click.self="state.showHelp = false"
           role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
        <div class="modal-box" style="max-width:380px">
          <div class="flex justify-between items-center mb-4">
            <h2 class="modal-title">Keyboard Shortcuts</h2>
            <button class="modal-close" @click="state.showHelp = false" aria-label="Close help">&times;</button>
          </div>
          <table class="w-full text-sm">
            <tbody>
              <tr v-for="[key, desc] in shortcuts" :key="key">
                <td class="py-1.5 pr-4 w-16"><kbd class="kbd">{{ key }}</kbd></td>
                <td class="py-1.5">{{ desc }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ── Import JSON wizard ─────────────────────────────────────────── -->
      <div v-if="state.showImport"
           class="modal-overlay"
           @click.self="closeImport"
           role="dialog"
           aria-modal="true"
           aria-label="Import JSON data"
           data-testid="json-import-modal">
        <div class="modal-box" style="max-width:640px">

          <div class="flex justify-between items-start mb-4">
            <div>
              <div class="modal-step">Step {{ importStep }} of 2</div>
              <h2 class="modal-title">
                {{ importStep === 1 ? 'Get the Copilot prompt' : 'Import the JSON' }}
              </h2>
            </div>
            <button class="modal-close" @click="closeImport" aria-label="Close import dialog">&times;</button>
          </div>

          <!-- ── Step 1: hand over the Copilot prompt ── -->
          <template v-if="importStep === 1">
            <p class="text-sm" style="color:var(--c-text-muted)">
              Pick what to export, then copy the prompt into
              <strong style="color:var(--c-text)">M365 Copilot</strong>. It replies
              with JSON you paste back here in step 2. One view at a time is
              faster and far more reliable than the whole-project export.
            </p>

            <div class="prompt-kinds" role="group" aria-label="What to export">
              <button v-for="kind in promptKinds"
                      :key="kind.key"
                      class="prompt-kind"
                      :class="{ active: promptKind === kind.key }"
                      :aria-pressed="promptKind === kind.key"
                      :data-testid="'prompt-kind-' + kind.key"
                      @click="selectPromptKind(kind.key)">{{ kind.label }}</button>
            </div>
            <div class="text-xs mt-1" style="color:var(--c-text-faint)"
                 data-testid="prompt-kind-hint">{{ activePromptHint }}</div>

            <pre data-testid="copilot-prompt-text"
                 class="prompt-block mt-3">{{ copilotPrompt || 'Loading prompt…' }}</pre>

            <ol class="steps-list">
              <li>Copy the prompt</li>
              <li>Paste it into M365 Copilot and send</li>
              <li>Copy Copilot's JSON reply</li>
              <li>Return here and continue to step 2</li>
            </ol>

            <div class="modal-actions">
              <button class="btn"
                      @click="copyPrompt"
                      data-testid="copy-prompt-btn"
                      title="Copy the prompt so you can paste it into Copilot">
                Copy prompt
              </button>
              <span class="flex-1"></span>
              <button class="btn" @click="closeImport">Cancel</button>
              <button class="btn btn-primary"
                      @click="goToPasteStep"
                      data-testid="import-next-btn">
                Next: paste JSON &rarr;
              </button>
            </div>
          </template>

          <!-- ── Step 2: accept the JSON ── -->
          <template v-else>
            <div class="segmented mb-3" role="group" aria-label="Import source">
              <button :class="{ active: importMode === 'text' }"
                      @click="importMode = 'text'"
                      data-testid="mode-text">Paste JSON</button>
              <button :class="{ active: importMode === 'file' }"
                      @click="importMode = 'file'"
                      data-testid="mode-file">Upload file</button>
            </div>

            <label class="sr-only" for="raw-json-input">Raw JSON</label>
            <textarea
              v-show="importMode === 'text'"
              id="raw-json-input"
              v-model="importText"
              class="json-textarea"
              placeholder='{"risks": [{"title": "Example risk", "severity": "high"}]}'
              spellcheck="false"
              data-testid="raw-json-input"
            ></textarea>

            <div v-show="importMode === 'file'"
                 class="drop-zone"
                 :class="{ 'is-dragover': isDragOver }"
                 data-testid="json-drop-zone"
                 @click="$el.querySelector('#json-file-input').click()"
                 @dragover.prevent="isDragOver = true"
                 @dragleave.prevent="isDragOver = false"
                 @drop.prevent="onDrop">
              <input id="json-file-input"
                     type="file"
                     accept=".json,application/json"
                     @change="onImportFile"
                     style="display:none"
                     data-testid="json-file-input">
              <span style="color:var(--c-primary);font-weight:600">Choose a JSON file</span>
              <span v-if="importFilename" data-testid="import-filename">{{ importFilename }}</span>
              <span v-else>or drag and drop it here</span>
            </div>

            <!-- Live preview of what will be imported -->
            <div v-if="importPreview" class="notice notice-info" data-testid="import-preview">
              <strong>Will import:</strong>
              <span v-for="(count, type) in importPreview" :key="type" class="ml-2">
                {{ type }} <strong>{{ count }}</strong>
              </span>
            </div>

            <!-- Inline error (invalid JSON, server rejection) -->
            <div v-show="importError"
                 class="notice notice-error"
                 role="alert"
                 aria-live="assertive"
                 data-testid="import-error"
                 id="json-error">{{ importError }}</div>

            <div v-show="importLoading"
                 class="notice notice-info flex items-center gap-2"
                 data-testid="import-progress">
              <span class="spinner" style="width:12px;height:12px;border-width:1.5px"></span>
              Importing&hellip;
            </div>

            <!-- Result summary -->
            <div v-show="importResult"
                 class="notice"
                 :class="importResult && importResult.ok ? 'notice-success' : 'notice-error'"
                 role="status"
                 aria-live="polite"
                 data-testid="import-result">
              <template v-if="importResult">
                <span v-if="importResult.ok">
                  Successfully imported — {{ importResult.created }} created,
                  {{ importResult.updated }} updated<template v-if="importResult.skipped">,
                  {{ importResult.skipped }} skipped</template>.
                </span>
                <span v-else>Import failed.</span>
                <!-- Counts alone do not say what landed or where to look for
                     it, which made a work-breakdown import feel like nothing
                     had happened. Name the screen each entity type shows on. -->
                <div v-if="importResult.ok && importedWhere.length"
                     class="mt-1"
                     data-testid="import-where">
                  <span v-for="w in importedWhere" :key="w.type" class="block">
                    {{ w.count }} {{ w.label }} → {{ w.screen }}
                  </span>
                </div>
              </template>
            </div>

            <div v-if="importResult && importResult.errors && importResult.errors.length"
                 class="notice notice-warn"
                 data-testid="import-errors">
              <strong>{{ importResult.errors.length }} item(s) reported a problem:</strong>
              <ul>
                <li v-for="e in importResult.errors.slice(0, 5)" :key="e">{{ e }}</li>
                <li v-if="importResult.errors.length > 5">
                  +{{ importResult.errors.length - 5 }} more
                </li>
              </ul>
            </div>

            <div class="modal-actions">
              <button class="btn"
                      @click="importStep = 1"
                      data-testid="import-back-btn">&larr; Back</button>
              <button class="btn"
                      @click="clearImportForm"
                      data-testid="clear-form-btn">Clear</button>
              <span class="flex-1"></span>
              <button class="btn" @click="closeImport" data-testid="import-cancel">Cancel</button>
              <button class="btn btn-primary"
                      @click="runImport"
                      :disabled="importLoading"
                      data-testid="import-submit-btn">
                {{ importLoading ? 'Importing…' : 'Import' }}
              </button>
            </div>
          </template>
        </div>
      </div>

      <!-- ── Toast ──────────────────────────────────────────────────────── -->
      <div v-if="toast.message"
           class="toast"
           :class="{ 'is-error': toast.isError }"
           role="alert"
           aria-live="assertive">
        <span>{{ toast.message }}</span>
        <button v-if="toast.undo"
                class="toast-undo"
                data-testid="toast-undo"
                @click="runUndo">Rückgängig</button>
      </div>
    </div>
  `,
};

// ── Mount ──────────────────────────────────────────────────────────────────
// Sub-components shared across screens are registered globally so screen
// templates can use them without repeating a local components: {} block.
// WbsNodeItem in particular is recursive and *must* be global.
const vueApp = createApp(App);
vueApp.component('WbsNodeItem', WbsNodeItem);
vueApp.component('WbsTab', WbsTab);
vueApp.component('KanbanTab', KanbanTab);
vueApp.mount('#app');
}());
