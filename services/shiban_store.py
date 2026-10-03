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
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
ROOT = os.environ.get("SHIBAN_ROOT", os.path.join(HOME, ".shiban"))
DATA_DIR = os.path.join(ROOT, "data")
SHIBAN_DATA = os.path.join(DATA_DIR, "shiban")
RAW_DIR = os.path.join(SHIBAN_DATA, "raw")
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
CREATE TABLE IF NOT EXISTS assets (
  asset_id        TEXT PRIMARY KEY,   -- 过 _valid_name：防路径穿越
  kind            TEXT NOT NULL,      -- html | report | transcript | note | ...
  title           TEXT NOT NULL,
  subject         TEXT,               -- 学科，可空兼容跨学科
  knowledge_point TEXT,               -- 对齐 lessons.knowledge_point → 跨课检索
  source_lesson   TEXT,               -- 关联 lesson_id（可空）
  params          TEXT,               -- 生成参数 JSON（可空）
  tags            TEXT,               -- 逗号分隔
  file_path       TEXT NOT NULL,      -- 相对 ROOT 的产物路径
  content_hash    TEXT,               -- SHA-256 → 查重/复用（先查后建）
  reuse_count     INTEGER DEFAULT 0,
  parent_asset    TEXT,               -- v0.4.3 自引用：本素材作为更大页面的组件时，指向该页面 asset_id
  assembly        TEXT,               -- v0.4.3 JSON：本页面编排了哪些子组件及每处喂的数据/关键参数
  created_at      TEXT,
  updated_at      TEXT
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
    # v0.4.3 幂等迁移：老库 assets 表缺 parent_asset / assembly 列则补齐（零迁移、重复 init 安全）
    if os.path.abspath(db_path) == os.path.abspath(META_DB):
        _ensure_asset_columns(conn)
    return conn


def _ensure_asset_columns(conn):
    """为 v0.4.3 给老库 assets 表幂等补列；新库 DDL 已含，此处跳过。"""
    has = {r[1] for r in conn.execute("PRAGMA table_info(assets)").fetchall()}
    for col, ddl in (("parent_asset", "ALTER TABLE assets ADD COLUMN parent_asset TEXT"),
                     ("assembly",    "ALTER TABLE assets ADD COLUMN assembly TEXT")):
        if col not in has:
            conn.execute(ddl)
            conn.commit()
            has.add(col)


def _valid_name(component):
    """防路径穿越/非法目录名：只允许字母数字中文下划线连接符。"""
    if not re.fullmatch(r"[\w\u4e00-\u9fff-]+", component):
        raise ValueError(f"非法标识符: {component!r}")


def _valid_evidence_name(name):
    """证据文件名：允许点（扩展名），禁路径分隔与 '..'。"""
    if not re.fullmatch(r"[\w\u4e00-\u9fff.-]+", name) or ".." in name:
        raise ValueError(f"非法证据文件名: {name!r}")


# ---------- 初始化 ----------
def init(force=False):
    """建立骨架与表；force=True 时只清空聚合库（不动 meta 主体数据）。"""
    os.makedirs(os.path.join(DATA_DIR, "classes"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "observations"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "assets"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "assets", "vendor"), exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)
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
# ---------- 原始证据（raw/，D1 唯一落盘目录） ----------
def save_raw_evidence(name, text):
    """保存原始证据（转录/记录/笔记）。

    契约：raw/ 只追加、不改写——同名文件已存在则拒绝（更正请另存新版本名）。
    D4 写盘校验：写入后字节数必须与内容一致，否则删除半成品并报错。
    name 过 _valid_evidence_name（允许扩展名，禁路径穿越）。"""
    _valid_evidence_name(name)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("证据内容为空，拒绝落盘")
    path = os.path.join(RAW_DIR, name)
    os.makedirs(RAW_DIR, exist_ok=True)
    if os.path.exists(path):
        raise ValueError(f"证据已存在，只追加不改写；更正请另存新版本名: {name}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    expected = len(text.encode("utf-8"))
    actual = os.path.getsize(path) if os.path.exists(path) else -1
    if actual != expected:
        try:
            os.remove(path)
        except OSError:
            pass
        raise RuntimeError(f"写盘校验失败: {name} 期望 {expected}B 实际 {actual}B")
    return {"ok": True, "name": name, "path": path, "bytes": expected}


def list_raw():
    if not os.path.isdir(RAW_DIR):
        return []
    return sorted(
        ({"name": n, "bytes": os.path.getsize(os.path.join(RAW_DIR, n)),
          "mtime": datetime.fromtimestamp(os.path.getmtime(os.path.join(RAW_DIR, n)), timezone.utc).isoformat()}
         for n in os.listdir(RAW_DIR)
         if os.path.isfile(os.path.join(RAW_DIR, n))),
        key=lambda e: e["name"],
    )


def read_raw(name):
    _valid_evidence_name(name)
    path = os.path.join(RAW_DIR, name)
    if not os.path.isfile(path):
        raise ValueError(f"证据不存在: {name}")
    with open(path, encoding="utf-8") as f:
        return {"ok": True, "name": name, "content": f.read()}


# ---------- 素材资产 ----------
ASSET_KINDS = ("html", "report", "transcript", "note")


def add_asset(asset_id, kind, title, file_path, subject=None, knowledge_point=None,
              source_lesson=None, params=None, tags=None, parent_asset=None, assembly=None):
    """登记素材。file_path 为绝对路径：拷入 assets/<id>/ 并登记。

    先查后建：若 file 内容 SHA-256 与既有 asset 相同 → 不重复入库，
    返回 {ok, existed, asset_id}。
    v0.4.3：parent_asset（自引用上层宿主）/ assembly（本页编排子组件+喂数据）支持层级自由。"""
    _valid_name(asset_id)
    if kind not in ASSET_KINDS:
        raise ValueError(f"未知素材类型: {kind!r}（允许 {ASSET_KINDS}）")
    if not os.path.isfile(file_path):
        raise ValueError(f"源文件不存在: {file_path}")
    if parent_asset is not None:
        _valid_name(parent_asset)
    with open(file_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    m = _connect(META_DB, META_SCHEMA)
    try:
        dup = m.execute("SELECT asset_id FROM assets WHERE content_hash=?", (digest,)).fetchone()
        if dup:
            return {"ok": True, "existed": True, "asset_id": dup["asset_id"], "content_hash": digest}
        if m.execute("SELECT 1 FROM assets WHERE asset_id=?", (asset_id,)).fetchone():
            raise ValueError(f"素材 id 已存在: {asset_id}（复用请用 asset reuse，或换 id）")
        # 落盘到 assets/<asset_id>/main<ext>（固定主文件名，不随源文件名漂移）+ meta.json
        dest_dir = os.path.join(DATA_DIR, "assets", asset_id)
        os.makedirs(dest_dir, exist_ok=True)
        ext = os.path.splitext(file_path)[1] or ".html"
        dest = os.path.join(dest_dir, "main" + ext)
        shutil.copyfile(file_path, dest)
        if os.path.getsize(dest) == 0 and os.path.getsize(file_path) > 0:
            raise RuntimeError(f"写盘校验失败：{dest} 为 0 字节（源文件非空）")
        now = _now()
        # meta.json：素材自描述（含契约 interface），脱离 DB 也可读
        with open(os.path.join(dest_dir, "meta.json"), "w", encoding="utf-8") as mf:
            json.dump({"asset_id": asset_id, "kind": kind, "title": title, "subject": subject,
                       "knowledge_point": knowledge_point, "params": params, "tags": tags,
                       "parent_asset": parent_asset, "assembly": assembly,
                       "created_at": now, "external": True}, mf, ensure_ascii=False, indent=2)
        rel = os.path.relpath(dest, ROOT)
        assembly_json = json.dumps(assembly, ensure_ascii=False) if assembly is not None else None
        m.execute(
            "INSERT INTO assets(asset_id,kind,title,subject,knowledge_point,source_lesson,"
            "params,tags,file_path,content_hash,reuse_count,parent_asset,assembly,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, kind, title, subject, knowledge_point, source_lesson,
             json.dumps(params, ensure_ascii=False) if params is not None else None,
             tags, rel, digest, 0, parent_asset, assembly_json, now, now),
        )
        m.commit()
        return {"ok": True, "existed": False, "asset_id": asset_id, "content_hash": digest}
    finally:
        m.close()


def get_asset(asset_id):
    m = _connect(META_DB, META_SCHEMA)
    row = m.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    m.close()
    return dict(row) if row else None


def list_assets(kind=None, knowledge_point=None, subject=None):
    m = _connect(META_DB, META_SCHEMA)
    sql = "SELECT * FROM assets WHERE 1=1"
    args = []
    if kind:
        sql += " AND kind=?"; args.append(kind)
    if knowledge_point:
        sql += " AND knowledge_point=?"; args.append(knowledge_point)
    if subject:
        sql += " AND subject=?"; args.append(subject)
    sql += " ORDER BY created_at DESC"
    rows = [dict(r) for r in m.execute(sql, args).fetchall()]
    m.close()
    return rows


def reuse_asset(asset_id):
    """复用计数 +1，回显 file_path（绝对路径）。"""
    m = _connect(META_DB, META_SCHEMA)
    try:
        row = m.execute("SELECT asset_id,file_path FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if not row:
            raise ValueError(f"素材不存在: {asset_id}")
        m.execute("UPDATE assets SET reuse_count=reuse_count+1,updated_at=? WHERE asset_id=?",
                  (_now(), asset_id))
        m.commit()
        return {"ok": True, "asset_id": asset_id,
                "file_path": os.path.join(ROOT, row["file_path"])}
    finally:
        m.close()


# ---------- v0.4.3 素材编排：suggest（先查后建）+ compose（原子内联装配） ----------

def _interface_of(row):
    """取该原子的输入契约（interface schema 片段）——compose/suggest 单一来源。

    优先级：素材目录 meta.json（运行期 add_asset/compose 写入，权威且脱离 DB 可读）
    → DB params 兜底（scan 登记等无 meta.json 的行）。两处皆缺 → 视为无契约（不校验）。"""
    try:
        meta_p = os.path.join(os.path.dirname(os.path.join(ROOT, row["file_path"])), "meta.json")
        if os.path.isfile(meta_p):
            with open(meta_p, encoding="utf-8") as f:
                meta = json.load(f)
            iface = (meta.get("params") or {}).get("interface")
            if isinstance(iface, dict) and iface:
                return iface
    except (OSError, ValueError):
        pass
    try:
        p = json.loads(row["params"]) if row["params"] else {}
    except (TypeError, ValueError):
        p = {}
    return (p or {}).get("interface") or {}


def _validate_data(iface, data, where):
    """按 interface 校验喂数——仅 required/enum/type 三子集（零依赖，非完整 JSON Schema）。

    interface 约定为「字段名 -> {约束}」映射；无约束的字段（interface 中值为空对象）不校验。
    缺省值由原子内部兜底，compose 不代填。"""
    data = data or {}
    errs = []
    tmap = {"string": str, "number": (int, float), "integer": int,
            "boolean": bool, "array": list, "object": dict}
    for field, cons in (iface or {}).items():
        if not isinstance(cons, dict):
            cons = {}
        if cons.get("required") and field not in data:
            errs.append(f"{where}.{field} 缺少必填字段")
            continue
        if field not in data:
            continue
        v = data[field]
        t = cons.get("type")
        if t and t in tmap and not isinstance(v, tmap[t]):
            errs.append(f"{where}.{field} 类型应为 {t}，实为 {type(v).__name__}")
            continue
        if "enum" in cons and v not in cons["enum"]:
            errs.append(f"{where}.{field}={v!r} 不在允许值 {cons['enum']}")
    return errs


def suggest_assets(knowledge_point=None, kind=None, subject=None):
    """先查后建第一步（只读、无副作用，不递增 reuse_count）。

    返回库存清单（每个 html 原子附 interface 输入契约，供 compose 喂数）+ 建议编排方式。
    不预设固定主题/原子清单：库存有什么就建议什么，缺口如实声明。"""
    rows = list_assets(kind=kind, knowledge_point=knowledge_point, subject=subject)
    atoms, pages = [], []
    for r in rows:
        entry = {
            "asset_id": r["asset_id"], "kind": r["kind"], "title": r["title"],
            "subject": r["subject"], "knowledge_point": r["knowledge_point"],
            "reuse_count": r["reuse_count"],
            "file_path": os.path.normpath(os.path.join(ROOT, r["file_path"])),
        }
        if r["kind"] == "html":
            entry["interface"] = _interface_of(r)
        if r.get("assembly"):
            try:
                entry["assembly"] = json.loads(r["assembly"])
            except (TypeError, ValueError):
                pass
            pages.append(entry)
        else:
            atoms.append(entry)
    hints = []
    if atoms:
        hints.append("先向教师确认预期交互/效果（ask_user），再用 shiban_asset_compose 编排；"
                     "html 原子按 interface 声明喂数，缺省值由原子内部兜底。")
    if not atoms and not pages:
        hints.append("库存无匹配素材：新建原子（生成 HTML 后经 shiban_asset_add 入库，"
                     "kind=html 时用 interface_schema 声明输入契约）。")
    return {
        "knowledge_point": knowledge_point, "kind": kind, "subject": subject,
        "atoms": atoms, "pages": pages,
        "counts": {"atoms": len(atoms), "pages": len(pages)},
        "suggestions": hints,
    }


_SECTION_TPL = {
    "type": "object",
    "properties": {
        "asset": {"type": "string", "description": "库存原子 asset_id"},
        "label": {"type": "string", "description": "本节标题（编排页呈现）"},
        "data": {"type": "object", "description": "按该原子 interface 契约喂的数据"},
    },
    "required": ["asset"],
    "additionalProperties": False,
}


def compose_spec_schema():
    """compose 输入契约（单一真源：CLI --spec-schema 与 bundle 工具参数都由它派生）。"""
    return {
        "type": "object",
        "properties": {
            "page_id": {"type": "string", "description": "编排页面 asset_id"},
            "title": {"type": "string", "description": "页面标题"},
            "subject": {"type": "string"},
            "knowledge_point": {"type": "string"},
            "tags": {"type": "string", "description": "逗号分隔"},
            "layout": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["stack", "grid"],
                             "description": "stack=自上而下；grid=自适应网格并排"},
                    "gap": {"type": "number", "description": "节间距 px，默认 20"},
                },
                "additionalProperties": False,
            },
            "sections": {"type": "array", "items": _SECTION_TPL, "minItems": 1},
        },
        "required": ["page_id", "title", "sections"],
        "additionalProperties": False,
    }


