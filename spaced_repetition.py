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
