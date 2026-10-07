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
import base64
import hashlib
import html as html_lib
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


def _absolute_asset_path(file_path):
    """Resolve both current and legacy paths without escaping the data root."""
    if os.path.isabs(file_path):
        return os.path.normpath(file_path)
    candidates = [os.path.join(ROOT, file_path), os.path.join(DATA_DIR, file_path)]
    for candidate in candidates:
        if os.path.exists(candidate):
            return os.path.normpath(candidate)
    return os.path.normpath(candidates[0])


def _asset_result(row, **extra):
    result = dict(row) if row is not None else {}
    if row is not None:
        result["absolute_file_path"] = _absolute_asset_path(row["file_path"])
    result.update(extra)
    return result


def _assembly_to_json(assembly):
    if assembly is None or assembly == {} or assembly == []:
        return None
    if isinstance(assembly, str):
        if not assembly.strip() or assembly.strip() in ("{}", "[]", "null"):
            return None
        json.loads(assembly)
        return assembly
    return json.dumps(assembly, ensure_ascii=False)


def _is_page_assembly(raw):
    if not raw:
        return False
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(value, (dict, list)) and bool(value)


def _interface_of(row):
    """Read the legacy field-map interface and standard object JSON Schema."""
    path = os.path.join(os.path.dirname(_absolute_asset_path(row["file_path"])), "meta.json")
    try:
        with open(path, encoding="utf-8") as stream:
            meta = json.load(stream)
        params = meta.get("params") or {}
        if isinstance(params, dict) and params.get("interface") is not None:
            return params["interface"]
    except (OSError, ValueError, TypeError):
        pass
    try:
        params = json.loads(row["params"]) if row["params"] else {}
    except (TypeError, ValueError):
        params = {}
    return params.get("interface", params) if isinstance(params, dict) else {}


def _validate_data(interface, data, where):
    data = {} if data is None else data
    if not isinstance(data, dict):
        return [f"{where} 必须是 object"]
    # Legacy field map: {name: {type, required, enum}}. Standard schema uses properties.
    schema = interface or {}
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        fields = schema["properties"]
        required = set(schema.get("required") or [])
    elif isinstance(schema, dict):
        fields = schema
        required = {key for key, value in fields.items() if isinstance(value, dict) and value.get("required")}
    else:
        return []
    errors = [f"{where}.{key} 缺少必填字段" for key in required if key not in data]
    types = {"string": str, "number": (int, float), "integer": int, "boolean": bool,
             "array": list, "object": dict, "null": type(None)}
    for key, constraint in fields.items():
        if key not in data or not isinstance(constraint, dict):
            continue
        value = data[key]
        expected = constraint.get("type")
        if expected in types:
            actual_type = types[expected]
            if expected == "number" and isinstance(value, bool):
                errors.append(f"{where}.{key} 类型应为 number，实为 boolean")
            elif not isinstance(value, actual_type):
                errors.append(f"{where}.{key} 类型应为 {expected}，实为 {type(value).__name__}")
        if "enum" in constraint and value not in constraint["enum"]:
            errors.append(f"{where}.{key}={value!r} 不在允许值 {constraint['enum']}")
    return errors


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
        dup = m.execute("SELECT * FROM assets WHERE content_hash=?", (digest,)).fetchone()
        if dup:
            return _asset_result(dup, ok=True, existed=True, content_hash=digest)
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
        # 空编排（None / {} / []）一律存 NULL：'{}' 是 SQL 真值，会让页面判据误收原子
        assembly_json = _assembly_to_json(assembly)
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
    return _asset_result(row) if row else None


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
    rows = [_asset_result(r) for r in m.execute(sql, args).fetchall()]
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
                "file_path": row["file_path"],
                "absolute_file_path": _absolute_asset_path(row["file_path"])}
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


# ---------- v0.4.3 material engine (iframe/srcdoc isolation) ----------
def _material_read(row):
    path = _absolute_asset_path(row["file_path"])
    if not os.path.isfile(path):
        raise ValueError(f"素材主文件缺失: {row['asset_id']} -> {path}")
    with open(path, encoding="utf-8") as stream:
        return stream.read()


def _material_with_data(document, data):
    payload = json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    payload = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    injection = f"<script>window.__MATERIAL_DATA={payload};</script>"
    # Inject before any original script, including scripts inside head.
    head = re.search(r"<head\b[^>]*>", document, re.I)
    if head:
        return document[:head.end()] + injection + document[head.end():]
    opening = re.search(r"<html\b[^>]*>", document, re.I)
    if opening:
        return document[:opening.end()] + "<head>" + injection + "</head>" + document[opening.end():]
    return injection + document


