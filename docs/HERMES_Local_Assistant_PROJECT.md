# HERMES Local Assistant — Project Specification & Build Guide

> **One document, three jobs:** (1) define *what* the system must do to help a junior consultant operate at senior level under HERMES 2022, (2) define *what is feasible* on the target hardware, and (3) give **Claude Code CLI** everything it needs to scaffold and build the system.
>
> **Status:** Specification v1.0 · Fully-local (Ollama, no cloud) · Single-user · Async-tolerant
> **Owner:** Project lead (Junior Consultant / Project Engineer, A+W Progress)
> **Target machine (prod):** HP ZBook Firefly 14 G9 — i7-1265U, 32 GB RAM, RTX A500 4 GB (dGPU)
> **Target machine (local POC):** MacBook Air M4 — 16 GB RAM, Apple Silicon GPU

---

## How to read this document

- **Part I–II** = the *why* and *what* (capabilities + hardware reality). Read once for context.
- **Part III** = the *how* (architecture decided by the hardware).
- **Part IV onward** = the **build contract for Claude Code**: repo layout, `CLAUDE.md`, interface contracts, phased backlog with acceptance criteria, and explicit guardrails.
- Anything in a `code block` is meant to be created or run verbatim. Anything tagged **[AC]** is an acceptance criterion Claude Code must satisfy before moving on.

---

# PART I — Capability Requirements (the *what*)

## 1. Context & hard constraints

The system is a personal, fully-local AI assistant that helps a junior project lead plan, organize, and quality-check work to a senior standard, inside the **HERMES 2022** Swiss federal project-management method. A+W Progress is an ICT / risk-and-security consultancy; the majority of its project references are confidential. That confidentiality posture makes **fully-local execution mandatory**.

**Hard constraints (non-negotiable):**

1. **Fully local.** All reasoning, planning, retrieval, and quality-checking run on local hardware via Ollama. No cloud reasoning, no anonymized cloud calls, no confidential content leaving the machine. (Cloud M365 Copilot may remain a *non-confidential* drafting tool only — it must never receive confidential content.)
2. **Fresh install**, single user, single laptop to start.
3. **Long inference time is acceptable** — design for latency tolerance, not speed.
4. **Adaptive, project-phase-driven — HERMES 2022 is an *optional reference lens*, not a mandatory backbone.** Projects here do not necessarily follow HERMES; they are IT-adaptation projects of varying sub-type. The assistant works through whatever phases a project *actually needs* ("do what's necessary") and pulls HERMES outcomes/checklists in via RAG only when a defensible reference is useful. See §3 and Part I-B (§4A–4C).

**Priority order of goals:** (1) close the **experience gap** [top], (2) plan & organize like a senior, (3) quality-check completed outputs.

## 2. The junior→senior experience gap (what we are actually encoding)

