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
"""
DayGrid – the 288‑slot container for a single day's schedule.
"""

from typing import Dict, List, Optional
from models import TaskChunk, TimeWindow, SLOTS_PER_DAY

SlotEntry = Optional[TaskChunk]  # None means free


class DayGrid:
    def __init__(self):
        self.slots: List[SlotEntry] = [None] * SLOTS_PER_DAY

    def is_slot_free(self, slot: int) -> bool:
        return self.slots[slot] is None

    def are_slots_free(self, start: int, end: int) -> bool:
        """Check that every slot in [start, end) is free."""
        return all(self.is_slot_free(s) for s in range(start, end))

    def reserve_slots(self, start: int, end: int, chunk: TaskChunk) -> None:
        """Occupy a contiguous block with the same chunk (for contiguous tasks)."""
        for s in range(start, end):
            self.slots[s] = chunk

    def free_slots(self, start: int, end: int) -> None:
        """Mark slots as free (used after early completion)."""
        for s in range(start, end):
            self.slots[s] = None

    def first_fit_block(self, required_slots: int, windows: List[TimeWindow]) -> Optional[tuple[int, int]]:
        """
        Find the earliest contiguous free block of length `required_slots` inside the given windows.
        Returns (start, end) or None.
        """
        for w in windows:
            for start in range(w.start_slot, w.end_slot - required_slots + 1):
                if self.are_slots_free(start, start + required_slots):
                    return start, start + required_slots
        return None

    def find_free_slots_in_window(self, window: TimeWindow, max_count: int) -> List[int]:
        """Return list of free slots in a window (up to max_count)."""
        free = []
        for s in range(window.start_slot, window.end_slot):
            if self.is_slot_free(s):
                free.append(s)
                if len(free) == max_count:
                    break
        return free

    def get_schedule(self) -> Dict[int, Optional[str]]:
        """Return a dict slot_number -> task_id (or None)."""
        return {i: (chunk.task_id if chunk else None) for i, chunk in enumerate(self.slots)}

    def export_json(self) -> Dict:
        """Compact JSON representation of the 288‑slot grid."""
        return {"grid": [self.slots[i].task_id if self.slots[i] else None for i in range(SLOTS_PER_DAY)]}
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
"""
Ebbinghaus‑based spaced repetition engine.
Generates future review tasks for study items at +1, +3, +7 days.
"""

from datetime import datetime, timedelta
from copy import deepcopy
from models import Task, TaskType

INTERVALS_DAYS = [1, 3, 7]   # after the original task day
REVIEW_DURATION_FACTOR = 0.5  # reviews are half the original duration


class SpacedRepetitionEngine:
    @staticmethod
    def generate_review_tasks(original_task: Task, scheduled_date: datetime) -> list[Task]:
        """
        Create review tasks for future days.
        Each review keeps the same type, priority, difficulty, but a reduced duration.
        The deadline is set to the review date + 1 day.
        """
        if original_task.task_type != TaskType.STUDY:
            return []

        reviews = []
        for day_offset in INTERVALS_DAYS:
            review_date = scheduled_date + timedelta(days=day_offset)
            review = Task(
                id=f"{original_task.id}_review_{day_offset}d",
                name=f"[Review] {original_task.name}",
                task_type=TaskType.STUDY,
                duration_minutes=max(5, int(original_task.duration_minutes * REVIEW_DURATION_FACTOR)),
                priority=original_task.priority,
                difficulty=original_task.difficulty,
                deadline=review_date + timedelta(days=1),
            )
            reviews.append(review)
        return reviews
      """
Core scheduler.

Algorithm:
  1. Reserve biological tasks (they come with fixed preferred_windows).
  2. Convert every flexible task into 5‑minute BARS.
  3. Score tasks (priority × deadline × difficulty).
  4. Place task chunks greedily into available windows.
  5. Insert spaced repetition review tasks for study items.
"""

from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from models import Task, TaskType, TaskChunk, TimeWindow
from grid import DayGrid
from utils import score_task, split_wrapping_window
from spaced_repetition import SpacedRepetitionEngine


