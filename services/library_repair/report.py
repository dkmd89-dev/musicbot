# services/library_repair/report.py
# -*- coding: utf-8 -*-
"""Human-readable Darstellung eines RepairPlan (Prompt Abschnitt 12)."""

from __future__ import annotations

from collections import Counter

from .models import RepairLevel, RepairPlan

_LEVEL_ORDER = [
    RepairLevel.SAFE_AUTOMATIC,
    RepairLevel.METADATA_REPROCESSING,
    RepairLevel.EXTERNAL_METADATA,
    RepairLevel.COVER,
    RepairLevel.LOUDNESS,
    RepairLevel.DUPLICATE,
    RepairLevel.MANUAL_REVIEW,
    RepairLevel.NOT_REPAIRABLE,
]

_LEVEL_LABEL = {
    RepairLevel.SAFE_AUTOMATIC: "Safe (Level 1 — deterministisch, kein --allow-delete)",
    RepairLevel.METADATA_REPROCESSING: "Metadata Reprocessing (Level 2)",
    RepairLevel.EXTERNAL_METADATA: "External Metadata (Level 3 — MusicBrainz/Pipeline)",
    RepairLevel.COVER: "Cover",
    RepairLevel.LOUDNESS: "Loudness / ReplayGain",
    RepairLevel.DUPLICATE: "Duplicates (destruktiv — Freigabe + --allow-delete)",
    RepairLevel.MANUAL_REVIEW: "Manual Review",
    RepairLevel.NOT_REPAIRABLE: "Nur Beobachtung (nichts zu tun)",
}


def render_plan_text(plan: RepairPlan, *, max_per_level: int = 25) -> str:
    lines: list[str] = []
    add = lines.append
    add("=" * 70)
    add("REPAIR PLAN")
    add("=" * 70)
    add(f"Library:      {plan.library_root}")
    add(f"Health score: {plan.health_score}")
    add(f"Actionable:   {len(plan.actionable())}")
    add(f"Manual review:{len(plan.manual_review()):>4}")
    if plan.unmapped_issue_codes:
        add(f"Unmapped issue codes (kein Repair): {sorted(plan.unmapped_issue_codes)}")
    add("")

    by_level = plan.by_level()
    for level in _LEVEL_ORDER:
        cands = by_level.get(level.value, [])
        if not cands:
            continue
        add("-" * 70)
        add(f"{_LEVEL_LABEL[level]}  ({len(cands)})")
        add("-" * 70)
        per_code = Counter(c.issue_code for c in cands)
        for code, n in sorted(per_code.items()):
            sample = next(c for c in cands if c.issue_code == code)
            flags = []
            if sample.requires_approval:
                flags.append("Freigabe")
            if sample.requires_external:
                flags.append("extern")
            if sample.is_destructive:
                flags.append("DESTRUKTIV")
            flag_s = f"  [{', '.join(flags)}]" if flags else ""
            add(f"  {n:>4}  {code}{flag_s}")
            add(f"        → {sample.action.value} via {sample.reuses_component}")
            add(f"        → {sample.expected_change}")
        # ein paar konkrete Pfade zur Orientierung
        shown = 0
        for c in cands:
            if shown >= max_per_level:
                add(f"        … {len(cands) - shown} weitere (siehe --json)")
                break
            loc = c.path or f"{c.artist or '-'} / {c.album or '-'}"
            add(f"          {c.issue_code:<28} {loc}")
            shown += 1
        add("")

    add("Nichts wird veraendert. Ausfuehrung: 'library_repair.py --apply' "
        "(Executor folgt in Phase 2 PR 2).")
    return "\n".join(lines)
