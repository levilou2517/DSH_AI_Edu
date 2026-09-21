# data/ — “师伴” 运行时数据目录

本目录存放运行时生成的数据，**默认不纳入版本控制**（见根目录 `.gitignore`），

## 约定
- `class_profile.db`：工作区内 SQLite 班级画像库（schema 与 V1.1 §4.2 一致）。
  由 `scripts/init_db.py` 创建并播种模拟数据（V1.1 §6.1）。
  每次运行 `.venv/bin/python scripts/init_db.py` 幂等重建；`--force` 重新播种。
- `./shiban/*.json`（如 `current_lesson.json`、`current_quiz.json`、`last_eval.json`）：
  主 Agent 编排时子 Agent 之间的“共享内存”中间产物（V1.1 §九）。

## 版本控制
schema 与种子数据的**真源**是 `scripts/init_db.py`；`.db` 与 `.log` 等临时/二进制产物被
`.gitignore` 排除，可随时重新生成，避免入库产生二进制 diff。