class Scheduler:
    def __init__(self, available_windows: List[TimeWindow], now: Optional[datetime] = None):
        """
        :param available_windows: general‑purpose time windows (e.g., 08:00‑12:00, 13:00‑18:00)
        """
        self.windows = available_windows
        self.now = now or datetime.now()
        self.grid = DayGrid()
        self.future_tasks: List[Task] = []

    def run(self, tasks: List[Task]) -> Tuple[DayGrid, List[Task]]:
        """
        Main entry point.
        Returns the populated DayGrid and a list of future review tasks.
        """
        bio_tasks = [t for t in tasks if t.task_type == TaskType.BIOLOGICAL]
        flexible_tasks = [t for t in tasks if t.task_type != TaskType.BIOLOGICAL]

        # 1. Reserve biological tasks
        self._reserve_biological(bio_tasks)

        # 2. Generate chunks for flexible tasks, score them
        for task in flexible_tasks:
            task.generate_chunks()
        scored = sorted(flexible_tasks, key=lambda t: score_task(t, self.now), reverse=True)

        # 3. Schedule flexible tasks
        self._schedule_flexible(scored)

        # 4. Spaced repetition for study tasks (today's and future)
        for task in tasks:
            if task.task_type == TaskType.STUDY:
                # Schedule reviews for the day when the original task is scheduled.
                # We assume the task is for today, so scheduled_date = self.now.date()
                review_tasks = SpacedRepetitionEngine.generate_review_tasks(task, self.now)
                self.future_tasks.extend(review_tasks)

        return self.grid, self.future_tasks

    def _reserve_biological(self, tasks: List[Task]) -> None:
        """Occupy the grid with biological tasks in their fixed windows."""
        for task in tasks:
            for win in task.preferred_windows:
                # win may wrap -> split
                for start, end in split_wrapping_window(win.start_slot, win.end_slot):
                    if not self.grid.are_slots_free(start, end):
                        raise ValueError(f"Biological task {task.id} window conflict at slots {start}-{end}")
                    # Create a single chunk that spans the whole window (we don't split bio tasks)
                    chunk = TaskChunk(task_id=task.id, chunk_index=0)
                    self.grid.reserve_slots(start, end, chunk)

    def _schedule_flexible(self, tasks: List[Task]) -> None:
        """Greedy placement of flexible tasks into self.windows."""
        for task in tasks:
            remaining = task.duration_slots()
            chunks = task.chunks[:]  # list of chunks to assign
            idx = 0
            while remaining > 0 and idx < len(chunks):
                # try to place as many chunks as possible contiguously
                block_len = min(remaining, 6)  # try moderate blocks to avoid excessive fragmentation
                placed = False
                for window in self.windows:
                    block = self.grid.first_fit_block(block_len, [window])
                    if block:
                        start, end = block
                        # assign that many chunks
                        for i in range(block_len):
                            if idx + i >= len(chunks):
                                break
                            chunk = chunks[idx + i]
                            chunk.assigned_slot = start + i
                            self.grid.reserve_slots(start + i, start + i + 1, chunk)
                        idx += block_len
                        remaining -= block_len
                        placed = True
                        break
                if not placed:
                    # fallback: place one chunk at a time wherever free
                    for window in self.windows:
                        free_slots = self.grid.find_free_slots_in_window(window, 1)
                        if free_slots:
                            slot = free_slots[0]
                            chunk = chunks[idx]
                            chunk.assigned_slot = slot
                            self.grid.reserve_slots(slot, slot + 1, chunk)
                            idx += 1
                            remaining -= 1
                            placed = True
                            break
                if not placed:
                    # Could not place remaining chunks – raise or log
                    raise RuntimeError(f"Cannot schedule task {task.id}: insufficient free space.")
                  """
Adaptive rescheduler – reacts to early task completions.

When a task finishes earlier than planned, unused BARS are freed and
redistributed to the remaining (not yet completed) tasks.
"""

from typing import Dict, List, Optional
from models import Task, TaskChunk, TimeWindow
from grid import DayGrid
from utils import score_task
from datetime import datetime
import copy