def _material_section(index, section, row):
    document = _material_with_data(_material_read(row), section.get("data") or {})
    srcdoc = html_lib.escape(document, quote=True)
    label = html_lib.escape(str(section.get("label") or row["title"]), quote=True)
    asset_id = html_lib.escape(str(row["asset_id"]), quote=True)
    return (f'<section class="shiban-sec" data-asset="{asset_id}">'
            f'<div class="shiban-sec-label">{label}</div>'
            f'<iframe title="{label}" sandbox="allow-scripts" '
            f'srcdoc="{srcdoc}" class="shiban-sec-frame"></iframe></section>')


def compose_spec_schema():
    return {
        "type": "object",
        "properties": {
            "page_id": {"type": "string"}, "title": {"type": "string"},
            "subject": {"type": "string"}, "knowledge_point": {"type": "string"},
            "source_lesson": {"type": "string"}, "tags": {"type": "string"},
            "layout": {"type": "object", "properties": {
                "mode": {"type": "string", "enum": ["stack", "grid"]},
                "gap": {"type": "number", "minimum": 0, "maximum": 200}},
                "additionalProperties": False},
            "sections": {"type": "array", "minItems": 1, "items": {
                "type": "object", "properties": {
                    "asset": {"type": "string"}, "label": {"type": "string"},
                    "data": {"type": "object"}}, "required": ["asset"],
                "additionalProperties": False}},
        }, "required": ["page_id", "title", "sections"], "additionalProperties": False,
    }


