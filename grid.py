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
