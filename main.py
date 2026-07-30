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