def _compose_section(i, sec, atom):
    """把单个原子 main.html 内联为一个自包含节（作用域隔离 + 喂数注入）。

    隔离规则：style→<scope 前缀；script→IIFE + 实例 id 替换 + 裸选择器加 #scope 前缀；
    body→限定进 <section id>。零外链、零 iframe，产物仍是自包含单文件。"""
    html_path = os.path.join(ROOT, atom["file_path"])
    if not os.path.isfile(html_path):
        raise ValueError(f"原子主文件缺失: {atom['asset_id']} -> {html_path}")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    scope = f"shiban-sec-{i}"
    m_body = re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I)
    body = m_body.group(1) if m_body else html
    # 样式/脚本可能位于 <head> 或 <body>：一律从**整份文档**提取，body 中相应标签稍后移除
    style_src = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I)
    frag = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.S | re.I)
    frag = re.sub(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>", "", frag, flags=re.S | re.I)
    frag = re.sub(r"<script[^>]*\bsrc=[^>]*></script>", "", frag, flags=re.I)  # 禁运行时外链

    # 1) 样式作用域化：所有选择器前置 #scope（原子间类名互不污染）
    style = re.sub(r"(?m)^(?!@)([^{}@/]+)\{",
                   lambda mm: "".join(f"#{scope} {s.strip()}," if s.strip() else ""
                                      for s in mm.group(1).split(",")) + " {",
                   style_src)
    # CSS 自定义属性兜底：原子的 :root 变量被改写后不会命中本节，需在本节根重新声明
    vars_map = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;}]+)", style_src))
    if vars_map:
        style = ("#%s{%s}" % (scope, ";".join(f"{k}:{v.strip()}" for k, v in vars_map.items()))
                 + "\n" + style)
    # 2) 脚本隔离：IIFE + 实例 id 改名（同原子多次复用时 DOM id 不冲突）
    js = "\n".join(scripts)
    if js.strip():
        ids = sorted(set(re.findall(r"""getElementById\(['"]([^'"]+)['"]\)""", js)))
        for _id in ids:
            frag = frag.replace(f'id="{_id}"', f'id="{scope}-{_id}"')
            frag = frag.replace(f"id=\"{_id}\"", f"id=\"{scope}-{_id}\"")
            js = re.sub(r"""(['"])%s\1""" % re.escape(_id), f"'{scope}-{_id}'", js)
        js = ("(function(){\nvar __S=%s;\nfunction __q(s){"
              "return typeof s==='string'&&/^[.#>]/.test(s)?__S.querySelectorAll(s):s;}\n"
              "try{\n%s\n}catch(e){console.error('[shiban-atom %s]',e);}\n})();"
              % (json.dumps("#" + scope), js, atom["asset_id"]))
    # 3) 喂数注入：window.__MATERIAL_DATA 在该节脚本之前生效（原子按既有约定读取）
    data_json = json.dumps(sec.get("data") or {}, ensure_ascii=False, separators=(",", ":"))
    label = sec.get("label") or atom["title"]
    return (
        f'<section id="{scope}" class="shiban-sec" data-asset="{atom["asset_id"]}">\n'
        f'<style>\n{style}\n</style>\n'
        f'<div class="shiban-sec-label">{label}</div>\n'
        f'<div class="shiban-sec-body">{frag}</div>\n'
        f'<script>window.__MATERIAL_DATA=json.loads({json.dumps(data_json)});</script>\n'
        f'<script>{js}</script>\n'
        f'</section>'
    ), atom["asset_id"]


