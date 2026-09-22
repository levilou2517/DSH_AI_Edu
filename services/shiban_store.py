#!/usr/bin/env python3
"""shiban_store —「师伴」持久数据层核心库（标准库 sqlite3，零第三方依赖）。

设计依据：构建/技术设计文档_数据与评估层_v1.md §1–§3。

职责：
  - 初始化 ~/.shiban/data/ 目录骨架与 meta.db / reference.db 表结构
  - 教师 / 班级 / 学生 / 课节 / 观测点 的新建、读取、追加
  - 跨班/跨届聚合借鉴（reference.db，只读，不外泄个体原始数据）
  - 幂等：重复初始化不破坏既有数据；delete 需显式 force

被两种上层访问方式的公共枢纽：
  1. CLI（bin/shiban-store）
  2. 宿主数据服务（cordis 动态 Tool 内部调用本库）
Agent 不直接碰文件，只经二者访问，达成「数据独立 + 跨会话继承」。
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
ROOT = os.environ.get("SHIBAN_ROOT", os.path.join(HOME, ".shiban"))
DATA_DIR = os.path.join(ROOT, "data")
META_DB = os.path.join(DATA_DIR, "meta.db")
REF_DB = os.path.join(DATA_DIR, "reference.db")

# ---------- schema ----------
META_SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
  teacher_id TEXT PRIMARY KEY,
  name       TEXT,
  profile    TEXT,          -- JSON: 偏好 + 专业成长时间线
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS classes (
  class_id     TEXT PRIMARY KEY,
  teacher_id   TEXT,
  level        TEXT,
  cohort       TEXT,
  subject      TEXT,
  class_family TEXT,
  created_at   TEXT
);
CREATE TABLE IF NOT EXISTS students (
  student_id  TEXT PRIMARY KEY,
  class_id    TEXT,
  name        TEXT,
  profile     TEXT,          -- JSON: 个体画像（时间纵深）
  external_ref TEXT,
  created_at  TEXT
);
CREATE TABLE IF NOT EXISTS lessons (
  lesson_id       TEXT PRIMARY KEY,
  class_id        TEXT,
  date            TEXT,
  topic           TEXT,
  knowledge_point TEXT,
  scaffold_type   TEXT,
  cognitive_level TEXT,
  pass_rate       REAL,
  lesson_meta     TEXT       -- JSON: current_*.json 产物、对话引用
);
CREATE TABLE IF NOT EXISTS observations (
  obs_id        TEXT PRIMARY KEY,
  class_id      TEXT,
  student_id    TEXT,
  recorded_at   TEXT,
  dimension     TEXT,        -- JSON: {knowledge_point, scaffold_type, cognitive_level}
  evidence      TEXT,        -- JSON: {ai_data, teacher_said}
  alignment     TEXT,        -- agreed / conflict / partial
  integrated    TEXT,
  pending_todo  TEXT
);
"""