class AdaptiveRescheduler:
    def __init__(self, grid: DayGrid, tasks: List[Task], now: datetime):
        self.grid = grid
        self.tasks = {t.id: t for t in tasks}
        self.now = now

    def handle_early_completion(self, task_id: str, actual_duration_minutes: int) -> DayGrid:
        """
        Remove the tail of the task's allocated BARS, reclaim the freed slots,
        and reschedule any tasks that had unplaced chunks (or were cut short).
        Returns the updated grid.
        """
        task = self.tasks.get(task_id)
        if not task:
            return self.grid

        planned_slots = task.duration_slots()
        actual_slots = -(-actual_duration_minutes // 5)  # ceiling
        if actual_slots >= planned_slots:
            # No early finish
            return self.grid

        # Find the chunks that were placed and remove the surplus ones
        placed_chunks = [chunk for chunk in task.chunks if chunk.assigned_slot is not None]
        placed_chunks.sort(key=lambda c: c.assigned_slot)
        # Keep only the first `actual_slots` chunks
        surplus_chunks = placed_chunks[actual_slots:]

        freed_windows = []
        for chunk in surplus_chunks:
            slot = chunk.assigned_slot
            self.grid.free_slots(slot, slot + 1)
            freed_windows.append(TimeWindow(start_slot=slot, end_slot=slot + 1))
            chunk.assigned_slot = None

        # Merge adjacent freed slots into windows for simplicity (can be left as single slots)
        merged = self._merge_windows(freed_windows)

        # Identify tasks that still have unassigned chunks (including the current task if we want to re‑expand)
        unplaced_tasks = []
        for t in self.tasks.values():
            if any(c.assigned_slot is None for c in t.chunks):
                unplaced_tasks.append(t)

        if not unplaced_tasks:
            return self.grid

        # Re‑score and reschedule the remaining chunks into merged freed windows
        scored = sorted(unplaced_tasks, key=lambda t: score_task(t, self.now), reverse=True)
        for t in scored:
            for chunk in t.chunks:
                if chunk.assigned_slot is not None:
                    continue
                # try to place in any merged window
                placed = False
                for mw in merged:
                    free_slots = self.grid.find_free_slots_in_window(mw, 1)
                    if free_slots:
                        slot = free_slots[0]
                        chunk.assigned_slot = slot
                        self.grid.reserve_slots(slot, slot + 1, chunk)
                        placed = True
                        # update window (narrow it)
                        mw.start_slot = slot + 1
                        if mw.start_slot >= mw.end_slot:
                            merged.remove(mw)
                        break
                if not placed:
                    # If still can't place, ignore or log – real system could escalate
                    pass

        return self.grid

    @staticmethod
    def _merge_windows(windows: List[TimeWindow]) -> List[TimeWindow]:
        """Combine adjacent or overlapping single‑slot windows."""
        if not windows:
            return []
        windows.sort(key=lambda w: w.start_slot)
        merged = [copy.copy(windows[0])]
        for w in windows[1:]:
            last = merged[-1]
            if w.start_slot <= last.end_slot:  # adjacent or overlapping
                last.end_slot = max(last.end_slot, w.end_slot)
            else:
                merged.append(copy.copy(w))
        return merged
      {
  "tasks": [
    {
      "id": "sleep",
      "name": "Sleep",
      "task_type": "bio",
      "duration_minutes": 480,
      "priority": 10,
      "difficulty": 1,
      "preferred_windows": [[276, 288], [0, 84]]
    },
    {
      "id": "breakfast",
      "name": "Breakfast",
      "task_type": "bio",
      "duration_minutes": 30,
      "priority": 9,
      "difficulty": 1,
      "preferred_windows": [[84, 90]]
    },
    {
      "id": "lunch",
      "name": "Lunch",
      "task_type": "bio",
      "duration_minutes": 45,
      "priority": 9,
      "difficulty": 1,
      "preferred_windows": [[156, 165]]
    },
    {
      "id": "dinner",
      "name": "Dinner",
      "task_type": "bio",
      "duration_minutes": 45,
      "priority": 9,
      "difficulty": 1,
      "preferred_windows": [[240, 249]]
    },
    {
      "id": "study_math",
      "name": "Math Study",
      "task_type": "study",
      "duration_minutes": 120,
      "priority": 8,
      "difficulty": 7,
      "deadline": "2026-07-30T23:59:00"
    },
    {
      "id": "exercise",
      "name": "Exercise",
      "task_type": "routine",
      "duration_minutes": 60,
      "priority": 7,
      "difficulty": 5
    },
    {
      "id": "project_work",
      "name": "Project Work",
      "task_type": "routine",
      "duration_minutes": 150,
      "priority": 9,
      "difficulty": 8,
      "deadline": "2026-07-30T12:00:00"
    }
  ],
  "available_windows": [
    {"start_slot": 90, "end_slot": 156},
    {"start_slot": 165, "end_slot": 240}
  ]
      }
"""
Demo script: load JSON, schedule, export, and adaptive reschedule.
"""

import json
from datetime import datetime
from models import Task, TaskType, TimeWindow
from scheduler import Scheduler
from adaptive import AdaptiveRescheduler
from grid import DayGrid
from utils import slot_to_time_str


def load_tasks_and_windows(filename: str):
    with open(filename) as f:
        data = json.load(f)

    tasks = []
    for td in data["tasks"]:
        pref = []
        for w in td.get("preferred_windows", []):
            pref.append(TimeWindow(start_slot=w[0], end_slot=w[1]))
        deadline = None
        if "deadline" in td:
            deadline = datetime.fromisoformat(td["deadline"])
        tasks.append(Task(
            id=td["id"],
            name=td["name"],
            task_type=TaskType(td["task_type"]),
            duration_minutes=td["duration_minutes"],
            priority=td["priority"],
            difficulty=td["difficulty"],
            deadline=deadline,
            preferred_windows=pref,
        ))

    windows = [TimeWindow(start_slot=w["start_slot"], end_slot=w["end_slot"])
               for w in data["available_windows"]]
    return tasks, windows


def pretty_print_grid(grid: DayGrid):
    schedule = grid.get_schedule()
    print("Slot | Time    | Task ID")
    print("-----|---------|--------")
    for slot, task_id in schedule.items():
        if task_id:
            print(f"{slot:3d}  | {slot_to_time_str(slot)} | {task_id}")


if __name__ == "__main__":
    tasks, windows = load_tasks_and_windows("example_input.json")

    now = datetime(2026, 7, 29, 7, 0)  # example "now" morning of July 29
    scheduler = Scheduler(windows, now=now)
    grid, future_tasks = scheduler.run(tasks)

    print("=== Initial schedule ===")
    pretty_print_grid(grid)

    # Export to JSON
    output = grid.export_json()
    with open("example_output.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\nExported 288‑slot grid to example_output.json")

    # Show future review tasks
    if future_tasks:
        print("\nFuture review tasks generated:")
        for t in future_tasks:
            print(f"  {t.id}: {t.name} ({t.duration_minutes} min, deadline {t.deadline})")

    # ---- Adaptive rescheduling example ----
    print("\n=== Adaptive rescheduling (early finish) ===")
    # Simulate: "project_work" finished in 90 min instead of 150 min
    ar = AdaptiveRescheduler(grid, tasks, now)
    updated_grid = ar.handle_early_completion("project_work", 90)
    print("After early completion of project_work (90 min used):")
    pretty_print_grid(updated_grid)
{
  "grid": [
    "sleep", "sleep", "sleep", ..., "breakfast", ..., "study_math", ...
  ]
}
# BARS Scheduler

A 5‑minute‑block (BARS) scheduling engine inspired by NASA/TRISH principles.

- **Biological tasks** are reserved first (sleep, meals, medication).
- **Flexible tasks** are scored by priority, deadline proximity, difficulty and placed greedily.
- **Spaced repetition** for study tasks generates review sessions at +1, +3, +7 days.
- **Adaptive rescheduling** reclaims unused blocks when a task finishes early.

## Usage
```bash
python main.py
