"""
Domain models for the BARS scheduler.

Every scheduling unit is based on 5‑minute blocks (BARS).
All time values are expressed in **slots** (0‑287), where slot 0 = 00:00‑00:05,
slot 1 = 00:05‑00:10, …, slot 287 = 23:55‑00:00.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

SLOT_MINUTES = 5
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES  # 288


class TaskType(Enum):
    BIOLOGICAL = "bio"
    STUDY = "study"
    ROUTINE = "routine"


@dataclass
class TimeWindow:
    """
    A continuous interval of slots, [start_slot, end_slot).
    start_slot and end_slot are integers in 0..287.
    If end_slot < start_slot the window wraps around midnight (not used here; we split such windows).
    """
    start_slot: int
    end_slot: int

    def duration_slots(self) -> int:
        return self.end_slot - self.start_slot

    def contains_slot(self, slot: int) -> bool:
        return self.start_slot <= slot < self.end_slot


@dataclass
class TaskChunk:
    """
    A single 5‑minute BARS belonging to a task.
    """
    task_id: str
    chunk_index: int        # 0‑based index within the task
    assigned_slot: Optional[int] = None  # set after scheduling


@dataclass
class Task:
    """
    A schedulable item.
    - Biological tasks MUST have `preferred_windows` (e.g., sleep, meals, medication).
    - Study tasks benefit from spaced repetition.
    - Routine tasks are flexible.
    """
    id: str
    name: str
    task_type: TaskType
    duration_minutes: int         # total estimated minutes
    priority: int                 # 1 (low) .. 10 (high)
    difficulty: int               # 1 (easy) .. 10 (hard)
    deadline: Optional[datetime] = None   # used for scoring & spaced repetition
    preferred_windows: List[TimeWindow] = field(default_factory=list)

    # Derived after scheduling
    chunks: List[TaskChunk] = field(default_factory=list, repr=False)

    def duration_slots(self) -> int:
        """Number of 5‑minute slots needed (rounded up)."""
        return -(-self.duration_minutes // SLOT_MINUTES)  # ceiling division

    def generate_chunks(self) -> List[TaskChunk]:
        """Create unassigned TaskChunks for the whole task."""
        n = self.duration_slots()
        self.chunks = [TaskChunk(task_id=self.id, chunk_index=i) for i in range(n)]
        return self.chunks
