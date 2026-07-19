"""Consistency / MECE checker — spec §4.10.

Fully deterministic: no LLM involved.  Analyses a
:class:`~hermes_assistant.hermes.model.ProjectPlan` for three classes of
structural defect:

MECE violations (mutually exclusive + exhaustive)
    * Duplicate outcome IDs across phases.
    * Duplicate outcome names (case-insensitive) across phases.
    * Duplicate milestone IDs across phases.
    * Phases with zero outcomes (exhaustiveness gap).

Numeric contradictions
    * Effort values that are zero or negative.

Cross-section checks
    * ``depends_on`` references to IDs that do not exist in the plan.
    * Outcome ``phase`` annotations that disagree with the containing phase.

Raises :class:`ConsistencyError` (a ``ValueError`` subclass) when any
violations are found, carrying the full list for programmatic inspection.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from hermes_assistant.hermes.model import ProjectPlan


# --------------------------------------------------------------------------- #
# Output model
# --------------------------------------------------------------------------- #
class ConsistencyReport(BaseModel):
    """Result of a consistency check — all three violation lists.

    All three lists are empty iff :attr:`ok` is ``True``.
    """

    mece_violations: list[str]
    numeric_contradictions: list[str]
    cross_checks: list[str]

    @property
    def ok(self) -> bool:
        """``True`` iff no violations were found in any category."""
        return not (
            self.mece_violations
            or self.numeric_contradictions
            or self.cross_checks
        )

    @property
    def all_violations(self) -> list[str]:
        """Flat list of all violations across all three categories."""
        return (
            self.mece_violations
            + self.numeric_contradictions
            + self.cross_checks
        )


# --------------------------------------------------------------------------- #
# Error type
# --------------------------------------------------------------------------- #
class ConsistencyError(ValueError):
    """Raised when one or more consistency violations are found.

    Attributes
    ----------
    violations:
        Flat list of all violation strings (the same ordering as
        ``ConsistencyReport.all_violations``).
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations: list[str] = violations
        preview = "; ".join(violations[:3])
        suffix = "..." if len(violations) > 3 else ""
        super().__init__(
            f"{len(violations)} consistency violation(s): {preview}{suffix}"
        )


# --------------------------------------------------------------------------- #
# Check implementations
# --------------------------------------------------------------------------- #
def _collect_all_ids(plan: ProjectPlan) -> set[str]:
    """Return all outcome and milestone IDs defined across all phases."""
    ids: set[str] = set()
    for phase in plan.phases:
        for ms in phase.milestones:
            ids.add(ms.id)
        for oc in phase.outcomes:
            ids.add(oc.id)
    return ids


def _check_mece(plan: ProjectPlan) -> list[str]:
    """Return MECE violations: duplicates and exhaustiveness gaps."""
    violations: list[str] = []

    outcome_id_phases: dict[str, list[str]] = defaultdict(list)
    outcome_name_ids: dict[str, list[str]] = defaultdict(list)
    milestone_id_phases: dict[str, list[str]] = defaultdict(list)

    for phase in plan.phases:
        if not phase.outcomes:
            violations.append(
                f"Phase '{phase.id}' ({phase.name}) has no outcomes "
                "(exhaustiveness gap)"
            )
        for oc in phase.outcomes:
            outcome_id_phases[oc.id].append(phase.id)
            outcome_name_ids[oc.name.strip().lower()].append(oc.id)
        for ms in phase.milestones:
            milestone_id_phases[ms.id].append(phase.id)

    for oc_id, phases in outcome_id_phases.items():
        if len(phases) > 1:
            violations.append(
                f"Duplicate outcome id '{oc_id}' appears in phases: "
                f"{', '.join(phases)}"
            )

    for name, ids in outcome_name_ids.items():
        if len(ids) > 1:
            violations.append(
                f"Duplicate outcome name '{name}' (ids: {', '.join(ids)})"
            )

    for ms_id, phases in milestone_id_phases.items():
        if len(phases) > 1:
            violations.append(
                f"Duplicate milestone id '{ms_id}' appears in phases: "
                f"{', '.join(phases)}"
            )

    return violations


def _check_numeric(plan: ProjectPlan) -> list[str]:
    """Return numeric contradictions: non-positive effort values."""
    contradictions: list[str] = []

    for phase in plan.phases:
        for oc in phase.outcomes:
            if oc.effort_days is not None and oc.effort_days <= 0:
                contradictions.append(
                    f"Outcome '{oc.id}' has invalid effort_days="
                    f"{oc.effort_days} (must be > 0)"
                )
        for ms in phase.milestones:
            if ms.effort_days is not None and ms.effort_days <= 0:
                contradictions.append(
                    f"Milestone '{ms.id}' has invalid effort_days="
                    f"{ms.effort_days} (must be > 0)"
                )

    return contradictions


def _check_cross_sections(plan: ProjectPlan) -> list[str]:
    """Return cross-section findings: dangling refs and phase mismatches."""
    findings: list[str] = []
    all_ids = _collect_all_ids(plan)

    for phase in plan.phases:
        for oc in phase.outcomes:
            for dep in oc.depends_on:
                if dep not in all_ids:
                    findings.append(
                        f"Outcome '{oc.id}' depends_on unknown id '{dep}'"
                    )
            # Only flag if the phase annotation is explicitly set (non-empty)
            # and contradicts the containing phase.
            if oc.phase and oc.phase != phase.id:
                findings.append(
                    f"Outcome '{oc.id}' declares phase='{oc.phase}' "
                    f"but is contained in phase '{phase.id}'"
                )
        for ms in phase.milestones:
            for dep in ms.depends_on:
                if dep not in all_ids:
                    findings.append(
                        f"Milestone '{ms.id}' depends_on unknown id '{dep}'"
                    )

    return findings


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def check_consistency(plan: ProjectPlan) -> ConsistencyReport:
    """Run MECE + numeric + cross-section checks on ``plan``.

    All checks are deterministic — no LLM is involved.

    Returns
    -------
    ConsistencyReport
        The (clean) report when no violations are found.

    Raises
    ------
    ConsistencyError
        If any violations are found.  ``exc.violations`` is the flat list of
        all violation strings.
    """
    mece = _check_mece(plan)
    numeric = _check_numeric(plan)
    cross = _check_cross_sections(plan)

    report = ConsistencyReport(
        mece_violations=mece,
        numeric_contradictions=numeric,
        cross_checks=cross,
    )

    if not report.ok:
        raise ConsistencyError(report.all_violations)

    return report
