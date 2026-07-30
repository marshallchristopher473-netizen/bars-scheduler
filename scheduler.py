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