REF_SCHEMA = """
CREATE TABLE IF NOT EXISTS scaffold_effectiveness_agg (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_family TEXT,
  scaffold_type TEXT,
  knowledge_point TEXT,
  cognitive_level TEXT,
  n INTEGER,
  avg_pass_rate REAL,
  source_distinct_lessons INTEGER,
  UNIQUE(class_family, scaffold_type, knowledge_point, cognitive_level)
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path, schema):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    conn.commit()
    return conn


def _valid_name(component):
    """防路径穿越/非法目录名：只允许字母数字中文下划线连接符。"""
    if not re.fullmatch(r"[\w\u4e00-\u9fff-]+", component):
        raise ValueError(f"非法标识符: {component!r}")


# ---------- 初始化 ----------
def init(force=False):
    """建立骨架与表；force=True 时只清空聚合库（不动 meta 主体数据）。"""
    os.makedirs(os.path.join(DATA_DIR, "classes"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "observations"), exist_ok=True)
    meta = _connect(META_DB, META_SCHEMA)
    ref = _connect(REF_DB, REF_SCHEMA)
    if force:
        ref.execute("DELETE FROM scaffold_effectiveness_agg")
        ref.commit()
    meta.close(); ref.close()
    return DATA_DIR


# ---------- 教师 ----------
def upsert_teacher(teacher_id, name, profile):
    _valid_name(teacher_id)
    m = _connect(META_DB, META_SCHEMA)
    m.execute(
        "INSERT INTO teachers(teacher_id,name,profile,created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(teacher_id) DO UPDATE SET profile=excluded.profile",
        (teacher_id, name, json.dumps(profile, ensure_ascii=False), _now()),
    )
    m.commit(); m.close()
    return {"ok": True, "teacher_id": teacher_id}


def get_teacher(teacher_id):
    m = _connect(META_DB, META_SCHEMA)
    r = m.execute("SELECT * FROM teachers WHERE teacher_id=?", (teacher_id,)).fetchone()
    m.close()
    if not r:
        return None
    return dict(r)


# ---------- 班级 ----------
def create_class(class_id, teacher_id, level, cohort, class_family, subject="生物"):
    _valid_name(class_id)
    m = _connect(META_DB, META_SCHEMA)
    m.execute(
        "INSERT INTO classes(class_id,teacher_id,level,cohort,subject,class_family,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (class_id, teacher_id, level, cohort, subject, class_family, _now()),
    )
    m.commit(); m.close()
    return {"ok": True, "class_id": class_id}


def get_class(class_id):
    m = _connect(META_DB, META_SCHEMA)
    r = m.execute("SELECT * FROM classes WHERE class_id=?", (class_id,)).fetchone()
    m.close()
    return dict(r) if r else None


def list_classes(teacher_id=None):
    m = _connect(META_DB, META_SCHEMA)
    if teacher_id:
        rows = m.execute("SELECT * FROM classes WHERE teacher_id=? ORDER BY cohort,class_id",
                         (teacher_id,)).fetchall()
    else:
        rows = m.execute("SELECT * FROM classes ORDER BY cohort,class_id").fetchall()
    m.close()
    return [dict(r) for r in rows]


# ---------- 学生 ----------
def create_student(student_id, class_id, name, external_ref=None, profile=None):
    _valid_name(student_id)
    m = _connect(META_DB, META_SCHEMA)
    m.execute(
        "INSERT INTO students(student_id,class_id,name,profile,external_ref,created_at) VALUES(?,?,?,?,?,?)",
        (student_id, class_id, name,
         json.dumps(profile or {}, ensure_ascii=False), external_ref, _now()),
    )
    m.commit(); m.close()
    return {"ok": True, "student_id": student_id}


def list_students(class_id):
    m = _connect(META_DB, META_SCHEMA)
    rows = m.execute("SELECT * FROM students WHERE class_id=? ORDER BY student_id", (class_id,)).fetchall()
    m.close()
    return [dict(r) for r in rows]


# ---------- 课节（含聚合回写 reference）----------
def add_lesson(class_id, lesson_id, date, topic, knowledge_point,
               scaffold_type, cognitive_level, pass_rate, lesson_meta=None,
               aggregate=True):
    _valid_name(lesson_id)
    m = _connect(META_DB, META_SCHEMA)
    m.execute(
        "INSERT INTO lessons(lesson_id,class_id,date,topic,knowledge_point,scaffold_type,"
        "cognitive_level,pass_rate,lesson_meta) VALUES(?,?,?,?,?,?,?,?,?)",
        (lesson_id, class_id, date, topic, knowledge_point, scaffold_type,
         cognitive_level, pass_rate, json.dumps(lesson_meta or {}, ensure_ascii=False)),
    )
    m.commit()
    cls = m.execute("SELECT class_family FROM classes WHERE class_id=?", (class_id,)).fetchone()
    m.close()
    if aggregate and cls:
        _aggregate_lesson(cls["class_family"], scaffold_type, knowledge_point, cognitive_level, pass_rate)
    return {"ok": True, "lesson_id": lesson_id}


def _aggregate_lesson(class_family, scaffold_type, knowledge_point, cognitive_level, pass_rate):
    ref = _connect(REF_DB, REF_SCHEMA)
    key = (class_family, scaffold_type, knowledge_point, cognitive_level)
    row = ref.execute(
        "SELECT * FROM scaffold_effectiveness_agg "
        "WHERE class_family=? AND scaffold_type=? AND knowledge_point=? AND cognitive_level=?",
        key).fetchone()
    if row:
        n = row["n"] + 1
        # 滚动平均
        new_avg = (row["avg_pass_rate"] * row["n"] + pass_rate) / n
        ref.execute(
            "UPDATE scaffold_effectiveness_agg SET n=?, avg_pass_rate=?, "
            "source_distinct_lessons=? WHERE id=?",
            (n, round(new_avg, 3), row["source_distinct_lessons"] + 1, row["id"]),
        )
    else:
        ref.execute(
            "INSERT INTO scaffold_effectiveness_agg(class_family,scaffold_type,knowledge_point,"
            "cognitive_level,n,avg_pass_rate,source_distinct_lessons) VALUES(?,?,?,?,?,?,?)",
            (*key, 1, round(float(pass_rate), 3), 1),
        )
    ref.commit(); ref.close()


# ---------- 观测点（过程性评价）----------
def add_observation(class_id, student_id, obs_id, dimension, evidence,
                    alignment, integrated, pending_todo=None):
    _valid_name(obs_id)
    m = _connect(META_DB, META_SCHEMA)
    m.execute(
        "INSERT INTO observations(obs_id,class_id,student_id,recorded_at,dimension,evidence,"
        "alignment,integrated,pending_todo) VALUES(?,?,?,?,?,?,?,?,?)",
        (obs_id, class_id, student_id, _now(),
         json.dumps(dimension, ensure_ascii=False),
         json.dumps(evidence, ensure_ascii=False),
         alignment, integrated, pending_todo),
    )
    m.commit(); m.close()
    return {"ok": True, "obs_id": obs_id}


def list_observations(student_id=None, class_id=None):
    m = _connect(META_DB, META_SCHEMA)
    if student_id:
        rows = m.execute("SELECT * FROM observations WHERE student_id=? ORDER BY recorded_at", (student_id,)).fetchall()
    elif class_id:
        rows = m.execute("SELECT * FROM observations WHERE class_id=? ORDER BY recorded_at", (class_id,)).fetchall()
    else:
        rows = m.execute("SELECT * FROM observations ORDER BY recorded_at").fetchall()
    m.close()
    return [dict(r) for r in rows]


# ---------- 跨班聚合借鉴（只读,不露个体）----------
def query_reference(scaffold_type=None, knowledge_point=None, cognitive_level=None, cohort=None):
    ref = _connect(REF_DB, REF_SCHEMA)
    sql = ("SELECT class_family,scaffold_type,knowledge_point,cognitive_level,n,avg_pass_rate,"
           "source_distinct_lessons FROM scaffold_effectiveness_agg WHERE 1=1")
    args = []
    for col, val in [("scaffold_type", scaffold_type), ("knowledge_point", knowledge_point),
                     ("cognitive_level", cognitive_level)]:
        if val:
            args.append(val)
            sql += f" AND {col}=?"
    if cohort:
        # cohort 不能直接对聚合库过滤（聚合库已去班维度），此处由 class_family 前缀兜底
        args.append(f"%{cohort}%")
        sql += " AND class_family LIKE ?"
    rows = ref.execute(sql + " ORDER BY avg_pass_rate DESC", args).fetchall()
    ref.close()
    return [dict(r) for r in rows]


# ---------- 幂等删除（显式 force）----------
def drop_class(class_id, force=False):
    if not force:
        return {"ok": False, "error": "需 force"}
    _valid_name(class_id)
    m = _connect(META_DB, META_SCHEMA)
    m.execute("DELETE FROM students WHERE class_id=?", (class_id,))
    m.execute("DELETE FROM lessons WHERE class_id=?", (class_id,))
    m.execute("DELETE FROM observations WHERE class_id=?", (class_id,))
    m.execute("DELETE FROM classes WHERE class_id=?", (class_id,))
    m.commit(); m.close()
    return {"ok": True, "class_id": class_id}


# ---------- CLI ----------
def _cli():
    ap = argparse.ArgumentParser(prog="shiban-store", description="师伴持久数据层")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    fc = sub.add_parser("class"); fc.add_argument("--id", required=True)
    fc.add_argument("--teacher", required=True); fc.add_argument("--cohort", required=True)
    fc.add_argument("--family", required=True)
    qc = sub.add_parser("query"); qc.add_argument("--scaffold"); qc.add_argument("--kp")
    sub.add_parser("classes")

    a = ap.parse_args()
    if a.cmd == "init":
        print(json.dumps({"ok": True, "root": init(force=False)}, ensure_ascii=False))
    elif a.cmd == "class":
        print(json.dumps(create_class(a.id, a.teacher, "高二", a.cohort, a.family), ensure_ascii=False))
    elif a.cmd == "query":
        print(json.dumps(query_reference(scaffold_type=a.scaffold, knowledge_point=a.kp), ensure_ascii=False))
    elif a.cmd == "classes":
        print(json.dumps(list_classes(), ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(_cli())