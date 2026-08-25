# HERMES Local Assistant — Master Documentation

> **Single source of truth.** This is the one canonical document for the
> hermes-assistant project. It merges every former standalone doc (project
> spec, architecture, web/chat, Copilot import, security, testing, deployment,
> status reports, implementation plans) into one reference-and-operational
> guide. Do **not** re-scatter documentation into separate `.md` files — extend
> the relevant section here instead.
>
> **Status:** Phase 5 complete · Ready for staging deployment · Fully-local
> (Ollama, no cloud) · Single-user · Async-tolerant
> **Last consolidated:** 2026-08-22

---

## Table of Contents

- [Part 0 — Overview & Quick Start](#part-0--overview--quick-start)
- [Part 1 — Project Specification & Build Guide](#part-1--project-specification--build-guide)
  - [I — Capability Requirements](#i--capability-requirements-the-what)
  - [I-B — Adaptive Project-Type Taxonomy](#i-b--adaptive-project-type-taxonomy-the-domain-backbone)
  - [I-C — Quality-Review / Rubric System](#i-c--quality-review--rubric-system-designed-from-scratch)
  - [II — Hardware Feasibility](#ii--hardware-feasibility-the-constraint)
  - [III — Architecture](#iii--architecture-decided-by-the-hardware)
  - [IV — Build Contract for Claude Code CLI](#iv--build-contract-for-claude-code-cli)
  - [IV-B — Scheduling & Calendar Export (ICS)](#iv-b--scheduling--calendar-export-ics)
  - [VI — Phased Build Backlog](#vi--phased-build-backlog-acceptance-criteria-driven)
  - [VII — Guardrails, Thresholds, Caveats](#vii--guardrails-decision-thresholds-caveats)
  - [IV-I…IV-L — Later Spec Amendments](#iv-iiv-l--later-spec-amendments-jul-2026)
- [Part 2 — Web Dashboard & Chat Assistant](#part-2--web-dashboard--chat-assistant)
- [Part 3 — Copilot Import (Prompt, Feature, Example)](#part-3--copilot-import-prompt-feature-example)
- [Part 4 — Security Model & Guardrails](#part-4--security-model--guardrails)
- [Part 5 — Testing (Strategy, Simulations, Coverage)](#part-5--testing-strategy-simulations-coverage)
- [Part 6 — Deployment & Operations](#part-6--deployment--operations)
- [Part 7 — Status & Quality Reports](#part-7--status--quality-reports)
- [Part 8 — Coder-Ready Implementation Plans](#part-8--coder-ready-implementation-plans)

---

# Part 0 — Overview & Quick Start

A fully-local AI assistant that helps junior consultants operate at senior level
under the HERMES 2022 Swiss project-management method.

- **Fully local:** Ollama-only, no cloud reasoning, no confidential data leaves the box
- **Structured:** Rubric-driven quality review, grammar-constrained JSON, explicit acceptance criteria
- **Hardware-aware:** Designed for i7-1265U + 32–64 GB RAM (MoE models, Q4 quantization, async job queue); local POC on M4 / 16 GB
- **Asynchronous:** Heavy passes run overnight via a SQLite job queue

## Quick Start

```bash
bash scripts/bootstrap.sh                 # Install deps, pull models
python -m hermes_assistant.cli --help     # See available CLI commands
bash scripts/start-web.sh                 # Start the web dashboard on :8000
```

For full installation, ops, and troubleshooting, see [Part 6 — Deployment & Operations](#part-6--deployment--operations).

## Building

Phases are implemented in order (Phase 0 → Phase 5). Keep `ruff check`,
`mypy src`, and `pytest -q` green at each step.

```bash
pytest -q          # mocked Ollama tests green
ruff check .       # lint clean
mypy src           # types clean
```

## License

MIT

---

# Part 1 — Project Specification & Build Guide

> **One document, three jobs:** (1) define *what* the system must do to help a
> junior consultant operate at senior level under HERMES 2022, (2) define *what
> is feasible* on the target hardware, and (3) give **Claude Code CLI**
> everything it needs to scaffold and build the system.
>
> **Status:** Specification v1.0 · Fully-local (Ollama, no cloud) · Single-user · Async-tolerant
> **Owner:** Project lead (Junior Consultant / Project Engineer, A+W Progress)
> **Target machine (prod):** HP ZBook Firefly 14 G9 — i7-1265U, 32 GB RAM, RTX A500 4 GB (dGPU)
> **Target machine (local POC):** MacBook Air M4 — 16 GB RAM, Apple Silicon GPU

**How to read this part**

- **I–II** = the *why* and *what* (capabilities + hardware reality). Read once for context.
- **III** = the *how* (architecture decided by the hardware).
- **IV onward** = the **build contract for Claude Code**: repo layout, `CLAUDE.md`, interface contracts, phased backlog with acceptance criteria, and explicit guardrails.
- Anything in a `code block` is meant to be created or run verbatim. Anything tagged **[AC]** is an acceptance criterion Claude Code must satisfy before moving on.

## I — Capability Requirements (the *what*)

### 1. Context & hard constraints

The system is a personal, fully-local AI assistant that helps a junior project lead plan, organize, and quality-check work to a senior standard, inside the **HERMES 2022** Swiss federal project-management method. A+W Progress is an ICT / risk-and-security consultancy; the majority of its project references are confidential. That confidentiality posture makes **fully-local execution mandatory**.

**Hard constraints (non-negotiable):**

1. **Fully local.** All reasoning, planning, retrieval, and quality-checking run on local hardware via Ollama. No cloud reasoning, no anonymized cloud calls, no confidential content leaving the machine. (Cloud M365 Copilot may remain a *non-confidential* drafting tool only — it must never receive confidential content.)
2. **Fresh install**, single user, single laptop to start.
3. **Long inference time is acceptable** — design for latency tolerance, not speed.
4. **Adaptive, project-phase-driven — HERMES 2022 is an *optional reference lens*, not a mandatory backbone.** Projects here do not necessarily follow HERMES; they are IT-adaptation projects of varying sub-type. The assistant works through whatever phases a project *actually needs* ("do what's necessary") and pulls HERMES outcomes/checklists in via RAG only when a defensible reference is useful. See §3 and I-B.

**Priority order of goals:** (1) close the **experience gap** [top], (2) plan & organize like a senior, (3) quality-check completed outputs.

### 2. The junior→senior experience gap (what we are actually encoding)

The gap is **judgment, ownership, and foresight**, not knowledge. A junior executes within a given frame; a senior *creates the frame*: defines the goal, breaks down the problem, names the unknowns, picks a "good enough" path, sets stop criteria and metrics, anticipates risk, and manages stakeholders. Much of this is **tacit knowledge** (expert pattern-matching à la Klein's Recognition-Primed Decision model) that "cannot be captured through words alone."

Therefore the tool cannot simply *be* senior. It must **elicit** senior judgment through structured questioning and **encode** it as reusable rubrics, checklists, and failure-mode libraries. Structure is the product.

### 3. Generic phases & HERMES 2022 as an optional lens

Projects are structured onto **flexible generic phases** the project actually needs — **Initiation/Analysis → Concept/Design → Realization/Implementation → Rollout/Deployment → Closure** — chosen adaptively rather than imposed. HERMES 2022 is pulled in **only as an optional reference** (via RAG) when the junior wants a defensible standard to cite. HERMES itself validates this adaptive stance: it offers classic/agile/hybrid solution creation, a *Szenarien + Sizing + Tailoring* mechanism to scale method weight to project characteristics, and treats "Adaption" as a first-class project type.

When referenced, the useful HERMES elements are:
- **Phases (classic):** Initialisierung → Konzept → Realisierung → Einführung → Abschluss; **(agile/hybrid):** Initialisierung → Umsetzung → Abschluss.
- **Milestones = quality gates** (strengthened control function in 2022).
- **Outcomes (Ergebnisse):** documents or states; some marked as **minimum required ("X")**.
- **Roles:** sponsor (Auftraggeber), project management (Projektleiter), user rep (Anwendervertreter); optional quality/risk manager, ISDS (security) manager, test manager.
- **Checklists** are already first-class HERMES artifacts (review steps, release criteria, responsible parties, date).

The tool's job is **not** to enforce HERMES but to **instantiate the phases/deliverables a project needs**, optionally cross-referencing HERMES outcomes as a lens. The domain backbone is the **project-type taxonomy** (I-B), not HERMES.

### 4. Prioritized capability list

Tags: **[Must]/[Nice]** and **[Local-OK]** / **[Hard-Local]** (needs structural workarounds).

**Goal 1 — Plan & organize like a senior**
1. **HERMES project scaffolder** [Must][Local-OK] — from a project description, propose scenario (sizing/tailoring), generate phase/milestone/outcome/role structure, list minimum-required documents per module. Output structured Markdown + JSON (grammar-constrained).
2. **Socratic intake interview** [Must][Local-OK] — before planning, interrogate for objectives, scope boundaries, stop criteria, stakeholders, constraints, success metrics, known unknowns. *Primary experience-gap closer.*
3. **Completeness & dependency checker** [Must][Local-OK] — cross-check plan against HERMES required outcomes and dependencies; flag missing deliverables, ungated phases, unassigned roles.
4. **Stakeholder / RACI + political-awareness map** [Must][Local-OK].
5. **Risk anticipation & pre-mortem at planning time** [Must][Local-OK] — risk register in A+W risk language (RAMS / EN 50126 vocabulary: reliability, availability, maintainability, safety; residual risk, risk-reducing measures).
6. **Scheduling & critical-path drafting** [Nice][Hard-Local] — ordering is local-OK; push numeric date/effort math to a deterministic tool, not the model's head.
7. **"What a junior wouldn't think to ask" prompt library** [Must][Local-OK].

**Goal 2 — Quality-check completed outputs**
8. **Rubric-based critic/judge** [Must][Local-OK] — score against explicit HERMES/company rubrics; chain-of-thought-before-score; bias controls; self-consistency (3× + reconcile). Output dimension scores + located findings + pass/fail vs acceptance criteria.
9. **Critique → revise loop** [Must][Local-OK].
10. **Consistency & MECE checker** [Must][Local-OK] — contradictions, overlaps/gaps, terminology drift, number mismatches.
11. **Red-team / "client auditor" review** [Must][Local-OK].
12. **"So-what" / insight-vs-noise critique** [Must][Local-OK].
13. **Grounded fact/claim checking against sources** [Must][Hard-Local] — RAG-grounded; keep human sign-off, never auto-approve.
14. **Multi-model panel for high-stakes reviews** [Nice][Hard-Local] — diverse-family panel; only where stakes justify the compute.

**Goal 3 — Close the experience gap (top priority)**
15. **Auto-checklist generator** [Must][Local-OK] — turn rubrics + HERMES checklists into per-deliverable acceptance checklists with explicit pass/fail criteria.
16. **Assumption surfacing & decision log** [Must][Local-OK] — force implicit assumptions explicit; maintain traceable decision/assumption log.
17. **Failure-mode library ("where juniors go wrong")** [Must][Local-OK] — curated, RAG-backed, growing.
18. **Tacit-knowledge capture loop** [Nice][Local-OK] — Critical-Decision-Method-style prompts to extract senior reasoning into reusable rubrics over time.
19. **"What good looks like" exemplars** [Must][Local-OK] — retrievable gold-standard outcome examples + annotated templates per HERMES document type.

**Cross-cutting platform capabilities**
- Document ingestion (PDF/Office/Markdown) into a local vector store [Must][Local-OK].
- Grammar-constrained JSON / tool-calling with schema validation + auto-retry [Must][Local-OK].
- HITL quality gates mapped to HERMES milestones [Must][Local-OK].
- Traceability / audit log of agent decisions and retrievals [Must][Local-OK].
- Fully-local enforcement — no outbound calls [Must][Local-OK].

### 5. Encoded senior-review methodologies

| Method | What it does | Encoded as |
|---|---|---|
| **Pre-mortem** (Klein) | Imagine it already failed; work backward to causes (improves reason-finding ~30%) | Automated pass: "assume this failed catastrophically — list every reason," map to mitigations/risk register |
| **Red-team review** | Adversarial reviewer emulates client/auditor | Critic agent persona scoring vs acceptance criteria |
| **MECE** | No overlaps, no gaps in structures | Structural-consistency pass |
| **"So-what" / Pyramid / ghost-deck** | Every section drives a decision; lead with the takeaway | Insight-vs-noise + storyline-completeness check |
| **QC checklist w/ explicit acceptance criteria** | Precise pass/fail, responsible person, evidence, non-conformance + corrective action | Bridge between HERMES checklists and the automated rubric-judge |

## I-B — Adaptive Project-Type Taxonomy (the domain backbone)

> Replaces a rigid methodology with an **extensible registry**. Projects are all IT-adaptation type, with sub-types (KVM systems, ISDS-Analyse, network adaptation, …). Each sub-type is **data, not code** — new types are added without touching logic. This registry is the join between *planning* (what to produce) and *review* (how to judge it).

### 4A. The taxonomy data structure

Each project sub-type is a self-contained record the planner composes onto the generic phases (§3). The `review_rubrics` field links directly to the rubrics in I-C so planning and quality-review share one taxonomy.

```yaml
project_type:
  id: isds_analyse
  label: "ISDS-Analyse (InfoSec & Data-Protection Analysis)"
  parent: it_adaptation
  typical_phases: [initiation, analysis, concept]    # the subset it actually needs
  sizing_questions:
    - "Are personal data processed? (may trigger DSFA)"
    - "Elevated protection need per Schutzbedarfsanalyse?"
  typical_deliverables:
    - {id: schutzbedarf, label: "Schutzbedarfsanalyse", phase: analysis}
    - {id: risikoanalyse, label: "Risikoanalyse", phase: analysis}
    - {id: isds_konzept, label: "ISDS-Konzept", phase: concept, condition: "elevated_need"}
  typical_risks:
    - "Unklare Rechtsgrundlage / missing legal basis"
    - "Cloud / CLOUD-Act exposure for special personal data"
  typical_stakeholders: [ISBO, Auftraggeber, Geschäftsprozessverantwortlicher, Datenschutzberater]
  review_rubrics: [isds_analyse]                      # → I-C rubric
  reference_lens: [ncsc_p042, hermes_2022]            # optional, pulled via RAG
```

A `ProjectPlan` = chosen sub-type(s) × selected phases × instantiated deliverables/risks/stakeholders, all user-editable. Implemented as `src/hermes_assistant/hermes/project_types.py` (a loader over `project_types/*.yaml` seed files) — this **supersedes** the earlier `scenarios.py`/`minimum_docs.py` idea (those assumed rigid HERMES scenarios).

### 4B. Seed sub-type checklists (what a *good* one contains)

**ISDS-Analyse** (Swiss; per NCSC/BACS Vorgabe **P042** + cantonal IDG/DSFA):
- Beschreibung des Informatikschutzobjekts (scope, data, architecture sketch, comms matrix, responsibilities).
- Schutzbedarfsanalyse across **Vertraulichkeit, Integrität, Verfügbarkeit, Nachvollziehbarkeit** per asset, **each with written justification**.
- Risikoanalyse (likelihood × impact); explicit **Restrisiken**.
- Sicherheitsmassnahmen (technical + organizational), **each traceable to a risk**; Rollen-/Berechtigungskonzept.
- **DSFA** per Art. 22 DSG when high risk; Rechtsgrundlagenanalyse.
- Notfallkonzept / recovery / decommissioning where applicable.
- **Restrisiko-Akzeptanz** signed by named accountable roles; ISBO review before go-live; validity ≤ 5 years; signatures before Betriebsaufnahme.

**KVM-system concept** (Keyboard-Video-Mouse console switching, data-center context):
- Scope / number of managed targets & consoles; **local vs KVM-over-IP** access model; user/role count & concurrency (single/multi-user/matrix); **security** (MFA, encryption, NIAP-certified secure KVM for data separation, NAC/AAA e.g. Cisco ISE); audit logging; cabling/video (resolution, latency, switching speed); rack/power; remote access; failover/redundancy; management-software integration (e.g. DSView).

**Network-adaptation concept** (HLD + LLD):
- Current-state + scope/boundaries; requirements (capacity/performance/growth).
- **HLD:** architecture, components/interfaces, topology, segmentation/VLAN strategy, redundancy/resilience, security zones/firewall placement, scalability.
- **LLD:** device models/hostnames, IP addressing, routing (OSPF/BGP), VLAN/tagging detail, ACLs/VPN/encryption, QoS, failover, monitoring/automation (Ansible, telemetry), BOM.
- Implementation/migration + rollback plan; risk plan; validation/test plan.

### 4C. Adaptive planning behavior

Both intake and planning are **model-generated and adaptive** ("what's necessary for *this* project"), not template-filling. The planner: picks the sub-type(s), proposes only the phases the project needs, instantiates that sub-type's deliverables/risks/stakeholders, lets the junior add/remove, and runs the completeness/dependency check against the sub-type checklist (not against a forced HERMES structure). A few sizing questions (criticality, personal-data involvement, regulatory exposure) drive the "what's necessary" decision.

## I-C — Quality-Review / Rubric System (designed from scratch)

> The current Copilot-agent review yields poor, non-qualitative results. This subsystem replaces it. **Design principle: a reviewer is a *compiler-executor*, not a chatbot** — encode senior standards as a versioned rubric of atomic, located, evidence-anchored checks; execute each with reasoning-before-verdict; aggregate across samples into a defensible pass/fail. This is the highest-value subsystem in the project.

### 4D. Why structured rubrics beat free-form critique (esp. for weak local models)
A general "review this" prompt makes a weak model both *invent* the standard and *apply* it every call — compounding error, drifting standards, and rewarding surface fluency. Fixing the standard (locked checklist) + binary decisions + reasoning-before-score + multi-sampling each removes a distinct failure mode. Evidence: checklist decomposition raised cross-model agreement **+0.45** and human correlation **+0.10** while cutting variance (CheckEval); self-consistency on gpt-oss-20b enabled **40–90%** less human grading time and flags its own low-confidence errors (SURE study); CoT-before-score adds the largest single prompt-level gain (G-Eval). These techniques are the reason a 20–30B local model can out-review the Copilot agent.

### 4E. Runtime pattern (one review pass)
1. **Retrieve** the rubric YAML for the deliverable type + optional reference passages (RAG grounding).
2. **Decompose** into atomic checks; keep ≤6–7 fields per LLM call (small models lose accuracy on wide schemas).
3. **CoT-before-score**: require rationale + **verbatim evidence quote/location** *before* the verdict field (ordering matters).
4. **Self-consistency**: sample each check 3–7× (start 5), majority-vote, record agreement as `confidence`, route low-agreement findings to the human.
5. **Validate** every response against a Pydantic schema via Ollama `format` (flat schema, ≤3 nesting levels).
6. **Aggregate** atomic findings → per-dimension rollups → single pass/fail verdict.

### 4F. Evaluation dimensions
Completeness · Correctness/factual accuracy · Internal consistency · Traceability · Clarity/unambiguity · Actionability · Risk coverage · Stakeholder fit · Evidence/grounding · Design-freedom (for requirements). Each becomes a rubric *category* holding atomic binary checks. Express acceptance criteria as concrete pass/fail (e.g. "Is **each** residual risk explicitly accepted by a named role?"), never adjectives ("is the risk analysis good?"). Rubric wording is a first-class reliability lever — rewording one ambiguous item cut a mis-scoring rate from 45%→14% (SURE).

### 4G. Judge-bias mitigations (bake in)
- **Self-enhancement bias → use a *different model family to judge than to draft*.** Draft with Qwen3-30B-A3B (thinking), review with gpt-oss-20b, or vice-versa. This is the cleanest mitigation and you have both models.
- **Verbosity bias** → binary checks (length-neutral); never reward length.
- **Position bias** → when comparing/ranking, swap positions and accept only consistent verdicts.
- **Leniency/severity** → calibrate against a small human-graded gold set; anchor each level with examples.
- **Surface-fluency bias** → require an evidence quote per finding.

### 4H. Rubric schema (YAML, senior-authored, version-controlled)
```yaml
rubric_id: isds_analyse
version: 1.3.0
deliverable_type: ISDS-Analyse
applies_to_phases: [analysis, concept]
references: [ncsc_p042, cantonal_idg]      # via RAG
scoring:
  scale: binary_plus                        # pass / partial / fail per criterion
  verdict_rule: "fail if any blocker; majors>2 => fail; else pass_with_comments"
criteria:
  - id: C1
    dimension: completeness
    text: "Schutzbedarfsanalyse covers confidentiality, integrity, availability AND traceability for every in-scope object."
    check_type: binary
    severity_if_failed: major
    evidence_required: true
  - id: C2
    dimension: risk_coverage
    text: "Each residual risk is explicitly accepted by a named accountable role."
    check_type: binary
    severity_if_failed: blocker
    evidence_required: true
anti_patterns:                              # reusable failure-mode library
  - id: AP1
    name: "Schutzbedarf asserted without justification"
    detector: "Classification stated with no Begründung."
    severity: major
```

### 4I. Finding output schema (Pydantic, enforced via Ollama `format`)
```python
class Severity(str, Enum):
    blocker = "blocker"   # blocks sign-off / acceptance
    major   = "major"     # significant gap, rework before sign-off
    minor   = "minor"     # improvement, non-blocking

class Verdict(str, Enum):
    pass_ = "pass"; pass_with_comments = "pass_with_comments"; fail = "fail"

class Finding(BaseModel):
    criterion_id: str
    dimension: str
    result: Literal["pass", "partial", "fail"]
    severity: Optional[Severity]
    location: str            # where in the document
    evidence_quote: str      # verbatim text
    rationale: str           # CoT — appears BEFORE result in prompt order
    fix_suggestion: str      # concrete, actionable
    confidence: float        # = self-consistency sample agreement

class ReviewResult(BaseModel):
    rubric_id: str; rubric_version: str; deliverable_type: str
    findings: List[Finding]
    dimension_summary: Dict[str, str]
    blockers: int; majors: int; minors: int
    verdict: Verdict; verdict_rationale: str
```

### 4J. Capturing senior tacit standards
The rubric *is* the capture mechanism: harvest a senior's recurring past review comments → convert each into a positive criterion or an **anti-pattern** entry; anchor each criterion with pass/fail examples; add a **reference exemplar** ("a score-5 ISDS analysis contains…") for reference-guided judging (Prometheus pattern lifted a 13B model to GPT-4-level agreement); version the rubric like code. Calibrate on a **gold set** of 10–20 human-reviewed deliverables per type, target judge–human κ ≥ 0.6, and fix rubric wording where model and human disagree.

## II — Hardware Feasibility (the *constraint*)

### 6. The decisive facts about the target machine

- **CPU:** i7-1265U — 15 W, 2 P-cores + 8 E-cores, 12 threads. Low-power U-series.
- **RAM:** 64 GB (the machine's real superpower — lets you *load* big models). *(Prod baseline later revised to 32 GB; see IV-I.)*
- **GPU:** Intel Iris Xe **integrated only**, no dedicated VRAM. The "32 GB display memory" is shared system RAM.
- **Bottleneck:** **memory bandwidth** (~50–77 GB/s real-world dual-channel), not cores. Token generation at batch 1 is bandwidth-bound — every token reads the active weights from RAM. ~5 threads already saturate the bus; more threads can *hurt*.

### 7. What this means for model choice

- **Dense models scale brutally badly.** Realistic CPU-only Q4_K_M generation estimates on this class of chip:
  - 3–4B dense: ~10–18 tok/s (usable)
  - 7–8B dense: ~3–6 tok/s (tolerable short answers)
  - 14B dense: ~2–3 tok/s (batch-only)
  - 24B dense: ~1.5–2.5 tok/s (batch-only)
  - **30–32B dense: ~1–2 tok/s (effectively unusable interactively)**
- **MoE with low active params is the unlock.** Generation speed tracks *active* (not total) parameters:
  - **Qwen3-30B-A3B** (30.5B total / ~3.3B active): **~6–12 tok/s** — the sweet spot. Q4 weights ≈ 17–18 GB.
  - **gpt-oss-20b** (20.9B total / ~3.6B active, native MXFP4, adjustable reasoning effort): **~5–9 tok/s**. Weights ≈ 12–13 GB.
- **Iris Xe acceleration is marginal-to-counterproductive** for generation. At most it offloads *prefill*. **Do not design around the iGPU.**
- **Thinking mode is a time bomb on dense models.** A 3K-token reasoning trace at ~1.5 tok/s (dense 32B) ≈ 30+ minutes; the same trace on the MoE at ~8 tok/s ≈ 6–7 minutes. **Thinking mode only on the fast MoE, with a capped budget.**

### 8. Quantization & memory policy

- **Default = Q4_K_M.** On bandwidth-bound CPU, every extra bit costs proportional speed; Q8 roughly halves throughput.
- MoE tolerates slightly higher quant (only active params are read): **Q5_K_M / UD-Q5_K_XL of Qwen3-30B-A3B is acceptable** if generation stays ≳ 6 tok/s.
- **Quantize the KV cache** (`q8_0` K and V) — near-lossless, stretches context, reduces bandwidth pressure.
- **Threads = physical cores (~10), not 12.** Hyperthreading hurts here.

### 9. Embeddings (run on CPU, cheap)

- **bge-m3** (568M) — strongest local all-rounder; dense+sparse+multi-vector, 100+ languages, 8192-token inputs. **Recommended default** (German/French/English Swiss context).
- **qwen3-embedding:0.6b** — modern, 32K context, 100+ languages; good CPU choice.
- **nomic-embed-text** (137M) — lightweight fallback.

## III — Architecture (decided by the hardware)

### 10. Design principles (async-first)

1. **Tiered model routing.** Small fast model (Qwen3-4B) for intent routing, field extraction, simple checks (~15 tok/s). Escalate to the MoE only when reasoning is genuinely required.
2. **One heavy pass, not many.** Collapse to: `retrieve → draft (MoE instruct) → single critique (MoE thinking, capped budget)`. Avoid iterative self-refine loops on the slow model.
3. **Async / batch / queue everything heavy.** Large document reviews = jobs on a queue, runnable overnight. Never block a chat UI on a 10-minute critique.
4. **Aggressive prompt caching.** Reuse KV for stable system prompts / rubrics / document headers (`cache_prompt=true`).
5. **Keep contexts small.** Chunk + retrieve top-k; avoid 32K-token stuffing; larger ubatch (e.g. 2048) to speed prefill.
6. **Single laptop = single-user async assistant.** Not a synchronous multi-user / many-agent real-time orchestrator. Deferred upgrade path: a single 24 GB GPU box (RTX 3090/4090 runs Qwen3-30B-A3B at 60–120 tok/s) or a high-bandwidth unified-memory machine — kept on-prem.

### 11. Model roster (target machine)

| Role | Model | Mode | Notes |
|---|---|---|---|
| Router / extractor / fast turns | `qwen3:4b` | instruct | ~15 tok/s |
| Planner / drafter (workhorse) | `qwen3-30b-a3b-instruct-2507` (Q4_K_M) | non-thinking | strong tool-calling (use `--jinja`) |
| Critic / judge (final pass) | `qwen3-30b-a3b-thinking-2507` (Q4_K_M) **or** `gpt-oss-20b` | thinking / capped | bake-off on real tasks; cap thinking ~1–2K tokens |
| Embeddings | `bge-m3` | — | CPU, multilingual |

### 12. Agent topology (logical, not necessarily multi-process)

```
                ┌──────────────┐
   user ───────▶│ Orchestrator │  (routing, state, HITL gates)
                └──────┬───────┘
        ┌──────────────┼───────────────┬───────────────┐
        ▼              ▼               ▼               ▼
   Intake/Socratic  Planner        RAG-Retriever     Scribe
   (qwen3:4b →      (30b-a3b        (bge-m3 +         (artifact +
    30b-a3b)         instruct)       vector store)     log writer)
        │              │               │               │
        └──────────────┴───────┬───────┴───────────────┘
                               ▼
                    Critic / Red-team / Pre-mortem
                    (30b-a3b thinking / gpt-oss-20b, async)
```

Specialist agents: **Intake/Socratic interviewer · Planner (HERMES structurer) · RAG-Retriever · Critic/Judge (rubric) · Red-Team/Pre-mortem · Consistency-checker · Scribe**. On this hardware they are *roles/prompts* invoked sequentially by one orchestrator process — **not** concurrent processes.

### 13. Compensating for weak local reasoning (structure > scale)

- **Grammar-constrained decoding** for all JSON/tool output → schema-valid output + Pydantic validation + auto-retry (drives JSON failure < 1%).
- **Rubric-driven LLM-as-judge** with concrete criteria, CoT-before-score, position randomization, length normalization.
- **Self-consistency** (run judge 3×, reconcile) before reaching for debate/panels.
- **Decomposition** (split big extractions into focused sub-calls).
- **RAG grounding** against HERMES/company docs — the main hallucination defense.
- **Debate/panels** only for highest-stakes reviews, with *different model families* — evidence on multi-agent debate is mixed; validate empirically before relying on it.

## IV — Build Contract for Claude Code CLI

### 14. Tech stack (chosen for local-first + Claude-Code-friendliness)

- **Language:** Python 3.11+ (Pandas/NumPy/FastAPI/SQLAlchemy stack).
- **LLM serving:** Ollama (local HTTP at `http://localhost:11434`).
- **Orchestration:** LangGraph (graph workflows, loops, state persistence, HITL interrupts). Plain-Python fallback acceptable if LangGraph proves heavy.
- **Structured output:** Pydantic v2 + `outlines` / Ollama JSON-schema `format` for grammar-constrained decoding.
- **Vector store:** ChromaDB (embedded, local) or LanceDB. Embeddings via Ollama `bge-m3`.
- **Job queue (async heavy passes):** SQLite-backed queue (start simple) → Redis/RQ if needed.
- **CLI / TUI:** Typer + Rich.
- **API (optional):** FastAPI (local-only bind `127.0.0.1`).
- **Config:** `pydantic-settings` + `.env` (no secrets needed — all local).
- **Testing:** pytest. **Lint/format:** ruff. **Types:** mypy.

### 15. Repository layout (scaffold exactly this)

```
hermes-assistant/
├── CLAUDE.md                     # operating contract for Claude Code (see §16)
├── pyproject.toml                # ruff + mypy + pytest config, deps
├── .env.example
├── docs/
│   └── MASTER.md                 # THIS document (single source of truth)
├── data/
│   ├── corpus/                   # HERMES manuals, A+W standards, templates (gitignored)
│   ├── projects/                 # per-project working dirs (gitignored)
│   └── vectorstore/              # Chroma persistence (gitignored)
├── src/hermes_assistant/
│   ├── __init__.py
│   ├── config.py                 # settings, model roster, thread/quant policy
│   ├── llm/
│   │   ├── client.py             # Ollama wrapper: chat, json_schema, tool-calling, retry
│   │   ├── roster.py             # ROUTER/PLANNER/CRITIC/EMBED model IDs + modes
│   │   └── caching.py            # prompt-prefix cache helpers
│   ├── rag/
│   │   ├── ingest.py             # PDF/Office/MD → chunks → embeddings → Chroma
│   │   ├── retrieve.py           # top-k retrieval, optional hybrid (bge-m3 sparse+dense)
│   │   └── store.py              # Chroma wrapper
│   ├── hermes/
│   │   ├── model.py              # Pydantic: Phase, Milestone, Outcome, Role, Module, Scenario
│   │   ├── project_types.py      # loader over project_types/*.yaml (the taxonomy, §4A)
│   │   └── reference.py          # optional HERMES lens lookups (RAG-backed)
│   ├── project_types/            # YAML seed files: isds_analyse, kvm, network_adaptation…
│   ├── agents/
│   │   ├── orchestrator.py       # LangGraph graph; routing; HITL gates
│   │   ├── intake.py             # Socratic interview
│   │   ├── planner.py            # HERMES scaffolder + completeness/dependency checker
│   │   ├── critic.py             # rubric judge + critique→revise + self-consistency
│   │   ├── redteam.py            # pre-mortem + red-team passes
│   │   ├── consistency.py        # MECE / contradiction / number checks
│   │   └── scribe.py             # writes Markdown artifacts + decision/assumption log
│   ├── rubrics/                  # YAML rubrics (acceptance criteria per deliverable type)
│   │   └── *.yaml
│   ├── queue/                    # (a.k.a. jobqueue) job model + SQLite queue + worker
│   │   ├── jobs.py
│   │   └── worker.py             # runs heavy critic/red-team jobs async/overnight
│   ├── scheduling/               # IV-B: dates, deadlines, ICS export
│   │   ├── model.py              # ScheduledItem, Schedule, Reminder (Pydantic)
│   │   ├── derive.py             # plan + anchors → dated schedule (deterministic)
│   │   ├── deadlines.py          # cross-project aggregation, collision detection
│   │   └── ics.py                # Schedule → RFC-5545 .ics (icalendar lib)
│   ├── artifacts/
│   │   └── writer.py             # Markdown + JSON emitters, traceability log
│   └── cli.py                    # Typer entrypoint (see §18)
├── tests/
│   ├── test_llm_client.py
│   ├── test_schema_validation.py
│   ├── test_rag.py
│   ├── test_planner.py
│   └── test_critic.py
└── scripts/
    ├── bootstrap.sh              # pull models, create venv, init store
    └── bench.sh                  # llama-bench / token-rate sanity check
```

### 16. `CLAUDE.md` — the operating contract (Claude Code reads this first)

```markdown
# CLAUDE.md — Operating contract for the HERMES Local Assistant

## What this project is
A fully-local (Ollama, no cloud) AI assistant that helps a junior consultant operate
at senior level under the HERMES 2022 method. See docs/MASTER.md for the full spec.
That document is the source of truth; if code and spec disagree, ask.

## Absolute rules (never violate)
1. NO network calls to any cloud LLM or external API for reasoning. All inference is via
   local Ollama at http://localhost:11434. No telemetry. No confidential data leaves the box.
2. All LLM JSON output MUST be schema-constrained (Ollama `format`/grammar) AND validated
   with Pydantic, with one bounded auto-retry on validation failure. Never trust raw text JSON.
3. Quality gates require human sign-off. Never mark a deliverable "approved" autonomously.
4. Respect the hardware: default model = Qwen3-30B-A3B (MoE) at Q4_K_M; thinking mode only
   on the MoE with a capped budget; heavy passes go through the async job queue, not inline.

## How to work
- Make the smallest change that satisfies the current backlog item (Part VI of the spec).
- After each change: `ruff check`, `mypy src`, `pytest -q` must pass before moving on.
- Prefer pure functions + Pydantic models. Keep agent logic testable without a live model
  (mock the Ollama client in tests).
- Every agent that calls a model must log: model id, mode, prompt hash, latency, token counts
  to the traceability log.

## Commands
- Setup:        bash scripts/bootstrap.sh
- Run CLI:      python -m hermes_assistant.cli --help
- Tests:        pytest -q
- Lint/types:   ruff check . && mypy src
- Bench models: bash scripts/bench.sh

## Model roster (see src/hermes_assistant/llm/roster.py)
- ROUTER  = qwen3:4b                         (fast, intent/extraction)
- PLANNER = qwen3-30b-a3b-instruct-2507:q4_K_M
- CRITIC  = qwen3-30b-a3b-thinking-2507:q4_K_M  (or gpt-oss-20b) — capped thinking
- EMBED   = bge-m3

## Definition of done for any feature
- Spec acceptance criteria [AC] met · tests added · lint+types+tests green ·
  traceability logging present · no cloud calls introduced.
```

### 17. Core interface contracts (implement these signatures)

```python
# src/hermes_assistant/llm/client.py
from typing import Type, TypeVar
from pydantic import BaseModel
T = TypeVar("T", bound=BaseModel)

class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434", num_thread: int = 10): ...

    def chat(self, model: str, messages: list[dict], *,
             think: bool | None = None, num_ctx: int = 8192,
             temperature: float = 0.2) -> str:
        """Plain chat completion. `think` toggles reasoning on capable MoE models."""

    def structured(self, model: str, messages: list[dict], schema: Type[T], *,
                   num_ctx: int = 8192, max_retries: int = 1) -> T:
        """Grammar-constrained JSON → validated Pydantic model. Retries once on
        ValidationError with the error fed back into the prompt. Raises after retries."""

    def embed(self, model: str, text: str) -> list[float]: ...
```

```python
# src/hermes_assistant/hermes/model.py  (skeleton — extend per HERMES 2022)
from enum import Enum
from pydantic import BaseModel

class Approach(str, Enum):
    traditional = "traditional"; agile = "agile"

class Outcome(BaseModel):
    id: str; name: str; kind: str           # "document" | "state"
    mandatory: bool                          # the "X" minimum docs
    module: str

class Milestone(BaseModel):
    id: str; name: str; is_quality_gate: bool = True
    release_criteria: list[str] = []

class Phase(BaseModel):
    id: str; name: str
    milestones: list[Milestone]; outcomes: list[Outcome]

class ProjectPlan(BaseModel):
    title: str; scenario: str; approach: Approach
    phases: list[Phase]; roles: list[str]
    open_assumptions: list[str] = []; risks: list[str] = []
```

```python
# src/hermes_assistant/agents/critic.py  (contract)
class Finding(BaseModel):
    location: str; severity: str            # "blocker"|"major"|"minor"
    rubric_dim: str; issue: str; suggestion: str

class CritiqueResult(BaseModel):
    dimension_scores: dict[str, int]        # 1–5 per rubric dimension
    findings: list[Finding]
    passed: bool                            # vs acceptance criteria
    summary: str

def critique(deliverable_md: str, rubric_yaml: str, *,
             self_consistency: int = 3) -> CritiqueResult:
    """Run rubric judge N times (CoT-before-score), reconcile, return result.
    MUST be callable as an async queue job for long runs."""
```

### 18. CLI surface (Typer)

```
hermes ingest <path>            # add docs to the local corpus + vector store
hermes intake                   # run the Socratic interview, save answers
hermes plan                     # generate HERMES scaffold from intake → ProjectPlan (md+json)
hermes check-plan               # completeness/dependency/role-coverage check
hermes review <file> [--rubric] # enqueue a rubric critique (async); prints job id
hermes premortem [--scope ...]  # run pre-mortem pass
hermes jobs [--watch]           # list/inspect queued + finished jobs
hermes show <artifact>          # render a produced artifact
hermes models --bench           # sanity-check token rates on this machine

# Scheduling / calendar (see IV-B)
hermes schedule <project>       # derive dated milestones+tasks from a plan → schedule.json
hermes deadlines [--all] [--in 14d]   # cross-project view: what's due, what collides
hermes ics <project> [--merged|--split] [--tasks-as events|vtodo]  # emit .ics file(s)
hermes ics --all                # emit a combined multi-project calendar for import
```

### 19. `scripts/bootstrap.sh` (intent)

```bash
#!/usr/bin/env bash
set -euo pipefail
# 1) Python env
python -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e ".[dev]"
# core deps (in pyproject): ollama, chromadb, langgraph, pydantic, pydantic-settings,
#   typer, rich, pyyaml, icalendar, workalendar  (all local; only Ollama runs as a service)
# 2) Local models (CPU-friendly roster)
ollama pull qwen3:4b
ollama pull qwen3-30b-a3b-instruct-2507:q4_K_M     # adjust tag to installed version
ollama pull qwen3-30b-a3b-thinking-2507:q4_K_M     # or: ollama pull gpt-oss:20b
ollama pull bge-m3
# 3) Init vector store + dirs
python -m hermes_assistant.cli init
echo "Bootstrap done. Run: bash scripts/bench.sh to confirm token rates."
```

### 20. Ollama runtime policy (bake into client / Modelfile)

- `OLLAMA_NUM_THREAD=10` (physical cores), flash attention on, KV cache `q8_0`.
- `num_ctx` default **8192**; raise only when a task truly needs it.
- Cap critic thinking budget (~1–2K tokens) via prompt + `num_predict`.
- First action after bootstrap: **measure real tok/s** (`hermes models --bench`); the measured numbers govern all later tuning. If Qwen3-30B-A3B generation < 5 tok/s → switch CRITIC/PLANNER to `gpt-oss-20b` or `qwen3:8b` and shrink contexts.

## IV-B — Scheduling & Calendar Export (ICS)

> Answers: *"can it create calendar, todos with reminders, juggle multiple project deadlines?"* — **Yes, via ICS file export.** The assistant is the *brain* that derives **what** the deadlines are; your calendar app (Outlook) is the *clock* that stores and reminds. Chosen because it needs **no Microsoft Graph access, no API permissions, no cloud account** — just local `.ics` files you import.

### 24. Design rationale & boundaries

- **Why ICS, not Graph/Outlook API:** a `.ics` file is a local artifact. The assistant writes it; you import it manually. No programmatic M365 access, no credentials, nothing leaves the box until *you* choose to import.
- **Division of labor:** the assistant **derives and exports**; the calendar app **stores, displays, and notifies**. No reminder daemon, no clock polling.
- **Content boundary (important):** ICS files carry only **structural schedule metadata** — item title, dates, reminder lead time, project tag, and a short non-confidential note. **No confidential deliverable content** goes into an `.ics` summary/description.
- **Re-import hygiene:** every component carries a **stable deterministic `UID`** (e.g. `hermes-{project_id}-{item_id}@local`) and a bumped `SEQUENCE` on change, so re-importing updates existing entries instead of duplicating.

### 25. What ICS (RFC 5545) supports — and the Outlook reality

| Need | ICS mechanism | Outlook reality |
|---|---|---|
| Milestone / deadline as a calendar entry | `VEVENT` (all-day or timed) | ✅ Fully supported on import |
| "Remind me N days before" | `VALARM` (`TRIGGER:-P2D`) | ✅ Supported on `VEVENT` |
| A to-do with a due date | `VTODO` (`DUE`, `PRIORITY`, `STATUS`) | ⚠️ Outlook import of `VTODO` is unreliable/unsupported |
| Multiple projects | many components, one or many files | ✅ Per-project files import as separate, color-codable calendars |

**Decision:** by **default, emit tasks as `VEVENT`** (all-day deadline events with alarms) so reminders fire in Outlook. Offer `VTODO` only behind `--tasks-as vtodo` for clients with real task support (Apple Calendar / Thunderbird-Tasks).

### 26. Where the dates come from (deterministic, not the LLM's head)

The LLM proposes **structure and ordering**; a **deterministic scheduler** computes the **actual dates**. Inputs to `scheduling/derive.py`:
1. The `ProjectPlan` (phases, milestones, deliverables, dependencies).
2. **Anchors** the user provides: go-live / hard deadline, start date, fixed external dates.
3. **Effort/duration hints** per item (LLM-suggested ranges, user-confirmable).
4. **Working-time rules**: skip weekends, optional Swiss/cantonal (Zürich) public holidays, configurable reminder lead times per item type (milestones −5 working days, tasks −2).

The scheduler does standard backward/forward-pass dependency dating (no LLM) and flags any **negative-float** items (work that can't fit before the deadline).

### 27. Data model & interface contracts

```python
# src/hermes_assistant/scheduling/model.py
from datetime import date, datetime
from pydantic import BaseModel
from enum import Enum

class ItemKind(str, Enum):
    milestone = "milestone"      # quality gate / decision point
    deadline  = "deadline"       # deliverable due
    task      = "task"           # work item

class Reminder(BaseModel):
    lead_days: int               # → VALARM TRIGGER:-P{n}D  (working-day aware in derive.py)
    note: str | None = None

class ScheduledItem(BaseModel):
    uid: str                     # stable: f"hermes-{project_id}-{item_id}@local"
    project_id: str
    project_label: str           # CATEGORIES tag for color-coding on import
    item_id: str
    title: str                   # NON-confidential summary only
    kind: ItemKind
    start: date | None
    due: date
    all_day: bool = True
    depends_on: list[str] = []
    reminders: list[Reminder] = []
    note: str | None = None      # short, NON-confidential
    sequence: int = 0            # bump on change → ICS SEQUENCE for clean re-import

class Schedule(BaseModel):
    project_id: str
    generated_at: datetime
    items: list[ScheduledItem]
    negative_float: list[str] = []   # item_ids that cannot meet the deadline → warn user
```

```python
# src/hermes_assistant/scheduling/ics.py
def to_ics(schedule: Schedule | list[Schedule], *,
           tasks_as: str = "events",      # "events" (Outlook-safe default) | "vtodo"
           merged: bool = True,
           calendar_name: str = "HERMES Assistant") -> dict[str, str]:
    """Return {filename: ics_text}. Uses the `icalendar` library.
    - VEVENT per milestone/deadline (+ optional task when tasks_as='events'),
      all-day via DTSTART;VALUE=DATE, with VALARM per reminder (TRIGGER:-P{n}D).
    - VTODO per task only when tasks_as='vtodo'.
    - UID stable, SEQUENCE from item.sequence, CATEGORIES=project_label.
    - DESCRIPTION limited to non-confidential note; never deliverable content."""
```

```python
# src/hermes_assistant/scheduling/deadlines.py
class DeadlineView(BaseModel):
    within_days: int
    upcoming: list[ScheduledItem]          # sorted by due, across ALL projects
    collisions: list[tuple[str, str]]      # item pairs due same day across projects
    overdue: list[ScheduledItem]

def cross_project_view(schedules: list[Schedule], *, within_days: int = 14) -> DeadlineView:
    """Aggregate every project's schedule into one view."""
```

**Dependencies:** add `icalendar` and `python-dateutil` / `workalendar` (Swiss + Zürich holidays) to `pyproject.toml`. All pip-installed, all local.

### 28–30. CLI behavior & limits
- `hermes schedule <project>` → prompts for anchors, derives `Schedule`, writes `schedule.json`, **prints negative-float warnings**.
- `hermes deadlines --all --in 14d` → cross-project juggling view.
- `hermes ics <project>` → writes `<project>.ics` (default: events + alarms). `--split` per-project; `--merged --all` one combined calendar.
- **Limits:** the assistant does *not* notify — your calendar app does. It's export, not live sync. `VTODO` is opt-in. No local daemon, no cloud.

## VI — Phased Build Backlog (acceptance-criteria driven)

**Phase 0 — Skeleton & guardrails**
- Scaffold repo (§15), `CLAUDE.md` (§16), `pyproject.toml`, `.env.example`. Implement `OllamaClient` (§17) incl. `structured()` retry path.
- **[AC]** `pytest` green with a **mocked** Ollama client; `ruff` + `mypy` clean.
- **[AC]** `structured()` rejects then repairs one malformed JSON in a unit test.
- **[AC]** No module imports any cloud SDK; a test asserts only `localhost` is contacted.

**Phase 1 — RAG foundation**
- `rag/ingest.py` (PDF/MD/Office → chunks → `bge-m3` → Chroma), `rag/retrieve.py` (top-k). `hermes ingest` + `hermes show` CLI.
- **[AC]** Ingest a sample HERMES PDF; retrieval returns relevant chunks. Ingestion is idempotent.

**Phase 2 — Experience-gap core (highest priority)**
- `agents/intake.py` (adaptive Socratic interview), `hermes/model.py`, `hermes/project_types.py` + `project_types/*.yaml` seeds (ISDS-Analyse first), optional `hermes/reference.py`. `agents/planner.py`: scaffolder → `ProjectPlan` + completeness/dependency/role-coverage checker. `agents/scribe.py`. Auto-checklist generator.
- **[AC]** `hermes plan` emits a schema-valid `ProjectPlan` with phases, milestones (quality gates), mandatory outcomes, roles.
- **[AC]** `hermes check-plan` flags an injected missing mandatory outcome and an unassigned minimum role.
- **[AC]** On one real past project, intake+plan surfaces ≥ 80% of gaps a senior reviewer independently lists.

**Phase 3 — Quality-checking**
- `agents/critic.py` (rubric judge per I-C §4E–4I), `rubrics/*.yaml` (schema §4H), `ReviewResult` (§4I), anti-pattern library (§4J). Async `queue/` (SQLite) + `worker.py`; `hermes review` enqueues, `hermes jobs` inspects.
- **[AC]** `hermes review` on a deliberately flawed deliverable returns located findings + correct pass/fail.
- **[AC]** A critique runs end-to-end as an async job and persists its result + traceability log.

**Phase 3.5 — Scheduling & ICS export**
- Implement `scheduling/` (model, deterministic `derive`, `ics`, `deadlines`) + `schedule`/`deadlines`/`ics` CLI. Add `icalendar`, `workalendar`.
- **[AC]** Dependency-correct dates (skip weekends/Zürich holidays); negative-float warnings; Outlook-safe ICS import with reminders; clean re-import (stable UID + bumped SEQUENCE); cross-project collision view; no confidential content in ICS.

**Phase 4 — Review depth**
- `agents/redteam.py` (pre-mortem + red-team), `agents/consistency.py` (MECE/contradiction/number checks). "So-what" critique. HITL gates wired to HERMES milestones. Failure-mode library + exemplars.
- **[AC]** Pre-mortem produces ≥ N distinct failure causes mapped to mitigations.
- **[AC]** Consistency checker catches an injected numeric contradiction across two sections.

**Phase 5 — Selective heavy techniques (only if they earn it)**
- Self-consistency on critical judgments; optional diverse-model panel for high-stakes reviews.
- **[AC]** Panel/self-consistency must **measurably beat** single-judge on a labeled set before being kept.

## VII — Guardrails, Decision Thresholds, Caveats

### 21. Guardrails (enforced in code + `CLAUDE.md`)
- **No cloud reasoning, ever.** All inference local. M365 Copilot stays non-confidential-only and outside this system's data path.
- **Schema-valid ≠ correct.** Constrained decoding guarantees format, not truth. Human sign-off at every HERMES gate is mandatory.
- **Traceability always on.** Every model call logged (model, mode, prompt hash, latency, tokens).

### 22. Decision thresholds (when to change course)
- Qwen3-30B-A3B generation **< 5 tok/s** → drop to **gpt-oss-20b** / **Qwen3-8B**, shrink contexts.
- Need **synchronous multi-agent** or **multi-user** → provision the deferred local GPU box.
- Thinking-mode critiques routinely **> 10 min** → cap thinking to ~1K tokens or switch critic to instruct-mode + structured rubric prompt.
- Hallucinated method guidance → tighten RAG grounding + citation-required rubrics **before** changing models.

### 23. Caveats
- **Model landscape moves fast.** Specific tags are current as of mid-2026; the *architecture* (low active params + Q4 + MoE + structure-over-scale) is what matters, not the version.
- **Performance estimates carry uncertainty.** `llama-bench` on the actual ZBook is ground truth — measure before committing.
- **Confirm RAM type/speed** (soldered LPDDR5 vs DDR5 SO-DIMM, MHz) in BIOS/HWiNFO — it sets the generation ceiling.
- **Tacit knowledge is only partially extractable.** The tool augments, it does not replace, senior mentoring.
- **Internal A+W standards and the specific HERMES tailoring** must be ingested during Phase 1.

## IV-I…IV-L — Later Spec Amendments (Jul 2026)

### IV-I — Hardware Baseline Update

| Component | Prod machine | Local POC |
|-----------|-------------|-----------|
| CPU | i7-1265U (10c/12t) | M4 (10c) |
| RAM | 32 GB LPDDR5 | 16 GB unified |
| GPU | RTX A500 4 GB GDDR6 | Apple Silicon GPU |
| Storage | NVMe SSD | NVMe SSD |

**Model placement rules:**
- ROUTER (qwen3:4b) — fully on GPU (`num_gpu=1`); ~2.3 GB VRAM.
- EMBED (bge-m3) — fully on GPU; ~1.1 GB VRAM.
- PLANNER/CRITIC (qwen3-30b-a3b, Q4_K_M) — one resident at a time; KV-cache q8_0 mandatory; CPU+GPU offload as available.
- Panel models (qwen3:8b, gemma3:4b, llama3.1:8b) — sequential loading; `keep_alive=0` between models to release VRAM.
- Fallback under memory pressure: gpt-oss-20b (preferred) or qwen3:4b.
- **KV-cache:** `num_kv_cache_quant=q8_0` for all 30B models. Halves KV RAM vs fp16.

### IV-J — Phase 2.5: Task Store + WBS Tree

The task store is the prerequisite for Phase 2.6 (Pendenzen) and Phase 3.6 (Dashboard).

**NodeKind taxonomy:** `milestone` (quality gate) · `deliverable` (Ergebnis) · `task` (action) · `decision` (may spawn Pendenz) · `pendenz` (open follow-up) · `assumption` (tracked for invalidation).

- **WBS numbering:** computed from parent path (root="1", first child="1.1"). Stored on `wbs_number`; recomputed on tree restructure.
- **Progress rollup:** recursive closure/open counts up the parent chain. A parent is "done" when all children are `status=closed`.
- **Task history:** every field update appended as a `TaskUpdate` record (timestamp, field, old, new, changed_by). Immutable audit trail.

### IV-K — Phase 2.6: Pendenzen + Meetings

A Pendenz is a `Task` with `node_kind="pendenz"` plus source tracking.

**PendenzSource taxonomy:** `manual` · `review` (critic finding severity ≥ major, not closed) · `decision` (unresolved decision record) · `meeting` (extracted from notes) · `facilitator_import` (external tool).

- **Confidentiality:** Meeting `raw_notes` are LOCAL ONLY and must never appear in any export, API response, or log. Only `title`, `attendees`, and `extracted_actions` may leave the store.
- **Action extraction:** grammar-constrained LLM call (ROUTER model) on meeting raw_notes → list of Task objects in proposal state. Human approval required before promoting to open tasks.

### IV-L — Build Order

| Phase | Module | Status | Gate |
|-------|--------|--------|------|
| P1 | RAG ingest + retrieve | Done | 338 tests green |
| P2 | HERMES model + planner | Done | — |
| P3 | Rubrics + critic + queue + CLI | Done | — |
| P3 | Consistency + redteam agents | Done | — |
| P4 | Calibration gold sets | Done | — |
| P5 | Diverse panel + self-consistency | Done | — |
| P2.5 | Task store + WBS tree | Done | mypy + pytest |
| P2.6 | Pendenzen + meetings | Done | confidentiality test |
| P3.6 | Dashboard (read-only) | Done | — |
| P5.x | Facilitator import | Planned | — |

*Build in phase order; keep it local; measure before you optimize.*

---

# Part 2 — Web Dashboard & Chat Assistant

## 2.1 Web Dashboard (Phase 4)

A locally-hosted single-page dashboard providing visual access to all HERMES
project data. Replaces the TUI as the primary interface for day-to-day use.

**Quick start:** `bash scripts/start-web.sh` → open `http://localhost:8000`.

**Architecture**

```
Browser (Vue 3 — vendored locally, no CDN)
        │  fetch /api/dashboard
        ▼
FastAPI server (hermes_assistant.webapp.server)
        │  load_dashboard_data()   [reuse from dashboard_html.py]
        │  _validate_safe_json()    [confidentiality guard]
        ▼
SQLite task/job stores + schedule.json files
```

**Backend endpoints — `src/hermes_assistant/webapp/server.py`**

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check; `{"status":"ok","version":"0.1.0","timestamp":"…"}` |
| `/api/dashboard` | GET | Full DashboardData JSON (all projects) |
| `/api/dashboard?project_id=X` | GET | Scoped DashboardData for project X |
| `/api/refresh` | GET | Same as `/api/dashboard` — fresh disk read |
| `/` and `/*` | GET | Serves `index.html` (SPA fallback) |
| `/static/*` | GET | CSS, JS, HTML static assets |

**Frontend — `src/hermes_assistant/webapp/static/`**

| File | Purpose |
|---|---|
| `index.html` | SPA shell; loads the vendored Vue runtime, then components/screens/app |
| `vendor/vue.global.prod.js` | Vue 3 full build (includes the runtime template compiler the screens need) — vendored so the dashboard runs fully offline |
| `style.css` | Design tokens, a self-contained utility layer (replaces the former Tailwind CDN), and all component styles |
| `components.js` | Shared WBS components (`WbsNodeItem`, `WbsTab`) |
| `screens.js` | Screen components for all 6 views |
| `app.js` | Root app, global state, keyboard shortcuts, polling |

**Screens:** (0) **Overview** — landing screen; headline count tiles (each navigates to its screen) plus "Coming up", "Needs attention" and "Highest-scoring risks" panels. (1) **Projects** — sortable table, click to drill in. (2) **Project Detail** — Timeline (colour-coded by status), Kanban (To Do / Blocked / Done), WBS (collapsible tree with status icons). (3) **Pendenzen** — filterable by source/priority/status, sorted by priority rank. (4) **Reviews** — completed review jobs, verdict colour coding (green pass / amber pass_with_comments / red fail), click for detail modal. (5) **Risks** *(F1)* — non-confidential risks from `RiskRegistry.export_public()`, sortable by score (severity×likelihood), status colour-coded (open=red, mitigated=amber, accepted=blue, closed=grey), empty state "No risks recorded".

**`/api/dashboard` — DashboardData fields:** `generated_at`, `scope`, `range_start`, `range_end`, `projects`, `timeline`, `kanban`, `wbs`, `pendenzen`, `reviews`, `risks`. The `risks` array carries only safe fields per `RiskRow` (`id`, `title`, `severity`, `likelihood`, `status`, `score`, `updated_at`) — confidential risks and the `owner` field are excluded.

**Keyboard shortcuts:** `1`–`6` switch screens · `r` refresh · `i` import JSON · `d` toggle dark/light · `?` help · `Esc` close dialog. Theme persisted in `localStorage`.

**Version display:** the running version is shown as a small muted pill in the top-left corner of the topbar, next to the brand (`data-testid="app-version"`). The frontend never hard-codes it — it reads `version` from `/api/health`, which serves `hermes_assistant.__version__`. That module attribute is the single source of truth; `test_version_matches_pyproject` fails the build if `pyproject.toml` drifts from it. To cut a new version, edit `__version__` in `src/hermes_assistant/__init__.py` and the matching `version` in `pyproject.toml`.

**Routing:** screens are hash-routed (`#/overview`, `#/pendenzen`, `#/detail/<project_id>`), so a view survives reload and can be linked to.

**JSON import:** a two-step wizard in the topbar — step 1 hands over the ready-to-copy M365 Copilot prompt (`static/prompts/copilot_state_export.txt`), step 2 accepts the resulting JSON by paste, file picker or drag-and-drop, with live validation and a pre-import preview of the row counts.

**Security:** same-origin only (no CORS); CSP headers on every response (`default-src 'none'`, scripts/styles are served from `'self'` — the CDN allowance is no longer exercised now that Vue is vendored); `_validate_safe_json()` on every API response (forbidden fields `raw_notes`, `evidence_quote`, `rationale`, `assumptions`, etc. → HTTP 500); Pydantic `extra="forbid"` on all view models; no authentication (trusted LAN assumption; Phase 5 adds SSO); localhost bind by default.

**Deps:** `pip install -e ".[webapp]"` (FastAPI + uvicorn). The `dev` extra already includes FastAPI + httpx. Tests: `pytest tests/test_webapp_endpoints.py tests/test_webapp_e2e.py -v`.

**Company-network deployment:** change bind to `--host 0.0.0.0`; add nginx/Caddy for TLS. The CSP uses `https:` scheme-only allowlist, which works behind any HTTPS proxy.

## 2.2 Phase 5 — Chat Assistant

A text-based conversational interface. Users interact with the project (risks,
tasks, plans, reviews) in natural language; the assistant classifies each
message, executes the matching action, and replies in prose. All inference is
local (Ollama).

**Architecture**
- **IntentRouter** (`chat/router.py`) — classifies a message into one of eight intents using the ROUTER model (`qwen3:4b`) via grammar-constrained structured output. The LLM client is duck-typed (`LLMClient` Protocol) for test injection.
- **ActionExecutor** (`chat/executor.py`) — dispatches an intent to a concrete side effect against the Risk Registry, Task Store, and Plan Editor. Every handler returns a JSON-serialisable dict; errors are captured, not raised.
- **ChatService** (`chat/service.py`) — orchestrates one turn: classify → execute (or fall back) → format → persist → suggest. Intent classification is wrapped so an unavailable ROUTER model degrades to a safe `answer_question` fallback.
- **ChatStore** (`chat/store.py`) — WAL-mode SQLite persistence of sessions, messages, and actions with `ON DELETE CASCADE`. Opened with `check_same_thread=False` for FastAPI threadpool workers.
- **ResponseFormatter** (`chat/service.py`) — renders executor result dicts into natural-language replies.
- **prompts.py** — router and answer system prompts plus `build_context_block`.

**API endpoints (`webapp/chat_api.py`)**
- `POST /api/chat/message` — send a message, get the assistant response.
- `GET /api/chat/sessions` — list sessions (optional `project_id` filter).
- `GET /api/chat/sessions/{id}` — session plus full message history.
- `DELETE /api/chat/sessions/{id}` — delete a session (cascades messages/actions).

All responses pass through a confidentiality guard; blocking work runs in a thread pool. Input validated (message 1–2000 chars, `project_id` required).

**Frontend (`webapp/static/chat.js`):** self-contained, framework-free widget mounted into `#chat-app`. Fixed bottom-right, collapsible, user/assistant bubbles, suggestion buttons, typing indicator, Enter-to-send, inline error display.

**Intents:** `create_risk`, `create_task`, `list_risks`, `show_plan`, `review_status`, `run_review`, `answer_question`, `smalltalk`.

**Testing:** 13 `ChatStore` + 11 `IntentRouter` + 15 `ActionExecutor` + 10 `ChatService`/`ResponseFormatter` unit tests; 20 API integration tests; 2 perf tests; 15 E2E browser tests (`e2e/test_chat_ui.py`, marked `e2e`, skipped without Playwright + live server on `:8000`).

**Security:** confidentiality guard on every dict response (forbidden field names, `internal_*`/`confidential_*` patterns, absolute paths, emails); input validation at the API boundary; `list_risks` uses `export_public()` excluding confidential risks; all actions persisted to `chat_actions` for audit.

**Performance:** orchestration overhead (excluding LLM) well under 100 ms per turn; SQLite list queries single-digit ms; production message latency dominated by ROUTER inference (~15 tok/s).

**Follow-ups:** production `OllamaClient` should carry the system prompt as a `system`-role message (until then, graceful-degradation returns a safe fallback). Future: streaming responses, per-session rate limiting, richer context hydration. Voice I/O explicitly out of scope.

---

# Part 3 — Copilot Import (Prompt, Feature, Example)

Hermes imports a project's state (WBS, risks, pendenzen) from a JSON export
produced by **Microsoft 365 Copilot**. This part is the canonical reference for
that pipeline: the exact prompt, its enum contract, the adapter mapping, the
user/developer/maintainer guide, and a realistic example.

**Where it lives in the code**

| Concern | Location |
|---|---|
| Prompt text (source of truth) | `src/hermes_assistant/webapp/static/prompts/copilot_state_export.txt` |
| Button + toast + clipboard JS | `src/hermes_assistant/webapp/static/index.html` (`copyPromptToClipboard`, `showImportToast`, `loadCopilotPrompt`) |
| Schema → importer adapter | `src/hermes_assistant/webapp/import_adapters.py` (`_adapt_project_state_v1`) |
| Importer | `src/hermes_assistant/webapp/import_json.py` |
| Adapter/contract tests | `tests/test_copilot_adapter.py` |
| Clipboard/toast E2E test | `tests/e2e/test_json_import_ui.py::TestJsonImportUI::test_copy_copilot_prompt_shows_toast` |
| Golden fixture (prompt example) | `tests/fixtures/import/copilot_v1_prompt_example.json` |
| Realistic fixture | `tests/fixtures/import/copilot_v1_helios_realistic_export.json` |

## 3.1 Enum Reference (Source of Truth) — `hermes.project_state/v1`

| Field | Allowed values | Forbidden / common mistakes |
|---|---|---|
| `node_kind` | `phase \| deliverable \| task \| subtask \| action` | any value not in this list |
| `wbs.status` | `open \| in_progress \| done \| blocked` (NUR diese vier) | `todo`, `at_risk` |
| `project.phase` | `init \| konzept \| realisierung \| einfuehrung \| abschluss` | any value not in this list |
| `risks.likelihood` | `tief \| mittel \| hoch` | `gering` (that belongs to impact, not likelihood) |
| `risks.impact` | `gering \| mittel \| hoch` ("gering", NICHT "tief") | `tief` (only valid for likelihood, never impact) |
| `pendenzen.source` | `meeting \| review \| decision_log \| manual` | any value not in this list |
| `pendenzen.status` | `open \| in_progress \| done \| blocked` | `todo`, `at_risk` |

Date format: always `YYYY-MM-DD`. `external_ref` prefixes: `proj/` Projekt, `ms/` Meilenstein, `wp/` WBS-Knoten, `pd/` Pendenz.

**The prompt is the source of truth, not the code.** The prompt decides what Copilot emits; the adapter can only translate what it is given. If they disagree, imports silently degrade to defaults (data loss without an error). CI enforces the contract:
- `test_schema_version_matches_prompt_literal` — the exact schema string `hermes.project_state/v1` appears in the prompt file.
- `test_prompt_file_no_forbidden_tokens` — the `wbs.status:` / `risks.impact:` enum-definition lines do **not** offer `todo`, `at_risk`, or `tief` (impact). Checks only the definition lines (the "common mistakes" section legitimately names them as counter-examples).
- `test_prompt_example_roundtrips` — the worked example (mirrored in `copilot_v1_prompt_example.json`) runs through `adapt → validate → import` and yields exactly **7 rows created, 0 updated, 0 skipped, 0 errors**.

## 3.2 Full Copilot Prompt (copy-paste ready, verbatim)

```
# Aufgabe
Du hast Zugriff auf das Projekt-Repository. Erstelle eine maschinenlesbare
Zustandsaufnahme des Projekts als JSON. Dieses JSON wird von einem lokalen
Assistenzsystem (Hermes) eingelesen — es wird NICHT von Menschen gelesen und
NICHT ausgeführt. Deine einzige Aufgabe ist es, gültiges JSON nach dem unten
definierten Schema hermes.project_state/v1 auszugeben.

## Scope
Projekt: {{PROJECT_TITLE}}
Quellen: {{REPO_SCOPE}} (nur diese Quellen; keine anderen Projekte, keine
privaten Mails, keine Screenshots, keine Bilder)
Stichtag: {{AS_OF_DATE}}

## Ausgabe-Regeln (strikt)
1. Gib AUSSCHLIESSLICH ein einzelnes JSON-Objekt aus. Keine Einleitung, keine
   Erklärung, kein Kommentar, keine Markdown-Code-Fences, kein Text davor oder
   danach. Das erste Zeichen deiner Antwort ist "{", das letzte ist "}".
2. Halte dich EXAKT an das Schema. Erfinde keine zusätzlichen Felder und
   benenne keine Felder um.
3. Wenn eine Information nicht belegbar im Repo steht: lass das Feld weg.
   Rate niemals Termine, Verantwortliche oder Status. Ein fehlendes optionales
   Feld ist korrekt — ein erfundener Wert ist ein Fehler.
4. Verwende für jedes Element ein external_ref nach diesen DETERMINISTISCHEN
   Regeln (damit wiederholte Exporte identische Refs erzeugen und der Import
   keine Duplikate anlegt):
   - Präfix: proj/ Projekt · ms/ Meilenstein · wp/ WBS-Knoten · pd/ Pendenz
   - Danach der Titel in Kleinbuchstaben, Umlaute ausgeschrieben
     (ä→ae, ö→oe, ü→ue, ß→ss), nur a–z 0–9 -, Leerzeichen → -, max. 60 Zeichen.
   - Beispiel: „Begehung Serverraum" → wp/begehung-serverraum
   - Leite den Ref IMMER aus dem Titel ab, nie aus Position oder Reihenfolge.
5. Erlaubte Enum-Werte (jeder andere Wert ist ungültig):
   - node_kind: phase | deliverable | task | subtask | action
   - wbs.status: open | in_progress | done | blocked      ← NUR diese vier
   - project.phase: init | konzept | realisierung | einfuehrung | abschluss
   - risks.likelihood: tief | mittel | hoch
   - risks.impact: gering | mittel | hoch                  ← "gering", NICHT "tief"
   - pendenzen.source: meeting | review | decision_log | manual
   - pendenzen.status: open | in_progress | done | blocked
6. Datumsformat immer YYYY-MM-DD.
7. Gib bei jedem Element, das aus einem Dokument stammt, source_hint mit dem
   Dateinamen an (nur Dateiname, kein Pfad, keine Zitate aus dem Inhalt).
8. Obergrenzen: max. 500 WBS-Knoten, 300 Pendenzen, je 100 Annahmen / Risiken /
   Entscheide. Bei mehr: die wichtigsten auswählen und in meta.generator_note
   vermerken.

## Schema
{
  "schema": "hermes.project_state/v1",
  "meta": { "generated_at": "<ISO-8601>", "source": "m365_copilot",
            "repo_scope": "{{REPO_SCOPE}}", "generator_note": "<optional>" },
  "project": {
    "external_ref": "proj/<slug>", "title": "<string>", "goal": "<1-3 Sätze>",
    "phase": "init|konzept|realisierung|einfuehrung|abschluss",
    "milestones": [ { "external_ref": "ms/<slug>", "title": "<string>",
                      "due": "YYYY-MM-DD", "status": "open|in_progress|done|blocked" } ]
  },
  "wbs": [ { "external_ref": "wp/<slug>", "parent_ref": "wp/<slug> oder null",
             "title": "<string>", "node_kind": "phase|deliverable|task|subtask|action",
             "status": "open|in_progress|done|blocked",
             "due": "YYYY-MM-DD", "effort_hint_h": <number>,
             "depends_on_refs": ["wp/<slug>"], "source_hint": "<Dateiname>" } ],
  "risks": [ { "title": "<string>", "impact": "gering|mittel|hoch",
               "likelihood": "tief|mittel|hoch" } ],
  "pendenzen": [ { "external_ref": "pd/<slug>", "title": "<string>",
                   "owner": "<Rolle oder Name>", "raised_by": "<string>",
                   "due": "YYYY-MM-DD", "status": "open|in_progress|done|blocked",
                   "source": "meeting|review|decision_log|manual",
                   "source_hint": "<Dateiname>" } ],
  "open_assumptions": [ { "text": "<string>", "since": "YYYY-MM-DD" } ],
  "decisions": [ { "title": "<string>", "at": "YYYY-MM-DD", "rationale": "<string>" } ]
}

Hinweis zu open_assumptions und decisions: Diese Abschnitte werden vom Import
bewusst NICHT gespeichert, aber als übersprungene Abschnitte protokolliert. Du
darfst sie befüllen; sie gehen nicht verloren, werden aber nicht importiert.

## Vollständiges Beispiel (kleiner, gültiger Export — validiere deine Struktur dagegen)
{
  "schema": "hermes.project_state/v1",
  "meta": { "generated_at": "2026-08-22T10:00:00Z", "source": "m365_copilot",
            "repo_scope": "Webshop-Relaunch" },
  "project": {
    "external_ref": "proj/webshop-relaunch", "title": "Webshop-Relaunch",
    "goal": "Ablösung des Legacy-Shops durch eine neue Plattform bis Q4.",
    "phase": "realisierung",
    "milestones": [ { "external_ref": "ms/go-live", "title": "Go-Live",
                      "due": "2026-11-30", "status": "open" } ]
  },
  "wbs": [
    { "external_ref": "wp/anforderungsanalyse", "parent_ref": null,
      "title": "Anforderungsanalyse", "node_kind": "phase", "status": "done" },
    { "external_ref": "wp/implementierung-checkout", "parent_ref": null,
      "title": "Implementierung Checkout", "node_kind": "phase", "status": "in_progress" },
    { "external_ref": "wp/abnahme-und-go-live", "parent_ref": null,
      "title": "Abnahme und Go-Live", "node_kind": "phase", "status": "open" }
  ],
  "risks": [
    { "title": "Zahlungsanbieter-Integration verzögert sich",
      "impact": "hoch", "likelihood": "mittel" },
    { "title": "Unklare Migrationsdaten aus Altsystem",
      "impact": "gering", "likelihood": "hoch" }
  ],
  "pendenzen": [
    { "external_ref": "pd/dsgvo-check-checkout", "title": "DSGVO-Check Checkout",
      "owner": "Legal", "source": "review", "status": "open" },
    { "external_ref": "pd/lasttest-planen", "title": "Lasttest planen",
      "owner": "DevOps", "source": "meeting", "status": "open" },
    { "external_ref": "pd/texte-agb-finalisieren", "title": "Texte AGB finalisieren",
      "owner": "PM", "source": "manual", "status": "open" }
  ],
  "open_assumptions": [ { "text": "Altsystem bleibt bis Go-Live stabil",
                         "since": "2026-08-01" } ],
  "decisions": [ { "title": "Payment-Provider: Stripe", "at": "2026-07-15",
                   "rationale": "Beste API-Dokumentation" } ]
}

## Validierungs-Checkliste (vor der Ausgabe abarbeiten)
[ ] Ausgabe ist EIN JSON-Objekt, beginnt mit { und endet mit } — kein Fließtext.
[ ] "schema" ist exakt "hermes.project_state/v1".
[ ] "project.external_ref" beginnt mit "proj/" und ist aus dem Titel abgeleitet.
[ ] Jeder wbs.status / pendenzen.status ist einer von open|in_progress|done|blocked.
[ ] Jeder risks.impact ist gering|mittel|hoch (NICHT "tief" für Auswirkung).
[ ] Jeder risks.likelihood ist tief|mittel|hoch.
[ ] Jede pendenzen.source ist meeting|review|decision_log|manual.
[ ] Jedes parent_ref existiert auch als external_ref in wbs (sonst weglassen).
[ ] depends_on_refs enthält nur existierende Refs (sonst weglassen).
[ ] Keine Zyklen in parent_ref oder depends_on_refs.
[ ] Alle Daten im Format YYYY-MM-DD.
[ ] Jedes external_ref ist eindeutig und deterministisch aus dem Titel gebildet.

## Häufige Fehler (unbedingt vermeiden)
- KEIN roher Notion-/Confluence-Export und KEINE Screenshots — nur dieses Schema.
- KEINE Markdown-Code-Fences (``` ) um das JSON.
- KEINE erklärenden Sätze vor oder nach dem JSON.
- KEINE erfundenen Termine oder Verantwortlichen — im Zweifel Feld weglassen.
- KEIN "tief" als Risiko-Auswirkung (impact) — dort heisst "gering" die
  niedrigste Stufe. "tief" ist nur bei likelihood erlaubt.
- KEINE Status-Werte wie "todo" oder "at_risk" — nur open|in_progress|done|blocked.
```

## 3.3 Adapter Mapping (Copilot → Internal)

`_adapt_project_state_v1` in `import_adapters.py`. Translation tables:
`_LIKELIHOOD_TABLE`, `_IMPACT_TABLE`, `_PENDENZ_SOURCE_TABLE`.

| Copilot field | Copilot value | Adapter target | Internal value |
|---|---|---|---|
| `risks.likelihood` | `tief` | `likelihood` (int 1-5) | `2` |
| `risks.likelihood` | `mittel` | `likelihood` (int 1-5) | `3` |
| `risks.likelihood` | `hoch` | `likelihood` (int 1-5) | `4` |
| `risks.likelihood` | unknown/missing | `likelihood` | `3` (default) |
| `risks.impact` | `gering` | `severity` (string) | `low` |
| `risks.impact` | `mittel` | `severity` | `medium` |
| `risks.impact` | `hoch` | `severity` | `high` |
| `risks.impact` | unknown/missing | `severity` | `medium` (default) |
| `pendenzen.source` | `meeting` / `review` / `manual` | `source` | pass through |
| `pendenzen.source` | `decision_log` | `source` | `decision` (name mismatch, normalised) |
| `pendenzen.source` | unknown/missing | `source` | `manual` (default) |
| `project.external_ref` | `proj/<slug>` | `project_id` | prefix `proj/` stripped |
| `wbs[].node_kind` | `phase\|deliverable\|…` | plan item `phase` | stored verbatim |
| `wbs[].external_ref` | `wp/<slug>` | plan item `id` | stored verbatim |
| `wbs[].owner` | `<string>` | plan item `assignee` | stored verbatim |
| `pendenzen[].external_ref` | `pd/<slug>` | pendenz `id` | stored verbatim |
| `open_assumptions` / `decisions` | (any) | `_skipped_sections` | listed, never stored |

**Entity-level mapping:** `project` → `projects` (1 record; `external_ref` prefix stripped → `project_id`; fallback = slug of `title`; final fallback `imported-project`). `wbs[]` → one `plan`, flattened into ordered `items` (`plan_id` = project id; each item `title`, `phase`=`node_kind`, `status`, `order`=array index, `id`=`external_ref`, `assignee`=`owner`). `risks[]` → `risks`. `pendenzen[]` → `pendenzen`.

**Idempotency:** `external_ref` values become row `id`s → re-importing the same export upserts instead of duplicating. This is why the prompt insists on deterministic, title-derived refs. Empty `open_assumptions`/`decisions` lists are **not** reported as skipped.

**Deterministic slug rules (`_slug()`, must match the prompt exactly):** lowercase, umlaut expansion (`ä→ae`, `ö→oe`, `ü→ue`, `ß→ss`), non-alphanumerics → `-`, trimmed, max 60 chars. **If you change one, change the other** — divergence breaks idempotent re-imports.

**Fields the prompt emits but the adapter currently ignores** (consumed silently, not in `_skipped_sections`): `meta`, `project.goal`, `project.phase`, `project.milestones`, and per-node `due`, `effort_hint_h`, `parent_ref`, `depends_on_refs`, `source_hint`. The WBS tree is *flattened* — `parent_ref`/`depends_on_refs` hierarchy is not reconstructed. Known limitation, not a bug.

## 3.4 The prompt → importer pipeline

```
Copilot prompt (.txt)  ──copy──▶  M365 Copilot  ──JSON──▶  paste into wizard
                                                                │
                                            POST /api/import/json
                                                                │
                             adapt_payload()  (import_adapters.py)
                    hermes.project_state/v1  ──▶  native importer dict
                                                                │
                          validate_import_payload() → import_payload()
                                                                │
                                        risks / plans / pendenzen / projects
```

`adapt_payload()` dispatches on the top-level `"schema"` string. **No** `schema` key = native format, passed through untouched (backward-compatible with hand-written imports). An **unknown** schema raises `ValueError("Unsupported schema: ...")`, surfaced as HTTP 422.

## 3.5 User guide (3-step workflow)

1. **Copy.** Dashboard → **Import JSON** (opens wizard on Step 1) → **Copy Copilot Prompt**. Toast: "Copied! Paste into Copilot". The full prompt (starting `# Aufgabe`) is on the clipboard.
2. **Run in Copilot.** Open M365 Copilot with your project repository in scope, paste, send. Copilot returns a single JSON object.
3. **Import.** Back in the wizard → **Next: Import JSON** → paste/upload the JSON. Hermes validates and imports.

**What a good response looks like:** first char `{`, last char `}`; no fences, no preamble; `"schema": "hermes.project_state/v1"`; statuses `open|in_progress|done|blocked` (never `todo`); risk impact `gering|mittel|hoch` (never `tief`).

**User troubleshooting**

| Symptom | Cause | Fix |
|---|---|---|
| Toast "Copy failed — select and copy manually" | Browser blocked clipboard (insecure origin) | Select text manually + Ctrl/Cmd-C, or use `https`/`localhost` |
| Nothing copied | Clicked before prompt loaded | Wait for the box to populate, click again |
| JSON wrapped in fences | LLM non-compliance | Delete fences before importing, or re-run |
| Import rejects an enum | Copilot used `todo`/`at_risk`/`tief` (impact) | Re-run; if recurring, report |
| Sections "skipped" | `open_assumptions`/`decisions` not stored | Expected, not an error |

## 3.6 Developer / maintainer notes

- **How the button works:** on modal open, `loadCopilotPrompt()` does `fetch('/static/prompts/copilot_state_export.txt')` and caches it. Editing the `.txt` and reloading is enough to change what users copy (not bundled). `copyPromptToClipboard()` awaits `navigator.clipboard.writeText`; on success `showImportToast('Copied! Paste into Copilot')`, on failure the manual-copy toast (old blocking `alert()` calls removed in `f5137b2`).
- **Known limitations:** LLM non-compliance is inevitable (prompt minimises, not eliminates). Unknown enums degrade **silently to defaults** (impact→`medium`, likelihood→`3`, source→`manual`) — a garbled risk imports as medium/medium, not a loud failure. WBS hierarchy + scheduling fields (`parent_ref`, `depends_on_refs`, `due`, `effort_hint_h`, milestones, goal/phase) are dropped. Clipboard API needs a secure context.
- **Debugging a user export:** get raw JSON → `adapt_payload(json.loads(raw))` (ValueError = wrong/missing schema, check for fences/truncation) → inspect adapted dict for default fallbacks → `validate_import_payload(adapted)` (empty list = clean) → check `_skipped_sections` and endpoint `errors[]`.
- **Updating the prompt:** edit enum lines in the prompt **and** the matching table / `_slug()` in the same change; update the worked example **and** its mirror fixture; run `pytest tests/test_copilot_adapter.py`; if a field became supported, remove it from the ignored list and add a test.
- **Versioning:** schema is versioned in the string (`hermes.project_state/v1`). Breaking change → bump to `/v2` in prompt + example, register a **new** adapter with `@_register("hermes.project_state/v2")` (keep v1), add a v2 fixture + tests. Never mutate v1's meaning in place. Additive optional fields the adapter ignores can stay on v1.
- **Testing layers:** `TestRegistryContract` (schema registered + in prompt) · `TestGoldenFile` (enum/shape exact) · `TestPromptExampleFixture` (example imports cleanly = 7 rows; enum lines no forbidden values) · `TestEndToEnd` / `TestEndpointIntegration` (adapt→validate→import; POST 200/422/native/skipped) · `test_json_import_ui.py::test_copy_copilot_prompt_shows_toast` (button copies real prompt, shows toast).

**FAQ:** the button sends nothing to a server (reads a static file, writes clipboard; only later `POST /api/import/json` hits the network). Prompt is German because target users are Swiss/German-speaking and enum values are domain terms. `tief` is valid for likelihood, forbidden for impact. A medium/medium risk means its enum wasn't recognised. Native payloads (no `schema` key) import directly.

## 3.7 Realistic example fixture — Helios Data Platform

**File:** `tests/fixtures/import/copilot_v1_helios_realistic_export.json`. A production-quality example of a real M365 Copilot export, generated after reading the live adapter code and verified to pass the C1 pipeline.

**Scenario:** B2B Analytics SaaS MVP, 2026-03-02 → 2026-09-30, EUR 420k budget, Berlin HQ + EU contractors, as of 2026-08-10 in `realisierung` (Feature-Complete milestone at-risk).

| Section | Count | Purpose |
|---------|-------|---------|
| Project | 1 | Goal, phase, milestones with status |
| WBS | 25 nodes | 5 phases with tree hierarchy |
| Risks | 10 | high/medium/low; German enums |
| Pendenzen | 16 | Meetings, reviews, manual |
| Open Assumptions | 6 | API stability, budget, contractor availability |
| Decisions | 6 | incl. 1 revisited (Auth0→Keycloak for DSGVO) |

**Real-world complexity:** blocked task `wp/auth-berechtigungen` (SSO vendor decision); overdue Feature-Complete milestone; revisited SSO decision; mitigated EUR/USD risk; bus-factor risk (one dev knows ETL). Tree hierarchy with `depends_on` chains. Cross-references encoded in free-text titles (e.g. "…bricht die ETL-Pipeline (wp/etl-pipeline)").

**Expected import:** `{"ok": true, "created": 28, "skipped": 0}` — 1 project → 1 plan; 10 risks; 16 pendenzen; 6 decisions + 6 assumptions in `_skipped_sections`.

```bash
curl -X POST http://localhost:8000/api/import/json \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/import/copilot_v1_helios_realistic_export.json
```

**Schema trade-offs demonstrated:** status enum drift (`todo`/`at_risk` declared valid in prompt but not in `PlanItem`); impact enum gap (risk #9 uses `"impact": "tief"` to demonstrate the silent map to `medium`); assumptions/decisions dropped to `_skipped_sections`; free-text cross-references (no structured reference fields).

**v2 roadmap ideas:** structured risk→WBS linkage (`risk.affected_wbs_id`); risk source enum; structured decision→impact links; importable assumptions & decisions; per-role effort breakdowns.

---

# Part 4 — Security Model & Guardrails

HERMES processes sensitive project-management data on a local machine. Five
independent guardrail layers prevent confidential information from leaking into
git history, log files, or API responses.

| Layer | Where | Blocks |
|-------|-------|--------|
| 1 — External data dir | `config.py` | DB files outside repo |
| 2 — Security headers | `webapp/server.py` | Browser-based attacks |
| 3 — Pre-commit hook | `scripts/hooks/pre-commit` | Accidental commits |
| 4 — Response validator | `webapp/server.py` | Confidential field leakage |
| 5 — PII dictionary | `.hermes/pii_terms.txt` | Organisation-specific terms |

> **Note:** the guardrail set is described two ways across the project's history —
> as (1 data dir, 2 headers, 3 hook, 4 response validator, 5 PII dict) in the
> security model, and as (1 hook, 2 PII dict, 3 API guard, 4 data dir, 5 RLock
> serialization) in the ops guardrails guide. Both are captured below; RLock
> serialization (data-integrity) is documented as Layer 5b.

## Layer 1 — External Data Directory

All runtime SQLite databases (tasks, job queue, risks, chat) and LLM traces are
stored **outside the repository tree** in a platform-specific directory.

| Platform | Default path |
|----------|-------------|
| macOS / Linux | `~/.hermes/data/` |
| Windows | `%LOCALAPPDATA%\hermes-data\` |

Override with `HERMES_DATA_DIR` (default in some configs is `./data`). Keeping
databases outside the repo means `git add .` can never accidentally stage a
database file, even if `.gitignore` is incomplete.

```bash
export HERMES_DATA_DIR=/var/lib/hermes/data
mkdir -p $HERMES_DATA_DIR/queue $HERMES_DATA_DIR/traces
git check-ignore -v data/risks.db     # confirm gitignored
git ls-files data/                     # should be empty
```

## Layer 2 — HTTP Security Headers

`_SecurityHeadersMiddleware` in `webapp/server.py` sets on every response:
`Content-Security-Policy` (restricts script/style sources), `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. The dashboard is local
but may be opened alongside untrusted browser tabs.

## Layer 3 — Pre-Commit Hook

`scripts/hooks/pre-commit` inspects every staged file and aborts the commit if it finds:

| Pattern | Reason |
|---------|--------|
| `*.db`, `*.db-wal`, `*.db-shm`, `*.log` | SQLite runtime files / raw traces |
| `.env`, `.env.*` | Credentials and secrets |
| `__pycache__/`, `node_modules/`, `.pytest_cache/`, `build/`, `dist/`, `.egg-info/` | Build artefacts |
| Terms in `.hermes/pii_terms.txt` | Organisation-specific PII (non-test files only) |

**Activate (one-time per clone; bootstrap does this automatically):**
```bash
git config core.hooksPath scripts/hooks
git config core.hooksPath          # verify → prints: scripts/hooks
```
On a violation the hook prints the blocked pattern and exits 1; git aborts. Remove the file with `git restore --staged <file>` and retry. **Test files (`tests/`) and `docs/` are exempt from PII scanning** — security tests legitimately reference PII patterns.

## Layer 4 — API Response Validation

`_validate_safe_json()` in `webapp/server.py` walks every response before it
leaves the server and raises (HTTP 403/500) if it finds:
- Forbidden field names: `raw_notes`, `evidence_quote`, `rationale`, `fix_suggestion`, `open_assumptions`, `assumptions`, `password`, `secret`, `token`, `api_key`, `private_key`, `credentials`
- Field names matching `internal_*` or `confidential_*`
- Absolute filesystem paths (`/Users/…`, `/home/…`, `C:\…`)
- Email addresses

Pydantic view models use `extra="forbid"` to block confidential fields at construction; the response validator is a second independent check. Endpoints covered include `/api/health` (via `@confidentiality_guard`), `/api/dashboard` (inline), `/api/refresh` (delegates), and all chat endpoints.

> **Caution (see Part 7, H1):** the guard historically also ran over *user-authored*
> chat content, which could trap a session behind a permanent 500 if a user typed
> their own email/path. The guard should protect *store/model-derived* fields, not
> user content echoed back to the same user.

## Layer 5 — PII Terms Dictionary

`.hermes/pii_terms.txt` — a plain-text list (one term per line, `#` for
comments) the pre-commit hook searches for in every staged diff. Base terms:

```
secret
password
api_key
access_token
private_key
```

Add organisation-specific terms (customer names, project codenames, system IDs)
without touching source code. The terms themselves are not PII, so committing
the dictionary is safe.

## Layer 5b — RLock Serialization (data integrity)

`ChatStore`, `RiskRegistry`, `TaskStore`, and `JobStore` each hold a
`threading.RLock`. All public methods acquire it before reading/writing,
preventing race conditions when multiple HTTP handlers or workers hit the same
store. RLock (reentrant) lets a single thread re-acquire the lock (e.g. when a
store method calls another internally). Without it, concurrent SQLite writes
cause `database is locked`, partial writes, or lost updates.

```python
class MyNewStore:
    def __init__(self, db_path: str) -> None:
        self._lock = threading.RLock()
        self._db_path = db_path
    def write(self, data: dict) -> None:
        with self._lock: ...
```

## Extending the guardrails
- **New PII term:** `echo "term" >> .hermes/pii_terms.txt` and commit.
- **New forbidden API field:** extend `FORBIDDEN_FIELDS` / pattern list in `_validate_safe_json`.
- **New blocked extension:** add to `FORBIDDEN_EXTS` in `scripts/hooks/pre-commit`.

## Security incident response
1. **Identify:** `git log --all -S "term" --oneline`; `grep -r "term" src/ tests/`.
2. **Remove from history (if committed):** revoke the credential first, then `git filter-repo --replace-text <(echo "term==>REDACTED")` (or BFG).
3. **Rotate credentials** — treat as compromised regardless of cleanup success.
4. **Harden:** add the term to `.hermes/pii_terms.txt` and the API guard.
5. **Audit responses/traces:** `grep -i "term" data/traces/llm_trace.jsonl`.
6. **Notify** the project security contact if project data was affected.

## Guardrail test coverage

| Test file | Covers |
|-----------|--------|
| `tests/test_pre_commit_hook.py` | Layer 3: hook blocks .db, .env, PII |
| `tests/test_confidentiality_guards.py` | Layer 4: API response filtering |
| `tests/security_audit.py` | Layers 1, 3, 5: file tracking, gitignore, hook presence |
| `tests/test_concurrent_stores.py` | Layer 5b: RLock under concurrent load |
| `tests/test_config_isolation.py` | Layers 1, 3: no runtime artifacts in git |

---

# Part 5 — Testing (Strategy, Simulations, Coverage)

## 5.1 Test Strategy (Phase 5)

**Status:** Planning complete · Target 90%+ coverage on core modules · Timeline 4 weeks.
Current baseline at time of planning: **877 tests passing** (unit, integration, perf, security).

**New tiers to add:** Sanity (20–30 tests, <60s, fail-fast gate) · Consistency/invariants (30–40, <3 min) · Unit expansion (877 → 930+) · E2E (18 → 45 tests, ~30 min). Total ~1000 tests; runtime budget <5 min offline + <30 min staging.

### Corrections to the original brief
1. **No REST CRUD endpoints for risks/plans.** There are zero `/api/risks/*` or `/api/plans/*` routes — risks/plans are library/store objects. Test CRUD via in-process store access (FastAPI TestClient, no live server). The only mutating HTTP routes are `POST /api/import/json` and chat routes.
2. **RiskStatus lifecycle + `accepted_at`.** `RiskStatus` = `open|mitigated|accepted|closed`. `registry.accept()` originally did not set an `accepted_at` timestamp — added so audit trails record sign-off time.
3. **E2E is Python Playwright, not TypeScript.** `tests/e2e/` already uses Python Playwright with pytest (`pytestmark = pytest.mark.e2e`). Extend it; do not add `@playwright/test`.

### Testing pyramid

| Tier | Target | Runtime | When | Coverage |
|------|--------|---------|------|----------|
| Sanity | 20–30 | <60s | Pre-commit + CI job 1 (gate) | tripwire |
| Consistency | 30–40 | <3 min | Every push + pre-deploy | 100% of invariants |
| Unit | 930+ | <90s | Every push | 90% line on core 4 modules |
| E2E | 45–50 | <30 min | Staging only, nightly | All 7 user journeys |

- **Sanity** catches "app didn't boot" / "SQLite locked" / "Ollama unreachable" in 60s. File `tests/test_sanity.py`, marker `sanity`. Endpoint coverage (`/api/health`, `/api/dashboard`, `/api/refresh`, `/api/import/json` happy + `{}` 4xx, chat routes), store CRUD in-process, config/data-dir/RLock presence.
- **Consistency/invariants** are the real production risk. Files: `test_invariants_plans.py` (immutability), `test_invariants_risks.py` (lifecycle + export filter), `test_invariants_chat.py` (isolation + FK cascade), `test_invariants_import.py` (atomicity + M2 idempotency), `test_invariants_concurrency.py` (20-thread RLock). Verify: plan versions immutable (append-only); FK cascade actually deletes (SQLite `PRAGMA foreign_keys=ON` is per-connection — assert real row deletion); import atomic (partial failure → 0 rows); risk lifecycle enforced (no `closed→open`); concurrent writes deterministic.
- **Unit expansion** fills edge/error/regression gaps per module (`risks/registry.py` list filter/sort, auto_create edge cases, `RiskNotFoundError`; `plans/editor.py` diffs, version-not-found, reorder; `chat/service.py`+`router.py` classification boundaries, language edge cases, oversized messages; `webapp/import_adapters.py` unknown schema, enum translation, tree flattening). Coverage gate scoped to 4 core modules: `--cov=hermes_assistant.risks --cov=hermes_assistant.plans --cov=hermes_assistant.chat --cov=hermes_assistant.webapp.import_json --cov-fail-under=90`.
- **E2E** validates browser wiring across 7 journeys: chat flow + Q2 collapse animation, risk lifecycle + export filter, plan editing + version history, Copilot import + M2 re-import idempotency, review feedback loop, keyboard + ARIA a11y, error messages (no stack traces).

### Regression guards (from the audit)

| Fix | Regression test |
|-----|-----------------|
| C1 (Copilot adapter) | `test_adapt_project_state_v1_schema_maps_enums` (exists) |
| C2 (XSS) | `test_import_error_escaped_in_html` (exists) |
| C3 (RLock) | `test_concurrent_writes_deterministic` |
| H1 (guard before persist) | `test_confidentiality_violation_no_persist` |
| H5 (atomic import) | `test_import_atomicity` |
| M2 (idempotency) | `test_m2_idempotency_external_ref` |

### Anti-flake rules
Explicit waits, never `time.sleep()`; assert end-state not intermediate animations; isolate DB per run (`tmp_path`); capture traces on failure (`pytest --tracing retain-on-failure`); screenshot on error.

### CI shape
```
Job 1: pytest -m sanity                              (fail-fast, <60s)
Job 2: pytest -m "not e2e and not integration"       (unit+invariants, <90s)
Job 3: staging pytest -m e2e                          (nightly + pre-release, ~30 min, traces)
```
**Add:** `sanity` marker (register in `pyproject.toml`); optional `pytest-xdist` (`--dist loadscope` only, avoid SQLite contention); `axe-core` for a11y. **Do NOT add:** TypeScript Playwright, Selenium/Cypress, remote service mocking. Name new invariant files `test_invariants_*.py` (avoid collision with the existing `test_consistency.py`, which tests MECE/multi-model consistency).

## 5.2 Edge-Case Simulation Suite (S1–S10)

`tests/sim/` is a dedicated fault-injection and load-simulation suite, separate
from unit/integration/e2e. It exercises concurrency races, on-disk corruption,
partial/silent failures, slow/hung Ollama calls, boundary conditions, replay
idempotency, and resource exhaustion against the SQLite stores (`RiskRegistry`,
`PlanEditor`, `TaskStore`, `ChatStore`, `JobStore`) and the JSON import pipeline.
No test touches a live Ollama or `data/risks.db` — every store opens against
`tmp_path`; every LLM call is monkeypatched at the transport layer.

**Layout:** `faults.py` (barrier-synchronised thread runners, `corrupt_wal`/`truncate_file`/`plant_stale_lock`, `flaky()` decorator, `raw_conn()` lock-bypassing inspection) · `snapshots.py` (`snapshot()` checksummed table fingerprints, `reconcile()` row-count-delta diffing, `assert_invariants()` re-deriving enum/range/timestamp/FK/version rules from raw tables) · `test_sim_p0.py` (S1–S3) · `test_sim_faults.py` (S4, S5, S6, S8, S10) · `test_sim_load.py` (S7, S9, marked `slow`).

- **S1 — cross-connection import-vs-live race.** 200 live creates racing a 1000-row import on the same `risks.db`. Expected **pass** — WAL + `busy_timeout` + per-instance `RLock` serialise two independent connections.
- **S2 — plan version collision (`xfail`).** Two `PlanEditor` connections update the same `plan_id`; `_next_version()` reads `MAX(version)+1` with no cross-connection coordination → one loses with `IntegrityError`. `xfail` pending a decision on cross-connection version atomicity.
- **S3 — closed-risk resurrection via re-import (`xfail`).** `RiskRegistry.update()` enforces the D5 lifecycle (`closed` terminal), but `_import_risks` pass-2 uses raw `INSERT OR REPLACE`, bypassing the guard → a closed risk re-imported with `status:"open"` is silently resurrected. `xfail` pending a decision on enforcing lifecycle on the import path.
- **S4 — corruption recovery (3 variants).** Corrupted `-wal`, truncated main db, stale/corrupt `-shm`. WAL corruption and stale-shm degrade gracefully (silent loss acceptable, crash not; severe WAL corruption may surface as a clean `DatabaseError`); a truncated main file always raises a typed `DatabaseError`.
- **S5 — cross-entity partial failure.** Risks import in one transaction; plans/pendenzen via sequential public-API calls with no surrounding transaction. A fault in the second of three plans confirms: already-committed risks and the first plan survive; the failing and never-attempted plans are absent.
- **S6 — slow/hung Ollama (3 variants).** High-latency-but-successful calls traced accurately; a hung connection (`ReadTimeout`) surfaces as `OllamaTimeoutError` traced as failure; 20 concurrent `chat()` calls against a 4-at-a-time backend all complete without deadlock/starvation.
- **S8 — boundary conditions.** Empty batch, single item, 10,000-char title (exact round-trip), batch at the 10,000-item cap (succeeds), 10,001 items (rejected), zero-`effort_days` milestone (clamped to 1 working-day minimum), pathologically deep JSON (`json.loads` raises catchable `RecursionError`/`ValueError`).
- **S10 — replay idempotency.** Same mixed payload imported 10×: first creates, nine replays are pure updates with zero new rows; final state = one risk (single `external_ref`), one plan (10 versions — each import legitimately bumps), one pendenz.
- **S7 — resource exhaustion (`slow`).** 100k risks (10× 10k batches) listed in full; a single plan with 10,000 items; 1000 concurrent chat writes; a 10k-row import repeated 3× with `tracemalloc` peak comparison as a leak canary. Generous but blow-up-catching envelopes.
- **S9 — long-running accumulation (`slow`, soak proxy).** 10,000 messages in one session; 100 plan versions diffed end-to-end; 50 review jobs drained by 8 concurrent worker threads on one `JobStore` (each worker owns its own connection, since `JobStore` does not open with `check_same_thread=False`), verifying atomic claim semantics with no double-processing or lost jobs.

```bash
pytest tests/sim/ -v --tb=short -m "not slow"   # per-PR (S1, S4-S6, S8, S10; S2/S3 xfail)
pytest tests/sim/ -v --tb=short                 # nightly (full incl. S7/S9)
```
`slow` and `serial` markers registered in `pyproject.toml`. `serial` flags heavy shared-resource sims that must not run in parallel under pytest-xdist.

## 5.3 Coverage Report (snapshot 2026-08-01)

Runner: Python 3.11 / pytest 9.0.3 / pytest-cov 7.1.0. HTML report: `coverage-report/index.html`.

| Metric | Value |
|--------|-------|
| Tests collected | 752 |
| Tests passing | 744 |
| Tests skipped (integration, e2e) | 9 |
| Tests failing (pre-existing) | 6 |
| **Overall coverage (measured modules)** | **70%** |
| Core features coverage | ~93% |
| Guardrails coverage | ~98% |

**High-coverage core & guardrails:** `chat/store.py` 100%, `chat/service.py` 93%, `chat/router.py` 94%, `chat/executor.py` 82%; `webapp/import_json.py` 93%, `import_adapters.py` 86%, `chat_api.py` 95%, `server.py` 89%; `risks/registry.py` 98% (incl. RLock), `risks/model.py` 94%; `plans/editor.py` 90%, `plans/model.py` 100%; `config.py` 96%; `jobqueue/jobs.py` 99%; `llm/tracing.py` 95%. HERMES domain / tasks / scheduling / rubrics all 86–100%. `agents/critic.py` 98%, `agents/panel.py` 91%.

**Low coverage (by design — optional deps / live services / UI runtime):** `cli.py` 3% (needs `docx`/`pypdf`/`chromadb`), `rag/ingest.py` 12%, `rag/parsers.py` 6%, `rag/retrieve.py` 0% (live Chroma), `tui/*` 0–49% (Textual runtime), `agents/redteam.py` 32% + `agents/consistency.py` 23% (live Ollama), `suggestions/store.py` 66% (deferred M10), `dashboard_html.py` 67%.

**Excluded test modules (import errors, optional deps):** `test_cli*.py`, `test_consistency.py`, `test_ingest.py`, `test_parsers.py`, `test_rag_integration.py`, `test_redteam.py`, `test_retrieve.py`, `tests/e2e/` — all pass in a fully-installed environment.

**Known pre-existing failures (not regressions):** three `test_scheduling.py::test_zurich_*` (workalendar holiday data mismatch); `test_panel_eval.py`/`test_panel_queue.py` CLI tests (optional-dep `ModuleNotFoundError`).

---

# Part 6 — Deployment & Operations

Version: Phase 5 (Text-Based Chat). Platform: macOS 14+ / Linux (Ubuntu 22.04+).
Minimum RAM 8 GB (16 GB recommended for local LLM).

## Prerequisites

| Dependency | Version | Notes |
|-----------|---------|-------|
| Python | 3.11+ | `python3.11 --version` |
| Ollama | 0.3+ | Must be running before starting HERMES |
| RAM | 16 GB | 8 GB minimum |
| Disk | 10 GB free | Model weights (~2 GB) + data dir |
| `git` | Any | For clone and hook activation |

**Install Ollama**
```bash
brew install ollama                              # macOS
curl -fsSL https://ollama.com/install.sh | sh    # Linux
ollama pull llama3.2:3b                           # default model for this deployment
ollama run llama3.2:3b "Hello"
```

> Note: this deployment defaults to `llama3.2:3b` for a lightweight local install.
> The full production roster (Part 1 §11) uses the Qwen3-30B-A3B MoE + gpt-oss-20b;
> configure via `HERMES_MODEL` / `HERMES_CRITIC_MODEL`.

## Installation
```bash
git clone <repo-url> hermes-assistant
cd hermes-assistant
bash scripts/bootstrap.sh
```
Bootstrap creates `.venv/`, runs `pip install -e ".[webapp,dev]"`, creates the data dir (`~/.hermes/data/` or `./data/`), activates the pre-commit hook (`git config core.hooksPath scripts/hooks`), and verifies Ollama connectivity.

**Manual install (if bootstrap unavailable)**
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[webapp,dev]"
mkdir -p data/queue data/traces
git config core.hooksPath scripts/hooks
```

## First-time setup & config
```bash
# data dir
mkdir -p data/queue data/traces                 # or set HERMES_DATA_DIR
# verify Ollama
curl http://localhost:11434/api/tags
# env vars (defaults shown)
export HERMES_OLLAMA_URL=http://localhost:11434
export HERMES_MODEL=llama3.2:3b
export HERMES_CRITIC_MODEL=llama3.2:3b
export HERMES_DATA_DIR=./data
```

## Running
```bash
bash scripts/start-web.sh                 # web dashboard on :8000
bash scripts/start-web.sh --port 8080     # custom port
# or directly:
uvicorn hermes_assistant.webapp.server:app --host 127.0.0.1 --port 8000 --reload
hermes tui                                # terminal interface
```
Dashboard: `http://localhost:8000`. API docs: `http://localhost:8000/docs`.

## Verify the installation
```bash
pytest tests/ -q --tb=short --ignore=tests/e2e/ --ignore=tests/test_rag_integration.py
# Expected: 744+ pass, <10 fail (pre-existing), 9 skip

curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message": "Hello", "session_id": "smoke-test"}'
curl -X POST http://localhost:8000/api/import/json -H "Content-Type: application/json" \
  -d '{"risks": [], "tasks": [], "plans": []}'
```

## Monitoring
- Logs: `data/traces/llm_trace.jsonl` (LLM request/response traces, JSONL); stdout with `--reload`; configure a log file via uvicorn `--log-config`.
- Job queue: `hermes jobs list`, `hermes jobs status <job-id>`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ConnectionRefusedError [Errno 61]` (Ollama) | `ollama serve &` or `brew services start ollama` |
| `PermissionError` on `data/*.db` | `chmod 755 data/`; `chmod 644 data/*.db` |
| `[Errno 48] Address already in use` | `lsof -i :8000` then kill, or `--port 8080` |
| `ModuleNotFoundError: docx` | `pip install -e ".[webapp,dev]"` (+ `python-docx pypdf openpyxl` for full RAG) |
| Pre-commit blocks a commit | `git restore --staged <file>`; ensure `data/*.db` in `.gitignore` |

## Upgrading
```bash
git pull origin main
source .venv/bin/activate
pip install -e ".[webapp,dev]" --upgrade
pytest tests/ -q --tb=short --ignore=tests/e2e/
```

## Production hardening (staging → production)
1. `DEBUG=false`. 2. nginx/caddy in front of uvicorn (TLS). 3. Bind uvicorn to `127.0.0.1` only (never `0.0.0.0` unless behind a reverse proxy). 4. `HERMES_DATA_DIR` on a backed-up volume. 5. Log rotation for `llm_trace.jsonl` — implemented: size-based rotation via `HERMES_TRACE_MAX_MB` (default 50 MB), keeps up to 5 numbered backups (`.1`–`.5`), thread-safe (`threading.Lock` + atomic `os.rename`). 6. Run `pytest tests/e2e/` with Playwright installed. 7. `OLLAMA_HOST=127.0.0.1` (already default).

---

# Part 7 — Status & Quality Reports

> This part consolidates the audit remediation summary, the live-server
> validation campaign, the coverage-backed production-readiness checklist, and
> the Phase 5 stakeholder summary. Metrics differ slightly across the reports
> because they were taken at different dates (coverage snapshot 744/752 tests;
> audit remediation 828+/861 tests) — both are preserved as historical record.

## 7.1 Phase 5 at a glance

**HERMES Local Assistant** is a fully local AI assistant for HERMES 2022, running
entirely on a MacBook Air (16 GB M4) with no cloud calls (Ollama, `llama3.2:3b`
default). Capabilities: text chat for project Q&A · JSON import (risks/tasks/plans)
· risk registry with version history · plan editor with change tracking · async
critic/review job queue · scheduling + calendar integration · RAG ingestion.

Phase 5 delivered the chat assistant end-to-end across 4 work phases:

| Phase | Work | Commits |
|-------|------|---------|
| 1 | Security audit (30 findings) | 3 |
| 2 | Remediation (19 fixes applied) | 3 |
| 3 | Test suite (rubrics, critic, queue, CLI, integration) | 3 |
| 4 | Final validation, coverage, production-readiness docs | 1 |
| **Total** | | **10** |

| Metric | Value |
|--------|-------|
| Security findings identified / fixed / deferred | 30 / 19 / 11 |
| Security audit checks | 9 / 9 PASS |
| Tests passing | 744 (~760 in suite) |
| Core feature coverage | ~93% |
| Guardrail coverage | ~98% |
| Overall measured coverage | 70% |
| Regressions introduced | 0 |

## 7.2 Audit remediation (30 findings, 19 fixed)

**Objective:** proactively catch and fix bugs from a security/quality audit before production. **Result:** 30 findings; all Critical (3) and High (8) resolved, most Medium (5) complete. 861 tests passing, 0 regressions.

**Critical (3, complete)**
- **C1 — Copilot schema adapter.** Copilot exports `hermes.project_state/v1` (German enums, tree) but the importer expected native (English, flat) → 95% of data silently dropped. Fixed with a deterministic adapter (`import_adapters.py`): `project→projects`, `wbs→plans` (tree flattening), German→English enum tables, unmapped sections surfaced (not silent), versioned registry. Commit `48f379f`; 34 golden-file tests + 101 import tests.
- **C2 — XSS in import error rendering.** Server error strings echoed via `innerHTML` unescaped (`severity: "<img src=x onerror=…>"` executes). Two-layer fix: escape all server strings through `escapeHtml()` at render sinks (`index.html:200,213`) + server-side sanitisation. Commit `49628b5`.
- **C3 — SQLite concurrent-access race.** Single shared `Connection` with `check_same_thread=False` + `run_in_threadpool` → interleaved transactions, "recursive use of cursors", corruption. Added `threading.RLock` to all 4 stores (guard the whole execute+commit+read-back in one critical section). Commits `25cfd16` (3 stores) + `249dd1e` (RiskRegistry); 107 concurrency tests.

**High (8/8, complete):** H1 move confidentiality guard before persistence · H2 genericize guard error detail · H3 safe fallback for unhandled results · H4 normalize executor errors · H5 single-transaction per-entity import · H6 implement/remove reviews entity · H7 chat accessibility (aria-live) · H8 import-status accessibility. Commits `cc06b1b`, `0df71ed`, `99215f0`.

**Medium (5 complete):** M1 real question-answering (routes by keyword to risks/plans/tasks, no dead-end placeholder) · M2 import idempotency via `external_ref` (`find_by_external_ref()` upsert) · M6 language detection (German-without-umlauts + French keyword heuristics) · M7 config-tunable `chat_confidence_threshold` (env `CHAT_CONFIDENCE_THRESHOLD`, default 0.7) · M8 docstring updates.

**Deferred to Phase 6:** M10 suggestion context hydration (context fields now populated by service layer, full suggestion-generation deferred), M3–M5, L1–L7 polish.

**Security validation checklist (all ✅):** no stored/reflected XSS · no injection (SQL parameterized, PII validated) · no data-at-rest leaks (guard before persistence) · no race conditions (RLock) · no silent data loss (atomic imports, unmapped surfaced) · no auth bypass · no confidential-term disclosure (500s generic, real detail server-logged only).

## 7.3 Live-server validation campaign (2026-08-10)

Automated suite against `http://localhost:8000`, Tiers 1–6 (46 checks) + Tier 5 concurrency; Tier 7 (Playwright) skipped. **Verdict: NEEDS FIXES** — 44/46 pass, 2 HIGH blockers, 2 MEDIUM + 1 LOW.

**H1 — BLOCKER: confidentiality guard blocks user's own email.** A user email in a chat message matches `_EMAIL_RE` in stored content → `GET /api/chat/sessions/{id}` returns 500 forever (history permanently inaccessible). Root cause: `send_message` guards only the assistant response; user content persisted unguarded; `get_session` (wrapped in `@confidentiality_guard`) runs `_validate_safe_json()` over all messages incl. user content. **Fix direction:** exclude user-role message `content` from email/path checks (recommended), or redact instead of 500, or separate "source of truth" guard from transport guard.

**H2 — BLOCKER: import with explicit null optional field crashes.** A risk with explicit `null` for owner/severity/likelihood → unhandled exception → 500 instead of graceful per-item skip. Root cause: `raw.get("owner", "")` returns `None` for explicit null (defaults only apply to *missing* keys); `Risk(owner=None)` / `RiskSeverity(None)` / `int(None)` raises; no try/except in pass 1. **Fix:** coerce present-but-null → default (`raw.get("owner") or ""`), validate severity/status/likelihood before constructing, wrap in try/except appending to `result.errors`, return 200 with `skipped`.

**M3 — risk import missing idempotency key.** Re-import without `id` creates duplicates (pendenzen have `external_ref` dedup, risks do not). Fix: document that risks need stable `id`/`external_ref`, or add external_ref dedup mirroring pendenzen (see Part 8 PLAN 1). **M4 — runtime DB tracked in git:** `src/hermes_assistant/data/tasks.db` committed despite `.gitignore` (already-tracked file); `git rm --cached`. **L5 — import atomicity is per-entity-type, not global** (risks commit even if plans fail); matches docstring but note the expectation gap.

**False positives (correct behavior):** empty title / invalid severity → 200 + skip + error listing (graceful); XSS import → escaped; cross-entity atomicity → per-entity by design.

**Affirmed passing:** Tier 1 health 10/10 · Tier 2 journeys 20/20 · Tier 4 invariants 10/10 (DB-level: plan immutability, `closed→open` rejected, FK cascade, accepted_at set, session isolation, RLock no "database is locked") · Tier 5 concurrency (50 concurrent writes → exact 51 rows, zero corruption; 5 MB payload no OOM; <1% lock-timeout) · Tier 6 security 8/8 (no XSS/injection/leaks; CSP + X-Frame-Options DENY + nosniff present; export_public filters confidential).

**Note:** validation wrote test rows to the live dev DB (`life-*`, `idem-*`, `sqli-*`, `atom-*`, `camp-*` etc.); clear before demo/staging.

## 7.4 Production readiness checklist (Phase 5) — APPROVED for staging

- **Security (9/9):** data dir untracked · `.env`/`.db`/`.log` blocked by hook · PII dict active · `_validate_safe_json` active · Ollama loopback-only · no hardcoded creds · startup config validation.
- **Testing:** 744 passing · 9 skipped (live services) · 6 pre-existing failures (tracked) · 90%+ core, 95%+ guardrails · concurrency + config-isolation + security-audit suites pass.
- **Performance:** HTTP < 500 ms · store ops < 100 ms · config/validation < 10 ms · job queue non-blocking · ChromaStore lazy init.
- **Data integrity:** no deadlocks (RLock) · no corruption (atomic read-modify-write) · WAL mode · immutable plan versions · pydantic-validated risks · per-session UUID chat history.
- **Accessibility:** ARIA labels on form elements · keyboard nav (Tab/Enter/Escape) · `role="status"` on import messages · high-contrast tokens. **Deferred:** full WCAG 2.1 AA audit.
- **Config:** `HERMES_DATA_DIR`, `HERMES_OLLAMA_URL` (loopback), `HERMES_MODEL`, `HERMES_CRITIC_MODEL` documented in `config.py`; no secrets in names/defaults.

**Known limitations:** E2E Playwright not in CI (run on staging); optional RAG deps (`python-docx`, `pypdf`) not in base image; 3 scheduling holiday test failures (`workalendar` data); `suggestions/store.py` 66% (deferred M10). **Deferred features:** M10 suggestion RAG, L-tier UI polish, WCAG audit, Playwright CI, multi-tenant isolation.

## 7.5 Next steps (Phase 6)
1. Playwright CI pipeline. 2. M10 suggestion RAG (semantic search over past plans/risks). 3. L-tier UI polish (responsive, dark mode, a11y audit). 4. Multi-model per-session routing. 5. Log rotation + monitoring for long-running deployments. 6. Fix or replace `workalendar` holiday data. Plus deploy H1/H2 blocker fixes + regression guards before production.

## 7.6 Repository layout (as-built, Phase 5)

```
hermes-assistant/
├── src/hermes_assistant/
│   ├── chat/                 # session, store, router, LLM executor
│   ├── webapp/               # FastAPI server, import endpoints, chat API
│   ├── risks/                # Risk registry (SQLite + RLock)
│   ├── plans/                # Plan editor (immutable versions)
│   ├── agents/               # critic, panel, consistency, redteam
│   ├── jobqueue/             # async job store + worker
│   ├── rag/                  # ChromaDB store, chunking, ingest, retrieve
│   ├── scheduling/           # deadline derivation, ICS export
│   └── config.py             # pydantic-settings config
├── tests/                    # ~760 tests + tests/sim/ + tests/e2e/
│   ├── security_audit.py     # 9-point security checklist
│   └── e2e/                  # Playwright browser tests
├── scripts/
│   ├── hooks/pre-commit      # guardrail hook
│   ├── bootstrap.sh          # one-command install
│   └── start-web.sh          # start uvicorn
├── docs/MASTER.md            # this document (single source of truth)
├── data/                     # runtime artifacts (gitignored)
└── .hermes/pii_terms.txt     # PII dictionary
```

---

# Part 8 — Coder-Ready Implementation Plans

> Detailed, ready-to-execute specs for the follow-up work identified by the audit
> and validation campaign. Based on `import_json.py`, the risk store, and the
> pendenzen M2 pattern as of 2026-08-16.

| Plan | Status | Files | Effort | Dependencies |
|-------|--------|-------|--------|--------------|
| PLAN 1: Risk external_ref M2 | **Done** (`registry.py` has `external_ref` + `get_by_external_ref`) | 4 files | 3–4 hrs | None |
| PLAN 2: Fix phantom API in this doc's examples | Done inline | — | 30 min | None |
| PLAN 3: Lifecycle regression tests | **Done** (D5, commit `0d58be2`) | 1 file | 1 hr | None |
| PLAN 4: M10 hydration | **Done** (`chat/service.py` injects stores, commit `663a6c7`) | Phase 6 | — | PLAN 1 first |

**Execution order:** PLAN 1, 2, 3 in parallel → then Phase 1–4 test suites. **(all complete)**

Also landed since this table was drafted: **H1** user-authored-content guard exclusion
(`_redact_user_authored` in `chat_api.py`) and **H2** null-optional import coercion
(`raw.get(...) or ""` + per-item try/except in `import_json.py`). The Part 8 backlog
above is therefore **cleared**; the next work is **Part 8B — Phase 7 Feature Backlog** below.

---

# Part 8B — Phase 7 Feature Backlog (coder-ready)

> Designed 2026-08-22 against the as-built code (not the older Part 8 plans, which
> are now complete). Five high-impact, mostly self-contained features. Each is
> pickable independently unless a dependency is noted. Convention reminders:
> `ruff check . && mypy src && pytest -q` green before done; new invariant files are
> `test_invariants_*.py`; no cloud calls; confidentiality guard covers any new API
> response; store methods that touch SQLite acquire `self._lock` (RLock, Layer 5b).

| Feature | Impact | Files | Effort | Dependencies |
|---------|--------|-------|--------|--------------|
| F1: Risk Registry dashboard screen | High (visible gap) | ~5 | 6–8 hrs | None |
| F2: Copilot import v2 — WBS tree + milestones/dates → scheduler | High (data-loss fix) | ~5 | 8–12 hrs | None (F5 helps) |
| F3: Streaming chat responses (SSE) | High (perceived latency) | ~4 | 6–8 hrs | None |
| F4: M10 full — RAG-backed suggestions | Medium | ~4 | 8–10 hrs | F1 useful, not required |
| F5: Ops hardening — trace rotation + fix holiday tests | Medium (reliability) | ~4 | 3–5 hrs | None |

**Recommended order:** F5 (unblocks green CI) → F1 → F2 → F3 → F4. F1/F3/F5 are
parallelisable across coders.

## F1 — Risk Registry dashboard screen

**User story:** *As a project lead, I open the dashboard and see a Risks screen
listing every risk (title, severity, likelihood, status, score) so I can review the
register without using chat or the CLI.*

**Why:** The Risk Registry is a first-class store with lifecycle
(`open→mitigated→accepted→closed`), version history, and `export_public()`, but the
dashboard has **no** risk view — `DashboardData` (`dashboard_html.py:119`) has no
`risks` field and `screens.js` has only Projects / ProjectDetail / Pendenzen /
Reviews. Chat can *create* risks a user then cannot *see* in the UI.

**Acceptance criteria:**
- `GET /api/dashboard` (and `?project_id=X`) returns a `risks: []` array built from
  `RiskRegistry.export_public()` (confidential risks excluded — reuse the existing
  filter, never `list()` raw).
- Each risk row carries only non-confidential fields: `id`, `title`, `severity`,
  `likelihood`, `status`, computed `score` (severity×likelihood), `updated_at`.
  **No** `raw_notes`/`rationale`/owner-email — must pass `_validate_safe_json`.
- New Risks screen reachable via nav + keyboard shortcut `5`; sortable by score;
  status shown with colour coding (open=red, mitigated=amber, accepted=blue,
  closed=grey), mirroring the Reviews verdict colours.
- Empty state renders "No risks recorded" (no crash on zero risks).
- Screen respects the active `project_id` drill-in.

**Files:**
- `src/hermes_assistant/dashboard_html.py` — add `RiskRow(BaseModel)` (extra="forbid"),
  add `risks: list[RiskRow]` to `DashboardData`, populate in `load_dashboard_data()`
  from a `RiskRegistry(settings...risks_db)` call filtered by `export_public()`.
- `src/hermes_assistant/webapp/server.py` — no route change needed (dashboard endpoint
  already returns `DashboardData`); confirm `_validate_safe_json` still passes.
- `src/hermes_assistant/webapp/static/screens.js` — new `RisksScreen` component.
- `src/hermes_assistant/webapp/static/app.js` — register screen, add `5` shortcut + nav.
- `src/hermes_assistant/webapp/static/style.css` — status colour tokens (reuse verdict vars).

**Testing:** `tests/test_webapp_endpoints.py` — dashboard returns risks, confidential
excluded, score computed, `extra="forbid"` rejects unknown field; a
`test_confidentiality_guards.py` case asserting a risk with an email owner does **not**
leak. E2E (optional, `e2e/`): nav to Risks, rows render, sort by score.

## F2 — Copilot import v2: preserve WBS hierarchy + milestones/dates → scheduler

**User story:** *As a project lead, when I import a Copilot export the WBS tree,
milestone dates, and effort hints survive, so `hermes schedule`/`ics` can produce a
real calendar instead of losing 40% of the export.*

**Why:** `_adapt_project_state_v1` **flattens** the tree and silently drops
`parent_ref`, `depends_on_refs`, `due`, `effort_hint_h`, `project.milestones`,
`project.goal`, `project.phase` (documented in Part 3.3 "Fields the prompt emits but
the adapter ignores"). The scheduler (`scheduling/derive.py`, `ics.py`) and the
`DeadlineView` already exist but are **never fed by imports** — the biggest
value-per-hour gap in the product. This is the "v2 roadmap" from Part 3.7.

**Acceptance criteria:**
- Adapter preserves `parent_ref` and `depends_on_refs` on plan items instead of
  discarding them (map to the plan-item parent/dependency fields; add them if absent).
- `due` and `effort_hint_h` per node are carried through to plan items.
- `project.milestones[]` import as milestone-kind rows (not dropped); `project.goal`
  and `project.phase` persist on the project record.
- Round-trip: the Helios realistic fixture
  (`copilot_v1_helios_realistic_export.json`) imports with its 25-node tree
  **hierarchy intact** (parent chains reconstructable) and milestone dates present.
- Backward compatible: existing flat native imports and the v1 worked example still
  yield the documented row counts (7 rows for the small example). No enum contract
  change → the Copilot prompt file needs **no** edit (fields already emitted).
- Update Part 3.3 to move these fields out of the "ignored" list; update the
  `test_prompt_example_roundtrips` expectation only if counts change.

**Files:**
- `src/hermes_assistant/webapp/import_adapters.py` — extend `_adapt_project_state_v1`:
  stop flattening, carry `parent_ref`/`depends_on_refs`/`due`/`effort_hint_h`, emit
  milestones, persist goal/phase.
- `src/hermes_assistant/webapp/import_json.py` — accept the new plan-item fields;
  ensure atomicity unchanged.
- `src/hermes_assistant/plans/model.py` / `plans/editor.py` — add optional
  `parent_id`, `depends_on`, `due`, `effort_h` fields to the plan item model if not
  present (keep existing versions valid — optional with defaults).
- `tests/test_copilot_adapter.py` + `tests/test_json_import_unit.py` — hierarchy
  preserved, dates carried, milestones imported, v1 example still 7 rows.
- `docs/MASTER.md` Part 3.3 — update the ignored-fields paragraph.

**Notes / gotchas:** keep it on **v1** (additive, adapter was already receiving these
fields) — do *not* mint `hermes.project_state/v2` unless the enum contract changes.
Watch idempotency: re-import must still upsert by `external_ref` (S10 replay test must
stay green). Cycles in `parent_ref`/`depends_on_refs` are already excluded by the
prompt checklist; still guard against them in the adapter (drop the offending edge,
don't crash).

## F3 — Streaming chat responses (Server-Sent Events)

**User story:** *As a user, the assistant's reply streams token-by-token so a 15
tok/s local model feels responsive instead of a 10-second dead wait.*

**Why:** `chat_api.py` has no `StreamingResponse`; production latency is "dominated by
ROUTER inference (~15 tok/s)" (Part 2.2). Streaming is the single biggest perceived-
latency win and was explicitly listed as a follow-up. Classification/execution stay
synchronous; only the final **formatted answer** streams.

**Acceptance criteria:**
- New `POST /api/chat/message/stream` returns `text/event-stream`; emits `data:` chunks
  as the answer is produced, then a terminal `event: done` carrying the persisted
  `message_id` + suggestions.
- The turn is still classified → executed → persisted exactly once (persist the full
  assembled text after streaming completes; never persist partial content).
- Confidentiality guard runs on the **assembled** response before the `done` event; a
  violation ends the stream with `event: error` (generic message, no detail).
- Falls back cleanly: if the ROUTER/answer model is unavailable, stream the safe
  `answer_question` fallback (mirror the existing degradation path).
- Non-streaming `POST /api/chat/message` remains unchanged (back-compat).
- Frontend `chat.js` consumes the SSE stream, appends tokens to the assistant bubble,
  shows the typing indicator until first token, renders suggestions on `done`.

**Files:**
- `src/hermes_assistant/chat/service.py` — add a generator variant (e.g.
  `stream_turn()`) yielding text chunks; reuse `_classify`/execute/format; persist once.
- `src/hermes_assistant/llm/client.py` — expose a streaming chat (Ollama supports
  `stream=True`); keep the existing blocking `chat()`.
- `src/hermes_assistant/webapp/chat_api.py` — new SSE route via
  `fastapi.responses.StreamingResponse`.
- `src/hermes_assistant/webapp/static/chat.js` — `EventSource`/`fetch`-reader client.

**Testing:** `tests/test_chat_service.py` — `stream_turn` yields chunks then persists
one message; guard blocks a leaking assembled response; degradation streams fallback.
Integration (`test_chat_integration.py`) — SSE route returns `text/event-stream`,
terminal `done` carries `message_id`. Use a fake streaming LLM client (extend the
existing duck-typed `LLMClient` fake); **no live Ollama** in tests.

## F4 — M10 full: RAG-backed suggestions over past plans/risks

**User story:** *As a user, after a chat turn I get 1–3 concrete next-step suggestions
drawn from semantically-similar past plans/risks, not just static intent buttons.*

**Why:** M10 hydration landed (context now carries `risks`/`plan_summary`/
`open_task_count`), but the *generation* half — semantic retrieval over prior
project state — is still stubbed (`suggestions/store.py` at 66%, `SuggestionStore.score`
is a placeholder). This turns the suggestion bar from canned strings into grounded
recommendations. Fully local (bge-m3 via the existing RAG store).

**Acceptance criteria:**
- After a turn, `_build_suggestions()` retrieves top-k similar historical
  risks/plan-items (via the existing Chroma/`bge-m3` retriever) scoped to the
  `project_id`, ranks them, and returns ≤3 suggestions with a real relevance score.
- Degrades to the current static suggestions when Chroma/embeddings are unavailable
  (no hard dependency on RAG being installed — mirrors `cli.py` optional-dep pattern).
- Suggestions never leak confidential content (titles only; guard-checked).
- Deterministic in tests (inject a fake retriever; no live embeddings).

**Files:**
- `src/hermes_assistant/chat/service.py` — wire a retriever into `_build_suggestions()`.
- `src/hermes_assistant/suggestions/store.py` — real `score()` /
  ranking; persist generated suggestions for audit.
- `src/hermes_assistant/rag/retrieve.py` — add a scoped `similar_to(text, project_id)`
  helper if none exists.
- `tests/test_chat_service.py` / new `test_suggestions.py` — grounded suggestions with a
  fake retriever; graceful fallback when RAG absent; confidentiality filter.

**Dependency:** F1 makes the payoff visible (risks in UI), but F4 does not require it.

## F5 — Ops hardening: trace rotation + fix holiday tests

**User story:** *As an operator, `llm_trace.jsonl` can't grow unbounded and the test
suite is fully green so CI is trustworthy.*

**Why:** Two standing ops items: (a) `data/traces/llm_trace.jsonl` has no rotation
(Part 6 "Production hardening" lists it as a manual TODO) — an append-only JSONL will
grow without bound on a long-running box; (b) three `test_scheduling.py::test_zurich_*`
tests fail on `workalendar` holiday-data drift (Part 5.3 "known pre-existing
failures"), so the suite never reports fully green.

**Acceptance criteria:**
- LLM tracing rotates by size (default 50 MB, configurable via a new
  `HERMES_TRACE_MAX_MB` setting) keeping N rotated files; rotation is atomic and
  thread-safe (tracing is called from worker threads).
- No trace content changes; existing `test_tracing.py` stays green.
- The three `test_zurich_*` tests pass deterministically — either pin/patch the
  `workalendar` version and correct the expected holiday dates, or replace the live
  `workalendar` lookup in tests with a fixed fixture calendar. Document the choice.
- `pytest -m "not e2e and not integration"` reports **0 failures** (down from the 3
  tracked scheduling failures).

**Files:**
- `src/hermes_assistant/llm/tracing.py` — size-based rotating writer.
- `src/hermes_assistant/config.py` — `trace_max_mb` setting (env `HERMES_TRACE_MAX_MB`).
- `src/hermes_assistant/scheduling/derive.py` or `tests/test_scheduling.py` — fix the
  Zürich holiday assertions (fixture calendar preferred for determinism).
- `tests/test_tracing.py` — add a rotation test (write past the cap → new file created,
  old retained, most recent line readable).

## Phase 7 execution checklist
- [x] F5 first (green CI baseline) · [x] F1 · [ ] F2 · [x] F3 · [ ] F4
- [ ] Each: `ruff check . && mypy src && pytest -q` green, confidentiality guard covers
      new responses, RLock on new store writes, no cloud calls, co-author commit line.
- [ ] Update Part 2 (new screen/endpoint), Part 3.3 (F2 fields), Part 6 (F5 rotation)
      in this file as each ships — do not create new `.md` files.

## PLAN 1 — Risk external_ref idempotency (M2 for risks)

Add `external_ref` to the Risk model and implement M2-style re-import dedup, mirroring the TaskStore/pendenzen pattern.

**Critical corrections:** SQLite cannot `ALTER TABLE ADD COLUMN ... UNIQUE` → use a partial unique index `CREATE UNIQUE INDEX idx_risks_external_ref ON risks (external_ref) WHERE external_ref IS NOT NULL`. Do **not** overload `create()` with upsert logic — upsert belongs in the importer (Pass 1 lookup + Pass 2 `INSERT OR REPLACE`).

- **`risks/model.py`** (after `accepted_at`): `external_ref: str | None = None  # idempotency key for Copilot re-imports (M2)`.
- **`risks/registry.py`:** append `external_ref` to `_COLUMNS` (now 12); add `external_ref TEXT` to `_SCHEMA` + the partial unique index; in `_migrate` add a guarded `ALTER TABLE risks ADD COLUMN external_ref TEXT` (catch `OperationalError`) + `CREATE UNIQUE INDEX IF NOT EXISTS`; extract in `_row_to_risk` (`row["external_ref"] if "external_ref" in row.keys() else None`); add `external_ref` kwarg to `create()` (pass to `Risk()`, add to INSERT). New method:
  ```python
  def get_by_external_ref(self, external_ref: str) -> Risk | None:
      with self._lock:
          row = self._conn.execute(
              f"SELECT {_COLUMNS} FROM risks WHERE external_ref = ?",
              (external_ref,),
          ).fetchone()
          return self._row_to_risk(row) if row else None
  ```
  Do **not** add `external_ref` to `update()`'s `allowed` set — it is an identity key.
- **`webapp/import_json.py` (`_import_risks`):** append `external_ref` (and `accepted_at`) to `_RISK_COLS`; in Pass 1, before generating an id, compute `external_ref` and look it up (mirror pendenzen), fall back to legacy `id`; set `external_ref=` on the `Risk(...)` constructor and `created_at=existing.created_at if existing else now`; in Pass 2 add `risk.external_ref` to the values tuple.
- **New test `tests/test_json_import_unit.py::TestM2RiskExternalRefIdempotency`** using the real `import_payload()`: import 2 risks by `external_ref` → `created==2, updated==0`; edit one title, re-import → `created==0, updated==2`; assert DB has exactly 2 rows.

## PLAN 2 — (applied) real importer API in examples
The public entry point is `import_payload(payload_dict, risks_db=..., plans_db=..., tasks_db=...)` (`import_json.py`). There is no `import_risks(registry, payload)` function. All code examples in this document use `import_payload`.

## PLAN 3 — Lifecycle regression test matrix
`_LEGAL_TRANSITIONS` (registry.py) makes `closed` terminal. Existing tests already cover legal transitions, `accept()` setting `accepted_at`, and `closed→open`. Add one parametrized exhaustiveness test in `tests/test_invariants_risks.py`:
```python
@pytest.mark.parametrize("from_status,to_status", [
    (RiskStatus.closed, RiskStatus.open),
    (RiskStatus.closed, RiskStatus.mitigated),
    (RiskStatus.closed, RiskStatus.accepted),
])
def test_lifecycle_illegal_transitions_raise(tmp_path, from_status, to_status):
    registry = RiskRegistry(str(tmp_path / "risks.db"))
    risk = registry.create("test-risk")
    registry.update(risk.id, status=RiskStatus.mitigated)
    registry.update(risk.id, status=RiskStatus.accepted)
    registry.update(risk.id, status=RiskStatus.closed)
    with pytest.raises(ValueError, match="Illegal.*transition"):
        registry.update(risk.id, status=to_status)
```

## PLAN 4 — M10 suggestion context hydration (Phase 6)
`ChatContext` is currently built empty at `chat/service.py:242` (`ChatContext(project_id=project_id)`). Phase 6: inject `RiskRegistry`/`PlanEditor`/`TaskStore` into `ChatService.__init__`; hydrate context before `classify()`:
```python
context = ChatContext(
    project_id=project_id,
    risks=registry.list(project_id=project_id),
    plan_summary=editor.get_summary(project_id),
    open_task_count=task_store.count_open(project_id),
)
```
`_build_suggestions()` (service.py:330–341) already reads these fields — no formatter changes. Add `test_service_suggestions_filters_by_context`. Blocker: land PLAN 1 first (good practice for consistent data).

## Execution checklist
- [ ] PLAN 1 (3–4 hrs) · [ ] PLAN 2 docs fix (done) · [ ] PLAN 3 (1 hr)
- [ ] `pytest -m "not e2e and not integration"` green
- [ ] Commit with co-author line
- [ ] Dispatch Phase 1–4 test suites (unblocked)
- [ ] Phase 6: M10 hydration + H1/H2 blocker fixes

---

*End of master documentation. Extend the relevant Part above rather than creating new standalone docs.*
