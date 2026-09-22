#!/usr/bin/env python3
"""class-eval 学情入库脚本（标准库 sqlite3，无第三方依赖）。
首次建库：DNA的复制（高二）· 方案B · 2026-07-08。
教师未提供个体作答数据：students / quiz_results / q7_scoring 建结构留空，
班级级统计与支架归因写入 class_lessons / scaffold_effectiveness / student_layers。
"""
import json
import os
import sqlite3
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "class_profile.db")
EVAL_PATH = os.path.join(BASE, "last_eval.json")

with open(EVAL_PATH, "r", encoding="utf-8") as f:
    ev = json.load(f)

meta = ev["meta"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    student_id   TEXT PRIMARY KEY,
    name         TEXT,
    total_score  REAL,
    pass_flag    INTEGER,          -- 1=及格 0=不及格
    note         TEXT
);
CREATE TABLE IF NOT EXISTS quiz_results (
    student_id   TEXT,
    question_id  TEXT,             -- Q1..Q6, Q7_new
    score        REAL,
    max_score    REAL,
    PRIMARY KEY (student_id, question_id)
);
CREATE TABLE IF NOT EXISTS q7_scoring (
    student_id   TEXT,
    point1_half_retained   REAL,   -- ① 指出"半保留"（4分）
    point2_unwind_template REAL,   -- ② "解旋"+"每条母链各作模板"（3分）
    point3_complementarity REAL,   -- ③ "碱基互补配对"（2分）
    point4_correct_original REAL,  -- ④ 纠正"原件不变"（2分）
    q7_total       REAL,
    PRIMARY KEY (student_id)
);
CREATE TABLE IF NOT EXISTS scaffold_effectiveness (
    scaffold_id      TEXT PRIMARY KEY,
    scaffold_name    TEXT,
    status           TEXT,         -- 生效 / 部分生效 / 未完全生效 / 未充分验证
    evidence         TEXT,         -- 支撑证据（得分率/典型作答）
    attribution      TEXT          -- 归因说明
);
CREATE TABLE IF NOT EXISTS student_layers (
    layer_id     TEXT PRIMARY KEY,
    layer_name   TEXT,
    estimate_n   TEXT,             -- 人数估算（区间，基于分布反推）
    profile      TEXT,             -- 作答特征
    cognitive_state TEXT,
    next_step    TEXT              -- 补强策略
);
CREATE TABLE IF NOT EXISTS class_lessons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT,
    course       TEXT,
    scheme_id    TEXT,
    scheme_name  TEXT,
    date         TEXT,
    class_size   INTEGER,
    avg_score    REAL,
    total_score  REAL,
    pass_rate    REAL,
    q_scores     TEXT,             -- JSON: 各题得分率
    q7_points    TEXT,             -- JSON: Q7 四得分点
    key_findings TEXT              -- 关键发现
);
"""

con = sqlite3.connect(DB_PATH)
cur = con.cursor()
cur.executescript(SCHEMA)

# 清空本次课题旧数据（幂等：重跑不重复）
cur.execute("DELETE FROM scaffold_effectiveness")
cur.execute("DELETE FROM student_layers")
cur.execute("DELETE FROM class_lessons WHERE topic=? AND date=? AND scheme_id=?",
            (meta["topic"], meta["date"], meta["scheme_id"]))

# ---- scaffold_effectiveness ----
sa = ev["scaffold_attribution"]
scaffold_rows = [
    ("S1", "类比引入：复印机复制文件", sa["S1_类比引入"]),
    ("S2", "底片互补类比（互补配对）", sa["S2_底片互补类比"]),
    ("S3", "类比边界讨论：'复印机哪里错了？'", sa["S3_类比边界讨论"]),
    ("S4", "分子层面回归（碱基序列互补配对+示意图）", sa["S4_分子精确化"]),
    ("S5", "边解旋边复制分步卡片排序", sa["S5_边解旋边复制排序"]),
    ("巩固", "对比图巩固环节（全保留/半保留/分散）", sa["巩固环节_对比图"]),
]
for sid, sname, s in scaffold_rows:
    cur.execute(
        "INSERT INTO scaffold_effectiveness (scaffold_id, scaffold_name, status, evidence, attribution) "
        "VALUES (?,?,?,?,?)",
        (sid, sname, s["status"],
         json.dumps(s.get("evidence", []), ensure_ascii=False),
         s.get("attribution", "")),
    )

# ---- student_layers ----
for layer in ev["student_layers"]["layers"]:
    # layer 字段形如 "L1 分子语言完整层"：L1 为 layer_id，其余为 layer_name
    lid, _, lname = layer["layer"].partition(" ")
    cur.execute(
        "INSERT INTO student_layers (layer_id, layer_name, estimate_n, profile, cognitive_state, next_step) "
        "VALUES (?,?,?,?,?,?)",
        (lid, lname, layer["estimate"],
         layer["profile"], layer["cognitive_state"], layer["next_step"]),
    )

# ---- class_lessons ----
q_scores = {
    "Q1": 0.88, "Q2": 0.81, "Q3": 0.90, "Q4": 0.62,
    "Q5": 0.55, "Q6": 0.71, "Q7_new": 0.105,
}
q7_points = {
    "point1_half_retained": 0.62,      # /4
    "point2_unwind_template": 0.24,    # /3
    "point3_complementarity": 0.19,    # /2
    "point4_correct_original": 0.11,   # /2
}
key_findings = (
    "1) 三层断崖：识别层80%+（Q1-Q3）→ 推演层55-71%（Q4/Q5/Q6）→ 综合转换层10.5%（Q7），"
    "断点在'类比→分子'转换的第二跳（正确结论→分子机制的主动生成）；"
    "2) S3走了提示卡降级路径且跳过'先写后说'，导致20秒沉默+偏差发现权从学生转移到教师，"
    "板书三处偏差与教案设计有出入（'全保留vs半保留'缺失，被'母链分配'=半保留结论复述取代）；"
    "3) Q7四得分点①62%>②24%>③19%>④11%严格递减：学生'结论能答、机制说不、解释不会、反驳不能'，"
    "Q3配对规则90% vs Q7③调用率19%证明'知道规则'与'用规则解释'之间存在迁移墙；"
    "4) Q5 55%表明S4'反向平行'要点未落实（方向标注错误率推断>30%，触发scaffold_failure_signal）；"
    "5) 分层：L1分子语言完整层(5-8人)/L2半分子语言层(10-14人)/L3类比词汇残留层(10-13人)/L4基础未稳层(10-14人)；"
    "6) 下节课优先动作：Q7三级任务阶梯（先写后说式递进）+ S3执行修复（90秒书写硬触发）+ "
    "S4方向彩色标注 + 巩固环节检验性使用落地。"
)
cur.execute(
    "INSERT INTO class_lessons (topic, course, scheme_id, scheme_name, date, class_size, "
    "avg_score, total_score, pass_rate, q_scores, q7_points, key_findings) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
    (meta["topic"], meta["course"], meta["scheme_id"], meta["scheme_name"],
     meta["date"], meta["class_size"], meta["avg_score"], meta["total_score"],
     meta["pass_rate"],
     json.dumps(q_scores, ensure_ascii=False),
     json.dumps(q7_points, ensure_ascii=False),
     key_findings),
)

con.commit()

# 验证
print("== tables ==")
for (t,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {n} rows")
print("== class_lessons ==")
for row in cur.execute("SELECT id, topic, scheme_id, date, class_size, avg_score, pass_rate FROM class_lessons"):
    print(" ", row)
print("== scaffold_effectiveness ==")
for row in cur.execute("SELECT scaffold_id, status FROM scaffold_effectiveness"):
    print(" ", row)
print("== student_layers ==")
for row in cur.execute("SELECT layer_id, layer_name, estimate_n FROM student_layers"):
    print(" ", row)
con.close()
print(f"DB written: {DB_PATH}")