The gap is **judgment, ownership, and foresight**, not knowledge. A junior executes within a given frame; a senior *creates the frame*: defines the goal, breaks down the problem, names the unknowns, picks a "good enough" path, sets stop criteria and metrics, anticipates risk, and manages stakeholders. Much of this is **tacit knowledge** (expert pattern-matching à la Klein's Recognition-Primed Decision model) that "cannot be captured through words alone."

Therefore the tool cannot simply *be* senior. It must **elicit** senior judgment through structured questioning and **encode** it as reusable rubrics, checklists, and failure-mode libraries. Structure is the product.

## 3. Generic phases & HERMES 2022 as an optional lens

Projects are structured onto **flexible generic phases** the project actually needs — **Initiation/Analysis → Concept/Design → Realization/Implementation → Rollout/Deployment → Closure** — chosen adaptively rather than imposed. HERMES 2022 is pulled in **only as an optional reference** (via RAG) when the junior wants a defensible standard to cite. HERMES itself validates this adaptive stance: it offers classic/agile/hybrid solution creation, a *Szenarien + Sizing + Tailoring* mechanism to scale method weight to project characteristics, and treats "Adaption" (adaptation / standard-application customization) as a first-class project type.

When referenced, the useful HERMES elements are:
- **Phases (classic):** Initialisierung → Konzept → Realisierung → Einführung → Abschluss; **(agile/hybrid):** Initialisierung → Umsetzung → Abschluss.
- **Milestones = quality gates** (strengthened control function in 2022).
- **Outcomes (Ergebnisse):** documents or states; some marked as **minimum required ("X")**.
- **Roles:** sponsor (Auftraggeber), project management (Projektleiter), user rep (Anwendervertreter); optional quality/risk manager, ISDS (security) manager, test manager.
- **Checklists** are already first-class HERMES artifacts (review steps, release criteria, responsible parties, date).

The tool's job is **not** to enforce HERMES but to **instantiate the phases/deliverables a project needs**, optionally cross-referencing HERMES outcomes as a lens. The domain backbone is the **project-type taxonomy** (Part I-B), not HERMES.

## 4. Prioritized capability list

Tags: **[Must]/[Nice]** and **[Local-OK]** (fine on current local models) / **[Hard-Local]** (needs structural workarounds).

### Goal 1 — Plan & organize like a senior
1. **HERMES project scaffolder** [Must][Local-OK] — from a project description, propose scenario (sizing/tailoring), generate phase/milestone/outcome/role structure, list minimum-required documents per module. Output structured Markdown + JSON (grammar-constrained).
2. **Socratic intake interview** [Must][Local-OK] — before planning, interrogate for objectives, scope boundaries, stop criteria, stakeholders, constraints, success metrics, known unknowns. *Primary experience-gap closer.*
3. **Completeness & dependency checker** [Must][Local-OK] — cross-check plan against HERMES required outcomes and dependencies; flag missing deliverables, ungated phases, unassigned roles.
4. **Stakeholder / RACI + political-awareness map** [Must][Local-OK].
5. **Risk anticipation & pre-mortem at planning time** [Must][Local-OK] — risk register in A+W risk language (RAMS / EN 50126 vocabulary: reliability, availability, maintainability, safety; residual risk, risk-reducing measures).
6. **Scheduling & critical-path drafting** [Nice][Hard-Local] — ordering is local-OK; push numeric date/effort math to a deterministic tool, not the model's head.
7. **"What a junior wouldn't think to ask" prompt library** [Must][Local-OK].

### Goal 2 — Quality-check completed outputs
8. **Rubric-based critic/judge** [Must][Local-OK] — score against explicit HERMES/company rubrics; chain-of-thought-before-score; bias controls; self-consistency (3× + reconcile). Output dimension scores + located findings + pass/fail vs acceptance criteria.
9. **Critique → revise loop** [Must][Local-OK].
10. **Consistency & MECE checker** [Must][Local-OK] — contradictions, overlaps/gaps, terminology drift, number mismatches.
11. **Red-team / "client auditor" review** [Must][Local-OK].
12. **"So-what" / insight-vs-noise critique** [Must][Local-OK].
13. **Grounded fact/claim checking against sources** [Must][Hard-Local] — RAG-grounded; keep human sign-off, never auto-approve.
14. **Multi-model panel for high-stakes reviews** [Nice][Hard-Local] — diverse-family panel; only where stakes justify the compute.

### Goal 3 — Close the experience gap (top priority)
15. **Auto-checklist generator** [Must][Local-OK] — turn rubrics + HERMES checklists into per-deliverable acceptance checklists with explicit pass/fail criteria.
16. **Assumption surfacing & decision log** [Must][Local-OK] — force implicit assumptions explicit; maintain traceable decision/assumption log.
17. **Failure-mode library ("where juniors go wrong")** [Must][Local-OK] — curated, RAG-backed, growing.
18. **Tacit-knowledge capture loop** [Nice][Local-OK] — Critical-Decision-Method-style prompts to extract senior reasoning into reusable rubrics over time.
19. **"What good looks like" exemplars** [Must][Local-OK] — retrievable gold-standard outcome examples + annotated templates per HERMES document type.

### Cross-cutting platform capabilities
- Document ingestion (PDF/Office/Markdown) into a local vector store [Must][Local-OK].
- Grammar-constrained JSON / tool-calling with schema validation + auto-retry [Must][Local-OK].
- HITL quality gates mapped to HERMES milestones [Must][Local-OK].
- Traceability / audit log of agent decisions and retrievals [Must][Local-OK].
- Fully-local enforcement — no outbound calls [Must][Local-OK].

## 5. Encoded senior-review methodologies

| Method | What it does | Encoded as |
|---|---|---|
| **Pre-mortem** (Klein) | Imagine it already failed; work backward to causes (improves reason-finding ~30%) | Automated pass: "assume this failed catastrophically — list every reason," map to mitigations/risk register |
| **Red-team review** | Adversarial reviewer emulates client/auditor | Critic agent persona scoring vs acceptance criteria |
| **MECE** | No overlaps, no gaps in structures | Structural-consistency pass |
| **"So-what" / Pyramid / ghost-deck** | Every section drives a decision; lead with the takeaway | Insight-vs-noise + storyline-completeness check |
| **QC checklist w/ explicit acceptance criteria** | Precise pass/fail, responsible person, evidence, non-conformance + corrective action | Bridge between HERMES checklists and the automated rubric-judge |

---

# PART I-B — Adaptive Project-Type Taxonomy (the domain backbone)

> Replaces a rigid methodology with an **extensible registry**. Projects are all IT-adaptation type, with sub-types (KVM systems, ISDS-Analyse, network adaptation, …). Each sub-type is **data, not code** — new types are added without touching logic. This registry is the join between *planning* (what to produce) and *review* (how to judge it).

## 4A. The taxonomy data structure

Each project sub-type is a self-contained record the planner composes onto the generic phases (§3). The `review_rubrics` field links directly to the rubrics in Part I-C so planning and quality-review share one taxonomy.

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
  review_rubrics: [isds_analyse]                      # → Part I-C rubric
  reference_lens: [ncsc_p042, hermes_2022]            # optional, pulled via RAG
```

A `ProjectPlan` = chosen sub-type(s) × selected phases × instantiated deliverables/risks/stakeholders, all user-editable. Implemented as `src/hermes_assistant/hermes/project_types.py` (a loader over `project_types/*.yaml` seed files) — this **supersedes** the earlier `scenarios.py`/`minimum_docs.py` idea (those assumed rigid HERMES scenarios).

## 4B. Seed sub-type checklists (what a *good* one contains)

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

## 4C. Adaptive planning behavior

Both intake and planning are **model-generated and adaptive** ("what's necessary for *this* project"), not template-filling. The planner: picks the sub-type(s), proposes only the phases the project needs, instantiates that sub-type's deliverables/risks/stakeholders, lets the junior add/remove, and runs the completeness/dependency check against the sub-type checklist (not against a forced HERMES structure). A few sizing questions (criticality, personal-data involvement, regulatory exposure) drive the "what's necessary" decision.

---

# PART I-C — Quality-Review / Rubric System (designed from scratch)

> The current Copilot-agent review yields poor, non-qualitative results. This subsystem replaces it. **Design principle: a reviewer is a *compiler-executor*, not a chatbot** — encode senior standards as a versioned rubric of atomic, located, evidence-anchored checks; execute each with reasoning-before-verdict; aggregate across samples into a defensible pass/fail. This is the highest-value subsystem in the project.

## 4D. Why structured rubrics beat free-form critique (esp. for weak local models)
A general "review this" prompt makes a weak model both *invent* the standard and *apply* it every call — compounding error, drifting standards, and rewarding surface fluency. Fixing the standard (locked checklist) + binary decisions + reasoning-before-score + multi-sampling each removes a distinct failure mode. Evidence: checklist decomposition raised cross-model agreement **+0.45** and human correlation **+0.10** while cutting variance (CheckEval); self-consistency on gpt-oss-20b enabled **40–90%** less human grading time and flags its own low-confidence errors (SURE study); CoT-before-score adds the largest single prompt-level gain (G-Eval). These techniques are the reason a 20–30B local model can out-review the Copilot agent.

## 4E. Runtime pattern (one review pass)
1. **Retrieve** the rubric YAML for the deliverable type + optional reference passages (RAG grounding).
2. **Decompose** into atomic checks; keep ≤6–7 fields per LLM call (small models lose accuracy on wide schemas).
3. **CoT-before-score**: require rationale + **verbatim evidence quote/location** *before* the verdict field (ordering matters).
4. **Self-consistency**: sample each check 3–7× (start 5), majority-vote, record agreement as `confidence`, route low-agreement findings to the human.
5. **Validate** every response against a Pydantic schema via Ollama `format` (flat schema, ≤3 nesting levels).
6. **Aggregate** atomic findings → per-dimension rollups → single pass/fail verdict.

## 4F. Evaluation dimensions
Completeness · Correctness/factual accuracy · Internal consistency · Traceability · Clarity/unambiguity · Actionability · Risk coverage · Stakeholder fit · Evidence/grounding · Design-freedom (for requirements). Each becomes a rubric *category* holding atomic binary checks. Express acceptance criteria as concrete pass/fail (e.g. "Is **each** residual risk explicitly accepted by a named role?"), never adjectives ("is the risk analysis good?"). Rubric wording is a first-class reliability lever — rewording one ambiguous item cut a mis-scoring rate from 45%→14% (SURE).

## 4G. Judge-bias mitigations (bake in)
- **Self-enhancement bias → use a *different model family to judge than to draft*.** Draft with Qwen3-30B-A3B (thinking), review with gpt-oss-20b, or vice-versa. This is the cleanest mitigation and you have both models.
- **Verbosity bias** → binary checks (length-neutral); never reward length.
- **Position bias** → when comparing/ranking, swap positions and accept only consistent verdicts.
- **Leniency/severity** → calibrate against a small human-graded gold set; anchor each level with examples.
- **Surface-fluency bias** → require an evidence quote per finding.

## 4H. Rubric schema (YAML, senior-authored, version-controlled)
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

## 4I. Finding output schema (Pydantic, enforced via Ollama `format`)
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

## 4J. Capturing senior tacit standards
The rubric *is* the capture mechanism: harvest a senior's recurring past review comments → convert each into a positive criterion or an **anti-pattern** entry; anchor each criterion with pass/fail examples; add a **reference exemplar** ("a score-5 ISDS analysis contains…") for reference-guided judging (Prometheus pattern lifted a 13B model to GPT-4-level agreement); version the rubric like code. Calibrate on a **gold set** of 10–20 human-reviewed deliverables per type, target judge–human κ ≥ 0.6, and fix rubric wording where model and human disagree.

---

# PART II — Hardware Feasibility (the *constraint*)

## 6. The decisive facts about the target machine

- **CPU:** i7-1265U — 15 W, 2 P-cores + 8 E-cores, 12 threads. Low-power U-series.
- **RAM:** 64 GB (the machine's real superpower — lets you *load* big models).
- **GPU:** Intel Iris Xe **integrated only**, no dedicated VRAM, no discrete NVIDIA/AMD GPU. The "32 GB display memory" is shared system RAM.
- **Bottleneck:** **memory bandwidth** (~50–77 GB/s real-world dual-channel), not cores. Token generation at batch 1 is bandwidth-bound — every token reads the active weights from RAM. ~5 threads already saturate the bus; more threads can *hurt*.

## 7. What this means for model choice

- **Dense models scale brutally badly.** Realistic CPU-only Q4_K_M generation estimates on this class of chip:
  - 3–4B dense: ~10–18 tok/s (usable)
  - 7–8B dense: ~3–6 tok/s (tolerable short answers)
  - 14B dense: ~2–3 tok/s (batch-only)
  - 24B dense: ~1.5–2.5 tok/s (batch-only)
  - **30–32B dense: ~1–2 tok/s (effectively unusable interactively)**
- **MoE with low active params is the unlock.** Generation speed tracks *active* (not total) parameters:
  - **Qwen3-30B-A3B** (30.5B total / ~3.3B active): **~6–12 tok/s** — the sweet spot. Q4 weights ≈ 17–18 GB.
  - **gpt-oss-20b** (20.9B total / ~3.6B active, native MXFP4, adjustable reasoning effort): **~5–9 tok/s**. Weights ≈ 12–13 GB.
- **Iris Xe acceleration is marginal-to-counterproductive** for generation — the iGPU shares the same RAM bus, and Gen12 Iris Xe lacks matrix cores. At most it offloads *prefill*. **Do not design around the iGPU.**
- **Thinking mode is a time bomb on dense models.** A 3K-token reasoning trace at ~1.5 tok/s (dense 32B) ≈ 30+ minutes. The same trace on the MoE at ~8 tok/s ≈ 6–7 minutes. **Thinking mode only on the fast MoE, with a capped budget.**

## 8. Quantization & memory policy

- **Default = Q4_K_M.** On bandwidth-bound CPU, every extra bit costs proportional speed; Q8 roughly halves throughput. 64 GB capacity does **not** justify higher quants for the big model — speed dominates.
- MoE tolerates slightly higher quant (only active params are read): **Q5_K_M / UD-Q5_K_XL of Qwen3-30B-A3B is acceptable** if generation stays ≳ 6 tok/s.
- **Quantize the KV cache** (`q8_0` K and V) — near-lossless, stretches context, reduces bandwidth pressure.
- **Threads = physical cores (~10), not 12.** Hyperthreading hurts here.

## 9. Embeddings (run on CPU, cheap)

- **bge-m3** (568M) — strongest local all-rounder; dense+sparse+multi-vector, 100+ languages, 8192-token inputs. **Recommended default** (German/French/English Swiss context).
- **qwen3-embedding:0.6b** — modern, 32K context, 100+ languages; good CPU choice.
- **nomic-embed-text** (137M) — lightweight fallback.

---

# PART III — Architecture (decided by the hardware)

## 10. Design principles (async-first)

1. **Tiered model routing.** Small fast model (Qwen3-4B) for intent routing, field extraction, simple checks (~15 tok/s). Escalate to the MoE only when reasoning is genuinely required.
2. **One heavy pass, not many.** Collapse to: `retrieve → draft (MoE instruct) → single critique (MoE thinking, capped budget)`. Avoid iterative self-refine loops on the slow model.
3. **Async / batch / queue everything heavy.** Large document reviews = jobs on a queue, runnable overnight. Never block a chat UI on a 10-minute critique.
4. **Aggressive prompt caching.** Reuse KV for stable system prompts / rubrics / document headers (`cache_prompt=true`).
5. **Keep contexts small.** Chunk + retrieve top-k; avoid 32K-token stuffing; larger ubatch (e.g. 2048) to speed the prefill you do incur.
6. **Single laptop = single-user async assistant.** Not a synchronous multi-user / many-agent real-time orchestrator. Deferred upgrade path if needed: a single 24 GB GPU box (RTX 3090/4090 runs Qwen3-30B-A3B at 60–120 tok/s) or a high-bandwidth unified-memory machine — kept on-prem.

## 11. Model roster (target machine)

| Role | Model | Mode | Notes |
|---|---|---|---|
| Router / extractor / fast turns | `qwen3:4b` | instruct | ~15 tok/s |
| Planner / drafter (workhorse) | `qwen3-30b-a3b-instruct-2507` (Q4_K_M) | non-thinking | strong tool-calling (use `--jinja`) |
| Critic / judge (final pass) | `qwen3-30b-a3b-thinking-2507` (Q4_K_M) **or** `gpt-oss-20b` | thinking / capped | bake-off on real tasks; cap thinking ~1–2K tokens |
| Embeddings | `bge-m3` | — | CPU, multilingual |

## 12. Agent topology (logical, not necessarily multi-process)

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

## 13. Compensating for weak local reasoning (structure > scale)

- **Grammar-constrained decoding** for all JSON/tool output → schema-valid output + Pydantic validation + auto-retry (drives JSON failure < 1%).
- **Rubric-driven LLM-as-judge** with concrete criteria, chain-of-thought-before-score, position randomization, length normalization.
- **Self-consistency** (run judge 3×, reconcile) before reaching for debate/panels.
- **Decomposition** (split big extractions into focused sub-calls).
- **RAG grounding** against HERMES/company docs — the main hallucination defense.
- **Debate/panels** only for highest-stakes reviews, with *different model families* — evidence on multi-agent debate is mixed; validate empirically before relying on it.

---

# PART IV — Build Contract for Claude Code CLI

> This part turns the spec into something **Claude Code can scaffold and implement**. It assumes Claude Code runs **on the ZBook** (or a dev machine with the same Python toolchain) with Ollama installed locally.

## 14. Tech stack (chosen for local-first + Claude-Code-friendliness)

- **Language:** Python 3.11+ (user's primary stack: Pandas/NumPy/FastAPI/SQLAlchemy).
- **LLM serving:** Ollama (local HTTP at `http://localhost:11434`).
- **Orchestration:** LangGraph (graph workflows, loops, state persistence, HITL interrupts). Plain-Python fallback acceptable if LangGraph proves heavy.
- **Structured output:** Pydantic v2 + `outlines` / Ollama JSON-schema `format` for grammar-constrained decoding.
- **Vector store:** ChromaDB (embedded, local, no server) or LanceDB. Embeddings via Ollama `bge-m3`.
- **Job queue (async heavy passes):** SQLite-backed queue (start simple) → Redis/RQ if needed.
- **CLI / TUI:** Typer + Rich.
- **API (optional):** FastAPI (local-only bind `127.0.0.1`).
- **Config:** `pydantic-settings` + `.env` (no secrets needed — all local).
- **Testing:** pytest. **Lint/format:** ruff. **Types:** mypy.

## 15. Repository layout (Claude Code should scaffold exactly this)

```
hermes-assistant/
├── CLAUDE.md                     # operating contract for Claude Code (see §16)
├── README.md
├── pyproject.toml                # ruff + mypy + pytest config, deps
├── .env.example
├── docs/
│   └── HERMES_Local_Assistant_PROJECT.md   # THIS document
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
│   ├── queue/
│   │   ├── jobs.py               # job model + SQLite queue
│   │   └── worker.py             # runs heavy critic/red-team jobs async/overnight
│   ├── scheduling/              # Part IV-B: dates, deadlines, ICS export
│   │   ├── model.py             # ScheduledItem, Schedule, Reminder (Pydantic)
│   │   ├── derive.py            # plan + anchors → dated schedule (deterministic)
│   │   ├── deadlines.py         # cross-project aggregation, collision detection
│   │   └── ics.py              # Schedule → RFC-5545 .ics (icalendar lib)
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

## 16. `CLAUDE.md` — the operating contract (Claude Code reads this first)

Claude Code should create `CLAUDE.md` at repo root with the following content (this is the persistent instruction file Claude Code auto-loads):

```markdown
# CLAUDE.md — Operating contract for the HERMES Local Assistant

## What this project is
A fully-local (Ollama, no cloud) AI assistant that helps a junior consultant operate
at senior level under the HERMES 2022 method. See docs/HERMES_Local_Assistant_PROJECT.md
for the full spec. That document is the source of truth; if code and spec disagree, ask.

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

## 17. Core interface contracts (implement these signatures)

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

## 18. CLI surface (Typer) Claude Code should implement

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

# Scheduling / calendar (see Part IV-B, §24–27)
hermes schedule <project>       # derive dated milestones+tasks from a plan → schedule.json
hermes deadlines [--all] [--in 14d]   # cross-project view: what's due, what collides
hermes ics <project> [--merged|--split] [--tasks-as events|vtodo]  # emit .ics file(s)
hermes ics --all                # emit a combined multi-project calendar for import
```

---

# PART IV-B — Scheduling & Calendar Export (ICS)

> Added to answer: *"can it create calendar, todos with reminders, juggle multiple project deadlines?"* — **Yes, via ICS file export.** The assistant is the *brain* that derives **what** the deadlines are; your calendar app (Outlook) is the *clock* that stores and reminds. Chosen because it needs **no Microsoft Graph access, no API permissions, no cloud account** — just local `.ics` files you import. This keeps the fully-local guarantee intact.

## 24. Design rationale & boundaries

- **Why ICS, not Graph/Outlook API:** a `.ics` file is a local artifact. The assistant writes it; you import it manually. No programmatic M365 access (which may be locked down on the A+W machine), no credentials, nothing leaves the box until *you* choose to import. The local-first guarantee is untouched.
- **Division of labor:** the assistant **derives and exports**; the calendar app **stores, displays, and notifies**. The assistant does *not* run a reminder daemon, does not poll a clock, and does not own a calendar. (A reminder that fires while the laptop is asleep is the calendar app's job, and Outlook already does it well.)
- **Content boundary (important):** ICS files carry only **structural schedule metadata** — item title, dates, reminder lead time, project tag, and a short non-confidential note. **No confidential deliverable content** goes into an `.ics` summary/description. Treat the ICS surface exactly like the M365 boundary already defined in §21: titles and dates may cross; substance may not.
- **Re-import hygiene:** every emitted component carries a **stable deterministic `UID`** (e.g. `hermes-{project_id}-{item_id}@local`) and a bumped `SEQUENCE` on change, so re-importing an updated schedule **updates** existing entries instead of creating duplicates.

## 25. What ICS (RFC 5545) supports — and the Outlook reality

| Need | ICS mechanism | Outlook reality (design around this) |
|---|---|---|
| Milestone / deadline as a calendar entry | `VEVENT` (all-day or timed) | ✅ Fully supported on import |
| "Remind me N days before" | `VALARM` inside the component (`TRIGGER:-P2D`) | ✅ Supported on `VEVENT` |
| A to-do with a due date | `VTODO` (`DUE`, `PRIORITY`, `STATUS`) | ⚠️ **Outlook import of `VTODO` is unreliable/unsupported** in most desktop/web versions |
| Multiple projects | many components, one or many files | ✅ Per-project files import as separate, color-codable calendars |

**Decision that follows from the Outlook reality:** by **default, emit tasks as `VEVENT`** (all-day deadline events with alarms) so reminders actually fire in Outlook. Offer `VTODO` only behind an explicit `--tasks-as vtodo` flag for users on a calendar client with real task support (e.g. Apple Calendar / Thunderbird-Tasks). This is why the CLI exposes `--tasks-as events|vtodo` with `events` as the default.

## 26. Where the dates come from (deterministic, not the LLM's head)

Consistent with §4 capability 6 ("push numeric date/effort math to a deterministic tool, not the model's head"): the LLM proposes **structure and ordering** (which milestones, what depends on what, rough effort sizing); a **deterministic scheduler** computes the **actual dates**. The model never invents calendar arithmetic.

Inputs to `scheduling/derive.py`:
1. The `ProjectPlan` (phases, milestones, deliverables, dependencies) from the planner.
2. **Anchors** the user provides: a project go-live / hard deadline, and/or a start date, plus any fixed external dates (e.g. a steering-committee gate).
3. **Effort/duration hints** per item (LLM-suggested ranges, user-confirmable).
4. **Working-time rules**: skip weekends, optional Swiss/cantonal (Zürich) public holidays, configurable reminder lead times per item type (e.g. milestones −5 working days, tasks −2).

The scheduler does standard backward/forward pass dependency dating (no LLM): forward from start or backward from the hard deadline, respecting dependencies and working days, and flags any **negative-float** items (work that can't fit before the deadline) — exactly the kind of foresight a senior would surface.

## 27. Data model & interface contracts (implement these)

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
    project_label: str           # used as CATEGORIES tag for color-coding on import
    item_id: str
    title: str                   # NON-confidential summary only
    kind: ItemKind
    start: date | None           # for ranged work
    due: date                    # the date that matters
    all_day: bool = True
    depends_on: list[str] = []   # item_ids
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
           merged: bool = True,           # one file vs one per project
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
    """Aggregate every project's schedule into one view: what's due soon,
    what collides across projects, what's overdue. This is the multi-project juggling."""
```

**Dependencies:** add `icalendar` (emits RFC-5545-correct files; don't hand-roll the format) and `python-dateutil` / `workalendar` (Swiss + Zürich holidays for working-day math) to `pyproject.toml`. All pip-installed, all local, no services.

## 28. CLI behavior (already listed in §18)
- `hermes schedule <project>` → prompts for anchors (deadline/start), derives `Schedule`, writes `schedule.json`, **prints any negative-float warnings**.
- `hermes deadlines --all --in 14d` → the cross-project juggling view (upcoming, collisions, overdue).
- `hermes ics <project>` → writes `<project>.ics` (default: events + alarms, Outlook-safe). `--split` writes per-project files; `--merged --all` writes one combined calendar.
- Import flow for the user: open the `.ics` in Outlook → it lands as events with reminders; per-project files import as separate color-codable calendars.

## 29. Build phase (insert as **Phase 3.5**, after Quality-checking, before Review depth)
- Implement `scheduling/model.py`, deterministic `derive.py` (dependency dating + working days + negative-float detection), `ics.py` (via `icalendar`), `deadlines.py`, and the four CLI commands.
- **[AC]** From a `ProjectPlan` + a hard deadline, `hermes schedule` produces a `Schedule` whose dates respect dependencies and skip weekends/Zürich holidays.
- **[AC]** An item that cannot fit before the deadline appears in `negative_float` and is surfaced to the user.
- **[AC]** `hermes ics` emits a file that validates as RFC-5545 and **imports into Outlook as events with working reminders**; re-running after a change updates (not duplicates) entries (stable UID + bumped SEQUENCE).
- **[AC]** `--tasks-as vtodo` emits `VTODO`s; default `events` emits `VEVENT`s (documented Outlook-safe default).
- **[AC]** `hermes deadlines --all` lists upcoming items across ≥2 projects and flags same-day collisions.
- **[AC]** No `.ics` summary/description contains confidential deliverable content (a test asserts only title/date/tag/short-note fields are populated).

## 30. Limits (state plainly to the user)
- **The assistant does not notify you** — your calendar app does. If Outlook isn't running/synced, reminders won't fire; that's by design (no local daemon, no cloud).
- **It's export, not live sync.** Change a plan → re-export → re-import. Stable UIDs make re-import clean, but there's no two-way sync (that would require Graph/cloud, which is excluded).
- **`VTODO` is opt-in** because Outlook largely ignores it; tasks default to all-day events so reminders work.
- This covers calendar entries, reminders, deadlines, and multi-project collision-spotting — i.e. the substance of "juggling multiple project deadlines" — without building a full project-management app or a notification engine (those were options 2/3 in the design discussion; ICS is option 1).

---



## 19. `scripts/bootstrap.sh` (intent)

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

## 20. Ollama runtime policy (bake into client / Modelfile)

- `OLLAMA_NUM_THREAD=10` (physical cores), flash attention on, KV cache `q8_0`.
- `num_ctx` default **8192**; raise only when a task truly needs it.
- Cap critic thinking budget (~1–2K tokens) via prompt + `num_predict`.
- First action after bootstrap: **measure real tok/s** (`hermes models --bench`); the measured numbers govern all later tuning. If Qwen3-30B-A3B generation < 5 tok/s → switch CRITIC/PLANNER to `gpt-oss-20b` or `qwen3:8b` and shrink contexts.

---

# PART VI — Phased build backlog (acceptance-criteria driven)

> Claude Code should implement phases in order, keeping lint+types+tests green at each step.

### Phase 0 — Skeleton & guardrails
- Scaffold repo (§15), `CLAUDE.md` (§16), `pyproject.toml` (ruff/mypy/pytest), `.env.example`.
- Implement `OllamaClient` (§17) incl. `structured()` retry path.
- **[AC]** `pytest` green with a **mocked** Ollama client; `ruff` + `mypy` clean.
- **[AC]** `structured()` rejects then repairs one malformed JSON in a unit test.
- **[AC]** No module imports any cloud SDK; a test asserts only `localhost` is contacted.

### Phase 1 — RAG foundation
- `rag/ingest.py` (PDF/MD/Office → chunks → `bge-m3` → Chroma), `rag/retrieve.py` (top-k).
- `hermes ingest` + `hermes show` CLI.
- **[AC]** Ingest a sample HERMES PDF; retrieval returns relevant chunks for a known query.
- **[AC]** Ingestion is idempotent (re-ingest doesn't duplicate).

### Phase 2 — Experience-gap core (highest priority)
- `agents/intake.py` (adaptive Socratic interview), `hermes/model.py`, `hermes/project_types.py` + `project_types/*.yaml` seeds (ISDS-Analyse first; see §4A–4B), optional `hermes/reference.py` (HERMES lens).
- `agents/planner.py`: scaffolder → `ProjectPlan` (md+json) + completeness/dependency/role-coverage checker.
- `agents/scribe.py`: Markdown artifacts + decision/assumption log.
- Auto-checklist generator from rubric YAML.
- **[AC]** From a sample project description, `hermes plan` emits a schema-valid `ProjectPlan` with phases, milestones (quality gates), mandatory outcomes, and roles.
- **[AC]** `hermes check-plan` flags an injected missing mandatory outcome and an unassigned minimum role.
- **[AC]** On one real past project, intake+plan surfaces ≥ 80% of gaps/questions a senior reviewer independently lists (manual eval, recorded in `docs/eval/`).

### Phase 3 — Quality-checking
- `agents/critic.py` (rubric judge per **Part I-C §4E–4I**: compiler-executor, CoT-before-score, self-consistency, **different model family for judge vs draft**), `rubrics/*.yaml` (schema §4H), `ReviewResult` schema (§4I), anti-pattern library (§4J).
- Async `queue/` (SQLite) + `worker.py`; `hermes review` enqueues, `hermes jobs` inspects.
- **[AC]** `hermes review` on a deliberately flawed deliverable returns located findings + correct pass/fail vs acceptance criteria.
- **[AC]** A critique runs end-to-end as an async job and persists its result + traceability log.

### Phase 3.5 — Scheduling & ICS export
- Full spec in **Part IV-B (§24–30)**. Implement `scheduling/` (model, deterministic `derive`, `ics`, `deadlines`) + the `schedule` / `deadlines` / `ics` CLI commands. Add `icalendar`, `workalendar` deps.
- **[AC]** See §29 acceptance criteria (dependency-correct dates, negative-float warnings, Outlook-safe ICS import with reminders, clean re-import, cross-project collision view, no confidential content in ICS).

### Phase 4 — Review depth
- `agents/redteam.py` (pre-mortem + red-team), `agents/consistency.py` (MECE/contradiction/number checks).
- "So-what" / insight-vs-noise critique. HITL gates wired to HERMES milestones.
- Failure-mode library (RAG-backed) + "what good looks like" exemplars.
- **[AC]** Pre-mortem produces ≥ N distinct failure causes mapped to mitigations in the risk register.
- **[AC]** Consistency checker catches an injected numeric contradiction across two sections.

### Phase 5 — Selective heavy techniques (only if they earn it)
- Self-consistency on critical judgments; optional diverse-model panel for high-stakes reviews; deterministic scheduling tool integration.
- **[AC]** Panel/self-consistency must **measurably beat** single-judge on a labeled set before being kept; otherwise remove (mixed evidence on debate).

---

# PART VII — Guardrails, decision thresholds, caveats

## 21. Guardrails (enforced in code + `CLAUDE.md`)
- **No cloud reasoning, ever.** All inference local. M365 Copilot stays non-confidential-only and outside this system's data path.
- **Schema-valid ≠ correct.** Constrained decoding guarantees format, not truth. Human sign-off at every HERMES gate is mandatory — the assistant raises the floor and catches routine gaps; it does not certify correctness.
- **Traceability always on.** Every model call logged (model, mode, prompt hash, latency, tokens).

## 22. Decision thresholds (when to change course)
- Qwen3-30B-A3B generation **< 5 tok/s** or prefill unbearable → drop to **gpt-oss-20b** / **Qwen3-8B**, shrink contexts.
- Need **synchronous multi-agent** or **multi-user** → that's the trigger to provision the deferred local GPU box; the laptop can't.
- Thinking-mode critiques routinely **> 10 min** → cap thinking to ~1K tokens or switch critic to instruct-mode + structured rubric prompt.
- Hallucinated method guidance appears → tighten RAG grounding + citation-required rubrics **before** changing models.

## 23. Caveats
- **Model landscape moves fast.** Specific tags (Qwen3-30B-A3B, gpt-oss-20b, bge-m3) are current as of mid-2026; if a newer low-active-param MoE (≈3B active) is available at deploy time, it supersedes the primary — the *architecture* (low active params + Q4 + MoE + structure-over-scale) is what matters, not the version.
- **Performance estimates carry uncertainty.** CPU-only MoE tok/s here is extrapolated from higher-bandwidth machines scaled by memory bandwidth. `llama-bench` on the actual ZBook is ground truth — measure before committing.
- **Confirm RAM type/speed** (soldered LPDDR5 vs DDR5 SO-DIMM, configured MHz) in BIOS/HWiNFO — it directly sets the generation ceiling.
- **Tacit knowledge is only partially extractable.** The tool encodes the explicit residue of senior judgment (questions, rubrics, failure modes); it augments, it does not replace, senior mentoring.
- **Internal A+W standards and the specific HERMES tailoring** for the real project were not available here and must be ingested during Phase 1.

---

*End of specification v1.0 (Parts I–IV-H). Parts IV-I through IV-L appended Jul 2026.*

---

# PART IV-I — Hardware Baseline Update (Jul 2026)

## §11 — Hardware specification (revised)

| Component | Prod machine | Local POC |
|-----------|-------------|-----------|
| CPU | i7-1265U (10c/12t) | M4 (10c) |
| RAM | 32 GB LPDDR5 | 16 GB unified |
| GPU | RTX A500 4 GB GDDR6 | Apple Silicon GPU |
| Storage | NVMe SSD | NVMe SSD |

**Model placement rules (spec §11):**
- ROUTER (qwen3:4b) — fully on GPU (`num_gpu=1`); ~2.3 GB VRAM
- EMBED (bge-m3) — fully on GPU (`num_gpu=1`); ~1.1 GB VRAM
- PLANNER/CRITIC (qwen3-30b-a3b, Q4_K_M) — one resident at a time; KV-cache q8_0 mandatory; CPU+GPU offload as available
- Panel models (qwen3:8b, gemma3:4b, llama3.1:8b) — sequential loading; `keep_alive=0` between models to release VRAM
- Fallback under memory pressure: gpt-oss-20b (preferred) or qwen3:4b

**KV-cache setting:** `num_kv_cache_quant=q8_0` in Modelfile or Ollama options for all 30B models. Halves KV RAM vs fp16.

---

# PART IV-J — Phase 2.5: Task Store + WBS Tree

## §30 — Task model and WBS semantics

The task store is the prerequisite foundation for Phase 2.6 (Pendenzen) and Phase 3.6 (Dashboard).

**NodeKind taxonomy:**

| Kind | Purpose |
|------|---------|
| milestone | Quality gate (links to HERMES milestone) |
| deliverable | Output artefact (Ergebnis) |
| task | Work item / action |
| decision | Decision record (may spawn Pendenz if unresolved) |
| pendenz | Open item requiring follow-up (Phase 2.6) |
| assumption | Logged assumption (tracked for invalidation) |

**WBS numbering:** computed from parent path (root = "1", first child = "1.1", etc.). Stored on `wbs_number` field; recomputed on tree restructure.

**Progress rollup:** recursive closure/open counts up the parent chain. A parent is "done" when all children are `status=closed`.

**Task history:** every field update appended as a `TaskUpdate` record (timestamp, field, old_value, new_value, changed_by). Immutable audit trail.

---

# PART IV-K — Phase 2.6: Pendenzen + Meetings

## §31I–§31L — Pendenz model

A Pendenz is a `Task` with `node_kind="pendenz"` plus source tracking.

**PendenzSource taxonomy:**

| Source | Trigger |
|--------|---------|
| manual | User-created directly |
| review | Critic finding severity ≥ major, status != closed |
| decision | Unresolved decision record |
| meeting | Extracted from meeting notes |
| facilitator_import | Imported from external facilitator tool (§31R) |

**Confidentiality (§31J):** Meeting `raw_notes` are LOCAL ONLY and must never appear in any export, API response, or log. Only `title`, `attendees`, and `extracted_actions` may leave the store.

**Action extraction:** grammar-constrained LLM call (ROUTER model) on meeting raw_notes → list of Task objects in proposal state. Human approval required before promoting to open tasks.

---

# PART IV-L — Build Order (Jul 2026)

| Phase | Module | Status | Gate |
|-------|--------|--------|------|
| P1 | RAG ingest + retrieve | Done | 338 tests green |
| P2 | HERMES model + planner | Done | — |
| P3 | Rubrics + critic + queue + CLI | Done | — |
| P3 | Consistency + redteam agents | Done (committed Jul 2026) | — |
| P4 | Calibration gold sets | Done | — |
| P5 | Diverse panel + self-consistency | Done | — |
| P2.5 | Task store + WBS tree | Next | mypy + pytest |
| P2.6 | Pendenzen + meetings | Next | confidentiality test |
| P3.6 | Dashboard (read-only) | Planned | — |
| P5.x | Facilitator import (§31R) | Planned | — |

*End of specification. Build in phase order; keep it local; measure before you optimize.*
