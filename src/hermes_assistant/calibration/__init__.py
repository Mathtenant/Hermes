"""Judge calibration against a human-graded gold set (Phase 4, C2).

The rubric critic (Phase 3) is a *judge*; a judge is only trustworthy once it
has been calibrated against human grades. This package compares recorded critic
results to a small, human-reviewed **gold set** and reports judge-human
agreement (Cohen's kappa), per-criterion leniency/severity bias, and the
criteria where model and human disagree — the signal for fixing rubric wording.

All maths is deterministic pure Python (no LLM in the loop), so calibration is
fully reproducible and testable offline. Gold sets are *data* (YAML seeds under
``settings.calibration_path``), added with no code changes.
"""
