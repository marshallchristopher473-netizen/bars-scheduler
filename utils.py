"""
Helpers: scoring, slot conversion, time utilities.
"""

from datetime import datetime, timedelta
from models import Task, SLOT_MINUTES, SLOTS_PER_DAY

# Default scoring weights (can be tuned)
PRIORITY_WEIGHT = 1.0
DEADLINE_WEIGHT = 2.0
DIFFICULTY_WEIGHT = 0.5
EPSILON = 1e-6


def minutes_to_slot(minutes: int) -> int:
    """Convert minutes since midnight to slot index."""
    return (minutes // SLOT_MINUTES) % SLOTS_PER_DAY


def slot_to_time_str(slot: int) -> str:
    """Return 'HH:MM' for a given slot."""
    total_minutes = slot * SLOT_MINUTES
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"


def hours_until(deadline: datetime, now: datetime) -> float:
    delta = deadline - now
    return max(delta.total_seconds() / 3600.0, 0.0)


def score_task(task: Task, now: datetime) -> float:
    """
    Heuristic score for scheduling a task.
    Higher score = schedule earlier.
    """
    p_score = task.priority * PRIORITY_WEIGHT
    d_score = 0.0
    if task.deadline:
        h = hours_until(task.deadline, now)
        d_score = DEADLINE_WEIGHT / (h + 1)
    diff_score = task.difficulty * DIFFICULTY_WEIGHT  # harder tasks -> earlier start
    return p_score + d_score + diff_score


def split_wrapping_window(start_slot: int, end_slot: int) -> list:
    """If a window wraps midnight, split into two non‑wrapping windows."""
    if start_slot < end_slot:
        return [(start_slot, end_slot)]
    # wraps: e.g., 276..84 → [276,288) and [0,84)
    return [(start_slot, SLOTS_PER_DAY), (0, end_slot)]
