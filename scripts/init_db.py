#!/usr/bin/env python3
"""初始化“师伴”工作区班级画像库。

- 创建 data/shiban/class_profile.db 及 class_profile 表（schema 与 V1.1 §4.2 一致）。
- 写入 V1.1 §6.1 的模拟数据（高二(3)班，类比×3、逻辑推导×1）。
- 打印核心查询（支架类型×通过率矩阵）。

用法：.venv/bin/python scripts/init_db.py
幂等：已存在库时若无 --force 仅打印矩阵，不重复播种。
"""
import argparse
import os
import sqlite3
import sys

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE, "data", "shiban", "class_profile.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS class_profile (
  id INTEGER PRIMARY KEY,
  class_id TEXT NOT NULL,
  session_date TEXT NOT NULL,
  knowledge_point TEXT,
  scaffold_type TEXT,
  cognitive_level TEXT,
  pass_rate REAL,
  session_duration_min INTEGER,
  teacher_note TEXT
);
"""

# 模拟数据（V1.1 §6.1）：
#  支架类型：类比×3、逻辑推导×1；平均通过率 类比≈81%、逻辑推导≈68%
#  认知层次分布：记忆层≈92%、应用层≈58%（以 pass_rate 体现）
SEED = [
    # (class_id, session_date, knowledge_point, scaffold_type, cognitive_level, pass_rate, duration_min, teacher_note)
    ("高二(3)班", "2026-09-02", "DNA复制", "类比",     "记忆", 0.92, 8,  "拉链类比引入双链结构，学生基本理解"),
    ("高二(3)班", "2026-09-09", "DNA复制", "类比",     "理解", 0.80, 12, "用拉链类比讲半保留方向，部分学生困惑"),
    ("高二(3)班", "2026-09-16", "DNA复制", "类比",     "应用", 0.71, 15, "给碱基序列让判断子链，应用较好"),
    ("高二(3)班", "2026-09-23", "转录",   "逻辑推导", "理解", 0.68, 14, "模板链与配对推导，学生反应偏慢"),
]


def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def matrix(conn: sqlite3.Connection) -> list:
    q = """
    SELECT class_id, scaffold_type,
           COUNT(*) AS n,
           ROUND(AVG(pass_rate), 3) AS avg_pass_rate
    FROM class_profile
    GROUP BY class_id, scaffold_type
    ORDER BY scaffold_type
    """
    return [dict(r) for r in conn.execute(q).fetchall()]


def print_matrix(rows: list) -> None:
    print("=== 支架类型 × 通过率 矩阵 ===")
    print(f"{'班级':<10}{'支架类型':<10}{'次数':<6}{'平均通过率':<12}")
    for r in rows:
        print(f"{r['class_id']:<10}{r['scaffold_type']:<10}{r['n']:<6}{r['avg_pass_rate']:<12}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已存在时清空并重新播种")
    args = ap.parse_args()

    conn = connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(SCHEMA)
    conn.commit()

    existing = conn.execute("SELECT COUNT(*) FROM class_profile").fetchone()[0]
    if existing == 0 or args.force:
        if args.force:
            conn.execute("DELETE FROM class_profile")
        conn.executemany(
            "INSERT INTO class_profile"
            "(class_id, session_date, knowledge_point, scaffold_type, cognitive_level,"
            " pass_rate, session_duration_min, teacher_note)"
            " VALUES (?,?,?,?,?,?,?,?)",
            SEED,
        )
        conn.commit()
        print(f"已播种 {len(SEED)} 条模拟记录 -> {DB_PATH}")
    else:
        print(f"库已有 {existing} 条记录，跳过播种（--force 可重播）。")

    print_matrix(matrix(conn))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())