def compose_asset(spec):
    if not isinstance(spec, dict):
        raise ValueError("spec 必须是 JSON 对象")
    for key in ("page_id", "title", "sections"):
        if not spec.get(key):
            raise ValueError(f"spec 缺少必填字段: {key}")
    _valid_name(spec["page_id"])
    sections = spec["sections"]
    if not isinstance(sections, list) or not sections:
        raise ValueError("spec.sections 必须是非空数组")
    layout = spec.get("layout") or {}
    if not isinstance(layout, dict):
        raise ValueError("spec.layout 必须是 object")
    mode = layout.get("mode", "stack")
    gap = layout.get("gap", 20)
    if mode not in ("stack", "grid") or isinstance(gap, bool) or not isinstance(gap, (int, float)) or not 0 <= gap <= 200:
        raise ValueError("layout.mode 必须为 stack/grid，gap 必须为 0..200 的 number")
    m = _connect(META_DB, META_SCHEMA)
    temp = None
    dest_dir = None
    created_dir = False
    try:
        existing_id = m.execute("SELECT * FROM assets WHERE asset_id=?", (spec["page_id"],)).fetchone()
        parts, used, records = [], [], []
        for index, section in enumerate(sections, 1):
            if not isinstance(section, dict) or not section.get("asset"):
                raise ValueError(f"sections[{index}] 缺少 asset 字段")
            row = m.execute("SELECT * FROM assets WHERE asset_id=?", (section["asset"],)).fetchone()
            if not row or row["kind"] != "html":
                raise ValueError(f"sections[{index}] 原子不存在或不是 html: {section.get('asset')}")
            data = section.get("data") or {}
            errors = _validate_data(_interface_of(row), data, f"sections[{index}]({row['asset_id']})")
            if errors:
                raise ValueError("；".join(errors))
            parts.append(_material_section(index, section, row))
            used.append(row["asset_id"])
            records.append({"asset": row["asset_id"], "label": section.get("label"), "data": data})
        title = html_lib.escape(str(spec["title"]), quote=True)
        display = "display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));" if mode == "grid" else "display:flex;flex-direction:column;"
        page = ('<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f"<title>{title}</title><style>body{{margin:0;background:#f8fafc;"
                "font-family:system-ui,sans-serif;color:#1f2937}}.shiban-page{max-width:1200px;"
                "margin:0 auto;padding:20px}.shiban-page-title{font-size:20px;font-weight:700;"
                f"margin:0 0 16px}}.shiban-segments{{{display}gap:{gap}px}}"
                ".shiban-sec{background:#fff}.shiban-sec-label{font-size:14px;font-weight:600;"
                "color:#0d9488;padding:10px 16px 0}.shiban-sec-frame{display:block;width:100%;"
                'min-height:120px;border:0}</style></head><body><main class="shiban-page">'
                f'<div class="shiban-page-title">{title}</div><div class="shiban-segments">'
                + "".join(parts) + '</div></main></body></html>')
        digest = hashlib.sha256(page.encode("utf-8")).hexdigest()
        dup = m.execute("SELECT * FROM assets WHERE content_hash=?", (digest,)).fetchone()
        if dup:
            return _asset_result(dup, ok=True, existed=True, content_hash=digest)
        aid = spec["page_id"]
        if existing_id is not None:
            raise ValueError(f"素材 id 已存在: {aid}（内容不同，请换 id）")
        dest_dir = os.path.join(DATA_DIR, "assets", aid)
        os.makedirs(dest_dir, exist_ok=False)
        dest = os.path.join(dest_dir, "main.html")
        temp = dest + ".tmp"
        with open(temp, "w", encoding="utf-8") as stream:
            stream.write(page)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, dest)
        assembly = {"sections": records, "layout": {"mode": mode, "gap": gap}}
        now = _now(); rel = os.path.relpath(dest, ROOT)
        meta_path = os.path.join(dest_dir, "meta.json")
        with open(meta_path + ".tmp", "w", encoding="utf-8") as stream:
            json.dump({"asset_id": aid, "kind": "html", "title": spec["title"],
                       "subject": spec.get("subject"), "knowledge_point": spec.get("knowledge_point"),
                       "params": None, "tags": spec.get("tags"), "assembly": assembly,
                       "file": "main.html", "external": True, "created_at": now}, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(meta_path + ".tmp", meta_path)
        m.execute("BEGIN")
        m.execute("INSERT INTO assets(asset_id,kind,title,subject,knowledge_point,source_lesson,params,tags,file_path,content_hash,reuse_count,parent_asset,assembly,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (aid, "html", spec["title"], spec.get("subject"), spec.get("knowledge_point"), spec.get("source_lesson"), None, spec.get("tags"), rel, digest, 0, None, json.dumps(assembly, ensure_ascii=False), now, now))
        for used_id in used:
            m.execute("UPDATE assets SET reuse_count=reuse_count+1,updated_at=? WHERE asset_id=?", (now, used_id))
            m.execute("UPDATE assets SET parent_asset=? WHERE asset_id=? AND parent_asset IS NULL", (aid, used_id))
        m.commit()
        row = m.execute("SELECT * FROM assets WHERE asset_id=?", (aid,)).fetchone()
        return _asset_result(row, ok=True, existed=False, sections=len(sections), atoms=sorted(set(used)))
    except Exception:
        if m.in_transaction:
            m.rollback()
        if temp:
            for path in (temp, temp[:-4] if temp.endswith(".tmp") else temp):
                try:
                    if os.path.isfile(path): os.remove(path)
                except OSError: pass
        if dest_dir and os.path.isdir(dest_dir) and not os.listdir(dest_dir):
            try:
                os.rmdir(dest_dir)
            except OSError:
                pass
        raise
    finally:
        m.close()


def suggest_assets(knowledge_point=None, kind=None, subject=None, knowledge_point_mode="contains"):
    if knowledge_point_mode not in ("exact", "contains"):
        raise ValueError("未知 knowledge_point_mode: %r" % knowledge_point_mode)
    rows = list_assets(kind=kind, knowledge_point=knowledge_point, subject=subject) if not knowledge_point or knowledge_point_mode == "exact" else list_assets(kind=kind, subject=subject)
    if knowledge_point and knowledge_point_mode == "contains":
        needle = knowledge_point.casefold()
        rows = [row for row in rows if needle in (row.get("knowledge_point") or "").casefold()]
    atoms, pages = [], []
    for row in rows:
        entry = {"asset_id": row["asset_id"], "kind": row["kind"], "title": row["title"], "subject": row["subject"], "knowledge_point": row["knowledge_point"], "reuse_count": row["reuse_count"], "file_path": row["file_path"], "absolute_file_path": row["absolute_file_path"]}
        if row["kind"] == "html": entry["interface"] = _interface_of(row)
        if _is_page_assembly(row.get("assembly")):
            try: entry["assembly"] = json.loads(row["assembly"])
            except (TypeError, ValueError): pass
            pages.append(entry)
        else: atoms.append(entry)
    hints = ["先确认预期交互/布局，再用 compose 编排。"] if atoms else ["库存无匹配素材，可先创建 html 原子。"]
    return {"knowledge_point": knowledge_point, "kind": kind, "subject": subject, "knowledge_point_mode": knowledge_point_mode, "atoms": atoms, "pages": pages, "counts": {"atoms": len(atoms), "pages": len(pages)}, "suggestions": hints}


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