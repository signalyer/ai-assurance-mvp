"""Trust scorer — computes workload trust score from policy decision history.

Aggregates policy decisions from data/policy_decisions.jsonl into a numerical
trust score (0-100) per workload. Higher = more trusted.

Score components:
- Base: 100
- Per DENY: -10 (capped at -60)
- Per REVIEW: -3 (capped at -30)
- Time decay: older decisions weighted less (half-life 7 days)
- Category multipliers: org-mandatory violations weighted 2x
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Constants
BASE_SCORE = 100.0
DENY_PENALTY = 10.0
REVIEW_PENALTY = 3.0
MAX_DENY_PENALTY = 60.0
MAX_REVIEW_PENALTY = 30.0
HALF_LIFE_DAYS = 7.0

# Category weights (multiplier applied to penalty)
CATEGORY_WEIGHTS = {
    "org-mandatory": 2.0,      # Org rules are critical
    "posture": 1.5,            # Compliance violations are serious
    "risk-tier": 1.2,          # Risk tier issues are concerning
    "team": 1.0,               # Team-specific rules are baseline
    "system-override": 0.5,    # Overrides are noted but not punished
}

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
POLICY_DECISIONS_FILE = _DATA_DIR / "policy_decisions.jsonl"


def trust_score(workload_id: str, lookback_days: int = 30) -> dict:
    """
    Compute the trust score for a workload based on policy decision history.

    Args:
        workload_id: Workload to score (e.g., 'ws-finadvisor-001')
        lookback_days: How far back to look in policy history (default 30 days)

    Returns:
        Dict with:
            workload_id: The workload ID
            score: Float 0-100 (higher = more trusted)
            band: 'HIGH' (>= 80), 'MEDIUM' (>= 50), 'LOW' (< 50)
            decisions_evaluated: Number of policy decisions counted
            denies: Number of DENY decisions
            reviews: Number of REVIEW decisions
            allows: Number of ALLOW decisions
            last_violation: ISO timestamp of most recent DENY/REVIEW
            top_violation_categories: List of categories with most violations
    """
    try:
        import storage

        if not POLICY_DECISIONS_FILE.exists():
            return _empty_score(workload_id)

        records = storage._read_jsonl(POLICY_DECISIONS_FILE)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=lookback_days)

        decisions = []
        for record in records:
            if record.get("workload_id") != workload_id:
                continue

            ts_str = record.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if ts < cutoff:
                continue

            decisions.append((ts, record))

        if not decisions:
            return _empty_score(workload_id)

        # Compute score
        deny_penalty_total = 0.0
        review_penalty_total = 0.0
        allow_count = 0
        deny_count = 0
        review_count = 0
        violation_categories = {}
        last_violation = None

        for ts, record in decisions:
            result = record.get("result", {})
            decision = result.get("decision", "ALLOW")
            category = result.get("category", "team")

            # Time decay (half-life)
            age_days = (now - ts).total_seconds() / 86400.0
            decay_factor = math.pow(0.5, age_days / HALF_LIFE_DAYS)

            # Category weight
            weight = CATEGORY_WEIGHTS.get(category, 1.0)

            if decision == "DENY":
                deny_count += 1
                penalty = DENY_PENALTY * weight * decay_factor
                deny_penalty_total += penalty
                violation_categories[category] = violation_categories.get(category, 0) + 1
                if last_violation is None or ts > last_violation:
                    last_violation = ts
            elif decision == "REVIEW":
                review_count += 1
                penalty = REVIEW_PENALTY * weight * decay_factor
                review_penalty_total += penalty
                violation_categories[category] = violation_categories.get(category, 0) + 1
                if last_violation is None or ts > last_violation:
                    last_violation = ts
            else:
                allow_count += 1

        # Cap penalties
        deny_penalty_total = min(deny_penalty_total, MAX_DENY_PENALTY)
        review_penalty_total = min(review_penalty_total, MAX_REVIEW_PENALTY)

        score = max(0.0, BASE_SCORE - deny_penalty_total - review_penalty_total)
        score = round(score, 2)

        # Determine band
        if score >= 80:
            band = "HIGH"
        elif score >= 50:
            band = "MEDIUM"
        else:
            band = "LOW"

        # Top violation categories (sorted descending)
        top_cats = sorted(violation_categories.items(), key=lambda x: -x[1])

        return {
            "workload_id": workload_id,
            "score": score,
            "band": band,
            "decisions_evaluated": len(decisions),
            "allows": allow_count,
            "denies": deny_count,
            "reviews": review_count,
            "last_violation": last_violation.isoformat() if last_violation else None,
            "top_violation_categories": [{"category": c, "count": n} for c, n in top_cats[:5]],
            "lookback_days": lookback_days,
        }

    except Exception as e:
        logger.error(f"trust_score failed: {e}", exc_info=True)
        return _empty_score(workload_id, error=str(e))


def _empty_score(workload_id: str, error: Optional[str] = None) -> dict:
    """Return default score when no data exists."""
    return {
        "workload_id": workload_id,
        "score": BASE_SCORE,
        "band": "HIGH",
        "decisions_evaluated": 0,
        "allows": 0,
        "denies": 0,
        "reviews": 0,
        "last_violation": None,
        "top_violation_categories": [],
        "lookback_days": 30,
        "error": error,
    }


def all_workload_scores(lookback_days: int = 30) -> list[dict]:
    """
    Compute trust scores for all known workloads.

    Returns:
        List of trust score dicts, sorted by score ascending (lowest trust first)
    """
    try:
        import storage

        if not POLICY_DECISIONS_FILE.exists():
            return []

        records = storage._read_jsonl(POLICY_DECISIONS_FILE)
        workload_ids = set()

        for record in records:
            wid = record.get("workload_id")
            if wid:
                workload_ids.add(wid)

        scores = [trust_score(wid, lookback_days=lookback_days) for wid in workload_ids]
        scores.sort(key=lambda s: s["score"])
        return scores

    except Exception as e:
        logger.error(f"all_workload_scores failed: {e}")
        return []


if __name__ == "__main__":
    # Smoke test — first generate some policy decisions
    print("Testing trust_scorer...\n")

    from domain.policy_engine import evaluate

    # Generate some decisions for a test workload
    test_wid = "ws-trustscore-test-001"

    # 5 ALLOWs (clean prompts)
    for i in range(5):
        evaluate(test_wid, "llm_call", {"prompt": f"What is {i}+{i}?"})

    # 2 DENYs (raw PII)
    evaluate(test_wid, "llm_call", {"prompt": "Client john@example.com"})
    evaluate(test_wid, "llm_call", {"prompt": "SSN 123-45-6789"})

    # Compute score
    score = trust_score(test_wid)
    print(f"Score: {score}")

    assert score["allows"] == 5, f"Expected 5 allows, got {score['allows']}"
    assert score["denies"] == 2, f"Expected 2 denies, got {score['denies']}"
    assert score["score"] < 100, "Score should be less than 100 due to denials"
    assert score["band"] in ("HIGH", "MEDIUM", "LOW")

    # All workloads
    all_scores = all_workload_scores()
    print(f"\nAll workload scores: {len(all_scores)} workloads")
    for s in all_scores[:3]:
        print(f"  {s['workload_id']}: {s['score']} ({s['band']})")

    print("\n[PASS] trust_scorer smoke test passed")
