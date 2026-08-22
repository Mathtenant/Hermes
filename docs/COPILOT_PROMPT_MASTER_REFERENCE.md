# Copilot Prompt Master Reference — hermes.project_state/v1

**Purpose:** This document is the canonical reference for the Copilot JSON export prompt.
Use this file to verify that `/static/prompts/copilot_state_export.txt` has not drifted.
Any changes to the prompt MUST be made to BOTH this file and the static prompt file in parallel.

**Last verified:** 2026-08-22
**Prompt version:** hermes.project_state/v1
**Adapter:** src/hermes_assistant/webapp/import_adapters.py

---

## Enum Reference (Source of Truth)

| Field | Allowed values | Forbidden / common mistakes |
|---|---|---|
| `node_kind` | `phase \| deliverable \| task \| subtask \| action` | any value not in this list |
| `wbs.status` | `open \| in_progress \| done \| blocked` (NUR diese vier) | `todo`, `at_risk` |
| `project.phase` | `init \| konzept \| realisierung \| einfuehrung \| abschluss` | any value not in this list |
| `risks.likelihood` | `tief \| mittel \| hoch` | `gering` (that belongs to impact, not likelihood) |
| `risks.impact` | `gering \| mittel \| hoch` ("gering", NICHT "tief") | `tief` (only valid for likelihood, never impact) |
| `pendenzen.source` | `meeting \| review \| decision_log \| manual` | any value not in this list |
| `pendenzen.status` | `open \| in_progress \| done \| blocked` | `todo`, `at_risk` |

Date format: always `YYYY-MM-DD`.

`external_ref` prefixes: `proj/` Projekt, `ms/` Meilenstein, `wp/` WBS-Knoten, `pd/` Pendenz.

---

## Full Copilot Prompt (Copy-Paste Ready)

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

---

## Verification Checklist

- [ ] WBS status limited to: `open | in_progress | done | blocked`
- [ ] Risk impact limited to: `gering | mittel | hoch` (NOT "tief")
- [ ] Risk likelihood limited to: `tief | mittel | hoch`
- [ ] No forbidden tokens in enum-definition lines: "todo", "at_risk", `impact:"tief"`
- [ ] Schema version is exactly `"hermes.project_state/v1"`
- [ ] Worked example in prompt contains all required top-level fields (`schema`, `meta`, `project`, `wbs`, `risks`, `pendenzen`, `open_assumptions`, `decisions`)
- [ ] `external_ref` rules explained (deterministic slug generation: lowercase, umlaut expansion, non-alphanumerics → `-`, max 60 chars)
- [ ] "Häufige Fehler" (common mistakes) section lists forbidden values (fences, prose, invented dates, `todo`/`at_risk`, `tief` for impact)
- [ ] Output-rules section instructs single JSON object only, first char `{`, last char `}`
- [ ] `pendenzen.source` limited to: `meeting | review | decision_log | manual`

---

## How to Use This Document

1. **Verify prompt hasn't drifted:**
   ```bash
   diff docs/COPILOT_PROMPT_MASTER_REFERENCE.md src/hermes_assistant/webapp/static/prompts/copilot_state_export.txt
   # Should be empty or only differ in whitespace around the master doc's metadata
   ```
   In practice the master reference wraps the prompt in a fenced code block and
   adds surrounding sections, so diff this file's fenced block content against
   the static `.txt` file line-by-line rather than the whole document.

2. **When updating the prompt:**
   - Edit BOTH this file AND the static prompt file
   - Update the "Last verified" date
   - Run the verification checklist before committing
   - Commit with message: "Update Copilot prompt (audit: [your checks])"

3. **For debugging user issues:**
   - Compare user's Copilot output against the schema in this document
   - Check if their output matches the example
   - Identify which enum table the bad value should have come from

---

## Related Files

- Static prompt (deployed): `/src/hermes_assistant/webapp/static/prompts/copilot_state_export.txt`
- Adapter (implements schema): `/src/hermes_assistant/webapp/import_adapters.py`
- Tests (verify schema): `tests/test_copilot_adapter.py::TestPromptExampleFixture`
- User guide: `docs/COPY_COPILOT_PROMPT_GUIDE.md`

---

## Enum Mapping (Adapter → Internal)

| Copilot field | Copilot value | Adapter target field | Internal value |
|---|---|---|---|
| `risks.likelihood` | `tief` | `likelihood` (int 1-5) | `2` |
| `risks.likelihood` | `mittel` | `likelihood` (int 1-5) | `3` |
| `risks.likelihood` | `hoch` | `likelihood` (int 1-5) | `4` |
| `risks.likelihood` | unknown/missing | `likelihood` (int 1-5) | `3` (default) |
| `risks.impact` | `gering` | `severity` (string) | `low` |
| `risks.impact` | `mittel` | `severity` (string) | `medium` |
| `risks.impact` | `hoch` | `severity` (string) | `high` |
| `risks.impact` | unknown/missing | `severity` (string) | `medium` (default) |
| `pendenzen.source` | `meeting` | `source` | `meeting` |
| `pendenzen.source` | `review` | `source` | `review` |
| `pendenzen.source` | `decision_log` | `source` | `decision` (enum name mismatch, normalised) |
| `pendenzen.source` | `manual` | `source` | `manual` |
| `pendenzen.source` | unknown/missing | `source` | `manual` (default) |
| `project.external_ref` | `proj/<slug>` | `project_id` | prefix `proj/` stripped |
| `wbs[].node_kind` | `phase\|deliverable\|task\|subtask\|action` | plan item `phase` | stored verbatim |
| `wbs[].external_ref` | `wp/<slug>` | plan item `id` | stored verbatim |
| `wbs[].owner` | `<string>` | plan item `assignee` | stored verbatim |
| `pendenzen[].external_ref` | `pd/<slug>` | pendenz `id` | stored verbatim |
| `open_assumptions` | (any) | `_skipped_sections` | listed, never stored |
| `decisions` | (any) | `_skipped_sections` | listed, never stored |

Translation tables in code: `_LIKELIHOOD_TABLE`, `_IMPACT_TABLE`,
`_PENDENZ_SOURCE_TABLE` in `src/hermes_assistant/webapp/import_adapters.py`.

---

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-22 | Initial version (schema v1, German) | Created as part of Copy Copilot Prompt feature |
