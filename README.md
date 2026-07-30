# BARS Scheduler

A 5‑minute‑block (BARS) scheduling engine inspired by NASA/TRISH principles.

- **Biological tasks** are reserved first (sleep, meals, medication).
- **Flexible tasks** are scored by priority, deadline proximity, difficulty and placed greedily.
- **Spaced repetition** for study tasks generates review sessions at +1, +3, +7 days.
- **Adaptive rescheduling** reclaims unused blocks when a task finishes early.

## Usage
```bash
python main.py