def compose_asset(spec):
    """v0.4.3 编排：按 interface 契约校验喂数 → 内联装配原子 → 自包含页面落盘入库。

    产物 data/assets/<page_id>/main.html（路径契约固定主文件名）。
    编排即复用：各引用原子 reuse_count+1；原子 parent_asset 指回本页（层级自由降级）；
    页面 assembly 记引用子组件与每处喂数。
    与 add_asset 共用查重/写盘校验（content_hash 去重、0 字节即报错）。

    vendor 边界：compose 产物**零外链零 iframe**；vendor 内化库的引用发生在**原子侧**
    （原子生成时若需外库，把库内容内联进自身 main.html，而非 compose 期拼 <script src>）。"""
    if not isinstance(spec, dict):
        raise ValueError("spec 必须是 JSON 对象")
    for k in ("page_id", "title", "sections"):
        if not spec.get(k):
            raise ValueError(f"spec 缺少必填字段: {k}")
    page_id = spec["page_id"]
    _valid_name(page_id)
    sections = spec["sections"]
    if not isinstance(sections, list) or not sections:
        raise ValueError("spec.sections 必须是非空数组")

    m = _connect(META_DB, META_SCHEMA)
    try:
        # id 已存在时延迟报错：若组装产物与既有素材 content_hash 相同仍走 existed 查重返回（幂等）
        if m.execute("SELECT 1 FROM assets WHERE asset_id=?", (page_id,)).fetchone():
            dup_by_id = True
        else:
            dup_by_id = False
        parts, used, assembly_secs = [], [], []
        for i, sec in enumerate(sections, 1):
            if not isinstance(sec, dict) or not sec.get("asset"):
                raise ValueError(f"sections[{i}] 缺少 asset 字段")
            row = m.execute("SELECT * FROM assets WHERE asset_id=?", (sec["asset"],)).fetchone()
            if not row:
                raise ValueError(f"原子不存在: {sec['asset']}（先 shiban_asset_add 入库）")
            if row["kind"] != "html":
                raise ValueError(f"sections[{i}] {sec['asset']} kind={row['kind']}，编排仅支持 html 原子")
            errs = _validate_data(_interface_of(row), sec.get("data"), f"sections[{i}]({sec['asset']})")
            if errs:
                raise ValueError("；".join(errs))
            frag, aid = _compose_section(i, sec, dict(row))
            parts.append(frag)
            used.append(aid)
            assembly_secs.append({"asset": aid, "label": sec.get("label"),
                                  "data": sec.get("data") or {}})

        layout = spec.get("layout") or {}
        mode = layout.get("mode", "stack")
        gap = layout.get("gap", 20)
        grid = "display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));" \
            if mode == "grid" else "display:block;"
        page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{spec["title"]}</title>
<style>
  body{{margin:0;background:#f8fafc;font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;color:#1f2937;}}
  .shiban-page{{max-width:1200px;margin:0 auto;padding:20px;}}
  .shiban-page-title{{font-size:20px;font-weight:700;margin:0 0 16px;}}
  .shiban-segments{{display:flex;flex-direction:column;gap:{gap}px;{grid}}}
  .shiban-sec{{background:#fff;}}
  .shiban-sec-label{{font-size:14px;font-weight:600;color:#0d9488;padding:10px 16px 0;}}
</style>
</head>
<body>
<div class="shiban-page">
<div class="shiban-page-title">{spec["title"]}</div>
<div class="shiban-segments">
{chr(10).join(parts)}
</div>
</div>
</body>
</html>
"""
        # 临时文件 → content_hash 查重（与 add_asset 同一去重通路）
        tmp = os.path.join(DATA_DIR, "assets", f".compose-{page_id}.tmp.html")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(page)
        try:
            with open(tmp, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            dup = m.execute("SELECT asset_id FROM assets WHERE content_hash=?", (digest,)).fetchone()
            if dup:
                return {"ok": True, "existed": True, "asset_id": dup["asset_id"],
                        "content_hash": digest}
            if dup_by_id:
                raise ValueError(f"素材 id 已存在: {page_id}（编排页请换 id，或先复用既有原子）")
            dest_dir = os.path.join(DATA_DIR, "assets", page_id)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, "main.html")  # 路径契约：固定主文件名 main.html
            shutil.move(tmp, dest)
            if os.path.getsize(dest) == 0:
                raise RuntimeError(f"写盘校验失败：{dest} 为 0 字节")
            now = _now()
            assembly = {"sections": assembly_secs, "layout": {"mode": mode, "gap": gap}}
            assembly_json = json.dumps(assembly, ensure_ascii=False)
            with open(os.path.join(dest_dir, "meta.json"), "w", encoding="utf-8") as mf:
                json.dump({"asset_id": page_id, "kind": "html", "title": spec["title"],
                           "subject": spec.get("subject"), "knowledge_point": spec.get("knowledge_point"),
                           "tags": spec.get("tags"), "parent_asset": None, "assembly": assembly,
                           "file": "main.html", "external": True, "created_at": now},
                          mf, ensure_ascii=False, indent=2)
            rel = os.path.relpath(dest, ROOT)
            m.execute(
                "INSERT INTO assets(asset_id,kind,title,subject,knowledge_point,source_lesson,"
                "params,tags,file_path,content_hash,reuse_count,parent_asset,assembly,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (page_id, "html", spec["title"], spec.get("subject"), spec.get("knowledge_point"),
                 spec.get("source_lesson"), None, spec.get("tags"), rel, digest, 0,
                 None, assembly_json, now, now))
            # 编排即复用：引用原子计数 +1；parent_asset 为空时指回本页（已有父层不覆盖——层级自由而非单亲）
            for aid in used:
                m.execute("UPDATE assets SET reuse_count=reuse_count+1,updated_at=? WHERE asset_id=?",
                          (now, aid))
                m.execute("UPDATE assets SET parent_asset=? WHERE asset_id=? AND parent_asset IS NULL",
                          (page_id, aid))
            m.commit()
            return {"ok": True, "existed": False, "asset_id": page_id,
                    "file_path": rel, "content_hash": digest,
                    "sections": len(sections), "atoms": sorted(set(used))}
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    finally:
        m.close()


# ---------- 现存产物治理（知识库整合 (a)：统一索引，不移动文件） ----------
_SCAN_RULES = (
    ("microeval_", "report"),
    ("last_eval", "report"),
    ("last_microeval", "report"),
    ("课例", "report"),
    ("report", "report"),
    ("transcript", "transcript"),
    ("note", "note"),
)


def _classify_existing(fname):
    low = fname.lower()
    for pat, kind in _SCAN_RULES:
        if pat in low:
            return kind
    return None


def scan_existing(dry_run=False):
    """把 data/shiban/ 下现存运行产物登记入 assets 索引（知识库整合范围 (a)）。

    只登记、不移动不复制（区别于 add_asset 的拷入语义）；已按 content_hash
    入库或同 asset_id 存在者跳过。个人数据（teacher_profile）永不登记。
    返回 {scanned, registered, skipped, items}。"""
    if not os.path.isdir(SHIBAN_DATA):
        return {"scanned": 0, "registered": 0, "skipped": 0, "items": []}
    m = _connect(META_DB, META_SCHEMA)
    items = []
    scanned = registered = skipped = 0
    try:
        for fname in sorted(os.listdir(SHIBAN_DATA)):
            fpath = os.path.join(SHIBAN_DATA, fname)
            if not os.path.isfile(fpath):
                continue
            scanned += 1
            if fname == "teacher_profile.json" or fname == ".gitkeep":
                skipped += 1
                continue
            kind = _classify_existing(fname)
            if kind is None:
                skipped += 1
                continue
            aid = "scan-" + re.sub(r"[^\w\u4e00-\u9fff-]+", "-", fname.rsplit(".", 1)[0]).strip("-")
            try:
                _valid_name(aid)
            except ValueError:
                skipped += 1
                continue
            if m.execute("SELECT 1 FROM assets WHERE asset_id=?", (aid,)).fetchone():
                skipped += 1
                continue
            with open(fpath, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            dup = m.execute("SELECT asset_id FROM assets WHERE content_hash=?", (digest,)).fetchone()
            if dup:
                items.append({"file": fname, "action": "skip-dup", "asset_id": dup["asset_id"]})
                skipped += 1
                continue
            if dry_run:
                items.append({"file": fname, "action": "dry-run", "kind": kind})
                registered += 1
                continue
            now = _now()
            m.execute(
                "INSERT INTO assets(asset_id,kind,title,subject,knowledge_point,source_lesson,"
                "params,tags,file_path,content_hash,reuse_count,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, kind, fname, None, None, None, None, "scanned",
                 os.path.relpath(fpath, ROOT), digest, 0, now, now),
            )
            m.commit()
            items.append({"file": fname, "action": "registered", "asset_id": aid, "kind": kind})
            registered += 1
        return {"scanned": scanned, "registered": registered, "skipped": skipped, "items": items}
    finally:
        m.close()


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