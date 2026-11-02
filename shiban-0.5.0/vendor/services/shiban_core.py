"""师伴 Shiban v0.5.0 · 核心数据层（artifact store）。

数据流（谁写、写哪、怎么读）
------------------------------
写：
  * Agent / 技能**不直接碰文件**。凡要落盘的产物（task / lp / les / quiz /
    ev / mev / growth / asset / pref）一律调用本模块的 ``put()``。
  * ``put()`` 先把 envelope 补全、校验、定 rev，原子写到
    ``<root>/data/artifacts/<kind>/<id>.json``（真源，人类可读、可 diff），
    然后在**同一事务**内更新 ``<root>/data/graph.db``：``nodes`` 表 upsert，
    ``edges`` 表按 ``envelope.refs`` 整组重建。任一步失败都回滚文件。
  * 状态变更（confirm / discard / archive / mark_stale）同样只是"改 envelope
    再 put"，因此 rev 永远单调递增，历史留在 ``envelope.history``。
  * L0 证据（课标原文、听课记录、学生作业扫描文本…）只追加：
    ``save_evidence()`` 写到 ``<root>/data/evidence/``，同名即拒绝。
  * L2 索引由**程序**生成：``rebuild_indexes()`` 扫描 artifacts 写出
    ``<root>/data/indexes/<kind>.jsonl``；该目录随时可删可重建，不是真源。

读：
  * ``get(id, view)`` 四个视图按"读多少"递进：``index``（<2KB 卡片）→
    ``digest``（+ 结构摘要，仍 <2KB）→ ``section``（单节，见 ``get_section``）
    → ``full``（完整 envelope）。Agent 默认应当只读 index/digest，
    需要正文时按节取，避免把整份教案灌进上下文。
  * ``get_section()/set_section()`` 支持 ``"S8"`` 以及 ``"S8[2]"`` 下标寻址，
    ``set_section()`` 只替换 payload 的一个键，用于"章节重做"。
  * 图查询：``graph_neighbors()`` 看引用关系，``graph_query()`` 看全局统计。

真源与派生物
------------
    真源   data/artifacts/**/*.json  +  data/evidence/*
    派生   data/indexes/*.jsonl     +  data/graph.db（可从真源重建）

约束：零第三方依赖；所有写入 tmp + fsync + os.replace 原子化；
所有 id/name 进文件名前逐段过白名单正则；一切文本 IO 显式 UTF-8。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "ShibanError",
    "root",
    "ensure_layout",
    "constants",
    "make_id",
    "slugify",
    "put",
    "get",
    "get_section",
    "set_section",
    "list_artifacts",
    "confirm",
    "discard",
    "archive",
    "mark_stale",
    "graph_neighbors",
    "graph_query",
    "rebuild_graph",
    "save_evidence",
    "list_evidence",
    "read_evidence",
    "rebuild_indexes",
]


# --------------------------------------------------------------------------- #
# 错误
# --------------------------------------------------------------------------- #


class ShibanError(Exception):
    """带机器可读 code 的领域错误。

    code 取值（约定，调用方可据此分支）：
      constants_missing / bad_json            —— 共享约定读不到
      bad_kind / bad_payload / bad_envelope   —— put() 入参非法
      not_found                               —— 目标产物不存在
      rev_conflict                            —— 乐观锁冲突
      exists / unsafe_path / bad_name         —— 文件冲突或路径不安全
      cycle                                   —— 引用成环
      io                                      —— 其他文件/数据库错误
    """

    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def __str__(self) -> str:  # noqa: D105 - 简单格式化
        if self.hint:
            return f"[{self.code}] {self.message} —— {self.hint}"
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


# --------------------------------------------------------------------------- #
# 常量与路径
# --------------------------------------------------------------------------- #

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONSTANTS_PATH = _PROJECT_ROOT / "contracts" / "constants.json"
_CONSTANTS: dict | None = None

SCHEMA_ID = "shiban.artifact/1"

# id 各段白名单：\w（含中文）+ . - ；不含下划线之外的危险字符，天然排除 ".." / "/" / ":"
_ID_PART_RE = re.compile(r"[\w\u4e00-\u9fff.-]")
_DANGEROUS_RE = re.compile(r"[^\w\u4e00-\u9fff.-]+")
_EVIDENCE_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff.-]+$")
_SECTION_RE = re.compile(r"^\s*([^\[\]]+?)\s*(?:\[\s*(-?\d+)\s*\])?\s*$")

SLUG_MAX = 24
SCOPE_MAX = 24
DIGEST_SCALAR_MAX = 60  # digest 里单个标量最多回显的字符数
INDEX_VIEW_MAX = 2048  # index 视图超限时逐步丢字段，硬保证 < 2KB


def constants() -> dict:
    """读取并缓存 ``contracts/constants.json``（唯一常量真源）。

    路径由 ``__file__`` 推算：``vendor/services/shiban_core.py`` → 上两级到项目根。
    """
    global _CONSTANTS
    if _CONSTANTS is None:
        if not _CONSTANTS_PATH.is_file():
            raise ShibanError(
                "constants_missing",
                f"找不到共享约定文件：{_CONSTANTS_PATH}",
                "请确认项目根下存在 contracts/constants.json（它是唯一常量真源）。",
            )
        try:
            with open(_CONSTANTS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            raise ShibanError(
                "bad_json",
                f"contracts/constants.json 读取失败：{exc}",
                "该文件必须是合法 UTF-8 JSON。",
            ) from exc
        if not isinstance(data, dict):
            raise ShibanError("bad_json", "contracts/constants.json 顶层必须是对象")
        _CONSTANTS = data
    return _CONSTANTS


def _kinds() -> list:
    return list(constants().get("artifact_kinds") or [])


def _statuses() -> list:
    return list(constants().get("statuses") or [])


def _views() -> list:
    return list(constants().get("views") or [])


def pkg_dir() -> str:
    """本包的安装目录。用 __file__ 动态推导，不写死路径——
    DSH 用 pnpm link 安装时，node_modules/@local/<pkg> 指向真实目录，
    升级或换 profile 后位置会变，因此每次调用都重新计算。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def package_meta() -> dict:
    """读 package.json 里的版本与 shiban 元信息。"""
    try:
        with open(os.path.join(pkg_dir(), "package.json"), encoding="utf-8") as fh:
            pkg = json.load(fh)
    except (OSError, ValueError):
        return {"version": "0.0.0", "name": "shiban", "shiban": {}}
    return {"version": str(pkg.get("version") or "0.0.0"),
            "name": pkg.get("name") or "shiban",
            "shiban": pkg.get("shiban") or {}}


def version_slug() -> str:
    """0.5.0 → v0_5_0，用作目录名后缀。"""
    return "v" + re.sub(r"[^0-9]", "_", package_meta()["version"])


def legacy_root() -> str:
    """本系列的固定根（跨版本共享的上层）。实际数据根在其下的版本目录。"""
    env = constants().get("root_env") or "SHIBAN_ROOT"
    default = constants().get("default_root") or "~/.shiban"
    raw = os.environ.get(env) or default
    return os.path.abspath(os.path.expanduser(raw))


WORKSPACE_MARKER = ".shiban"

# 解析顺序（越靠前优先级越高）：
#   1. SHIBAN_DATA_DIR        显式指定，完全接管（测试/多实例）
#   2. <工作区>/.shiban/versions/<vX_Y_Z>/   默认：一切限制在工作区内，受 DSH 沙箱保护
#   3. <SHIBAN_ROOT>/versions/<vX_Y_Z>/      仅有显式 SHIBAN_ROOT 时（跨工作区共享）
#
# 为什么默认在工作区内：DSH 的文件沙箱是 workspace-write，工作区外的写入会被拒。
# 把数据放在 ~/.shiban 会让 Agent 的每次落盘都失败（v0.5.0 首次实测即如此）。


def workspace_root() -> str | None:
    """当前工作区根：有 .git 的最近祖先，否则 cwd。"""
    cur = os.path.abspath(os.getcwd())
    probe = cur
    while True:
        if os.path.isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return cur
        probe = parent


def root() -> str:
    """本版本的数据根。

    默认落在 ``<工作区>/.shiban/``——一切在工作区内，受 DSH 沙箱保护，
    Agent 可自由落盘，数据随工作区一起走。工作区本身即隔离边界，
    因此不再在其下再套一层版本目录；版本记录在 ``.shiban/VERSION``。
    显式 ``SHIBAN_ROOT`` 时才用工作区外的共享根（需自行确保可写）。
    """
    override = os.environ.get("SHIBAN_DATA_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if os.environ.get("SHIBAN_ROOT"):
        return os.path.join(legacy_root(), "versions", version_slug())
    return os.path.join(workspace_root(), WORKSPACE_MARKER)


def _layout() -> dict:
    r = root()
    data = os.path.join(r, "data")
    return {
        "root": r,
        "data": data,
        "artifacts": os.path.join(data, "artifacts"),
        "evidence": os.path.join(data, "evidence"),
        "indexes": os.path.join(data, "indexes"),
        "graph_db": os.path.join(data, "graph.db"),
        "corpus": os.path.join(r, "corpus"),
    }


def ensure_layout() -> dict:
    """建目录骨架，返回 ``{root, data, artifacts, evidence, indexes, graph_db, corpus}``。

    幂等；会确保 graph.db 的表结构存在。
    """
    layout = _layout()
    for key in ("root", "data", "artifacts", "evidence", "indexes", "corpus"):
        os.makedirs(layout[key], exist_ok=True)
    for kind in _kinds():
        os.makedirs(os.path.join(layout["artifacts"], kind), exist_ok=True)
    # 建表（不存在则建），随后立即关闭，避免长连接
    conn = _db()
    conn.close()
    return layout


# --------------------------------------------------------------------------- #
# 标识
# --------------------------------------------------------------------------- #


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def slugify(text: str, limit: int = SLUG_MAX) -> str:
    """清洗一段成可入文件名的 slug：去空白与 ``/ \\ : * ? " < > |``，限长，中文保留。

    另做的额外防护：连续 ``.`` / ``-`` 压成一个，去掉首尾的 ``.-_``（因此
    不可能出现 ``..`` 或以点开头的隐藏文件）；空结果返回 ``"x"``。
    """
    s = "" if text is None else str(text)
    s = re.sub(r"\s+", "", s)
    s = s.replace("/", "").replace("\\", "").replace(":", "")
    for ch in '*?"<>|':
        s = s.replace(ch, "")
    s = "".join(ch if _ID_PART_RE.fullmatch(ch) else "_" for ch in s)
    s = re.sub(r"\.{2,}", ".", s)
    s = re.sub(r"-{2,}", "-", s)
    s = re.sub(r"_{2,}", "_", s)
    s = s.strip(".-_")
    s = s[:limit]
    s = s.strip(".-_")
    return s or "x"


def make_id(kind: str, scope: str, slug: str, payload: dict) -> str:
    """生成 ``<kind>-<scope>-<slug>-<sha4>``。

    ``sha4`` = canonical json（sort_keys, ensure_ascii=False, 紧凑分隔符）
    的 sha256 前 4 位十六进制。scope/slug 同样清洗。
    """
    if kind not in _kinds():
        raise ShibanError(
            "bad_kind",
            f"未知产物类型：{kind!r}",
            f"合法值：{', '.join(_kinds())}",
        )
    k = slugify(kind, 12)
    s = slugify(scope, SCOPE_MAX) or "na"
    g = slugify(slug, SLUG_MAX) or "untitled"
    digest = hashlib.sha256(
        _canonical(payload if isinstance(payload, dict) else {}).encode("utf-8")
    ).hexdigest()[:4]
    return f"{k}-{s}-{g}-{digest}"


def _safe_id(artifact_id) -> str:
    """校验并返回一个可以安全拼进文件名的 artifact id。"""
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise ShibanError("bad_name", f"非法 artifact id：{artifact_id!r}")
    aid = artifact_id.strip()
    if "/" in aid or "\\" in aid or ".." in aid:
        raise ShibanError(
            "unsafe_path",
            f"artifact id 含路径成分：{artifact_id!r}",
            "id 必须是 <kind>-<scope>-<slug>-<sha4>，不得含 / \\ ..",
        )
    kind = aid.split("-", 1)[0]
    if kind not in _kinds():
        raise ShibanError(
            "bad_kind",
            f"artifact id 前缀不是合法 kind：{artifact_id!r}",
            f"合法值：{', '.join(_kinds())}",
        )
    if not _EVIDENCE_NAME_RE.fullmatch(aid):
        raise ShibanError(
            "unsafe_path",
            f"artifact id 含非法字符：{artifact_id!r}",
            "允许：字母数字下划线、中文、点、连字符。",
        )
    return aid


def _artifact_path(artifact_id: str) -> str:
    aid = _safe_id(artifact_id)
    kind = aid.split("-", 1)[0]
    return os.path.join(_layout()["artifacts"], kind, aid + ".json")


# --------------------------------------------------------------------------- #
# 底层 IO：原子写 / 读 / db
# --------------------------------------------------------------------------- #


def _atomic_write_text(path: str, text: str) -> None:
    """``<path>.tmp`` → flush + fsync → os.replace。失败清理 tmp。"""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            if os.path.exists(tmp):
                os.remove(tmp)
        raise
    # 目录项也落盘（尽力而为；部分文件系统不支持对目录 fsync）
    with contextlib.suppress(OSError):
        dfd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _db() -> sqlite3.Connection:
    layout = _layout()
    os.makedirs(os.path.dirname(layout["graph_db"]), exist_ok=True)
    conn = sqlite3.connect(layout["graph_db"], timeout=10.0, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    # 建表用 executescript：它在 autocommit 下会隐式提交并重置事务状态，
    # 因此只在库还没有表时执行一次。每次连接都执行会让随后的
    # BEGIN IMMEDIATE 落在已被重置的连接上，导致写入静默丢失。
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nodes'"
    ).fetchone():
        conn.executescript(
            """
            CREATE TABLE nodes(
              id TEXT PRIMARY KEY, kind TEXT, status TEXT, rev INTEGER,
              scope TEXT, topic TEXT, date TEXT, title TEXT, updated_at TEXT);
            -- 不用复合主键：SQLite 对 (src,dst,role) 覆盖索引上
            -- `WHERE src=?` 的 TEXT 等值查询在本环境会漏行。
            -- 唯一性由 _rebuild_edges 先 DELETE 再插入保证。
            CREATE TABLE edges(
              src TEXT, dst TEXT, role TEXT, candidate INTEGER DEFAULT 0);
            CREATE INDEX edges_src ON edges(src);
            CREATE INDEX edges_dst ON edges(dst);
            """
        )
    return conn


@contextlib.contextmanager
def _tx(conn: sqlite3.Connection):
    """显式事务。sqlite3 在未 COMMIT 就 close() 时会静默丢弃写入，
    因此这里必须显式提交，并由调用方在 finally 里 close()。"""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


# --------------------------------------------------------------------------- #
# envelope 规范化
# --------------------------------------------------------------------------- #

_LIST_FIELDS = ("refs", "citations", "degrade", "controversy")
_DICT_FIELDS = ("producer", "subject_line")


def _subject_of(env: dict) -> dict:
    sl = env.get("subject_line")
    return sl if isinstance(sl, dict) else {}


def _split_refs(refs) -> tuple:
    """把 ``role=evidence`` 的引用从 refs 分流出去。

    证据不是产物节点：它住在 data/evidence/，不该进 graph，
    否则会被当作"尚未落盘的弱边"，语义错误。
    """
    graph_refs, evidence_refs = [], []
    for ref in (refs or []):
        if isinstance(ref, dict) and ref.get("role") == "evidence":
            evidence_refs.append(ref)
        else:
            graph_refs.append(ref)
    return graph_refs, evidence_refs


def _apply_evidence_split(env: dict) -> dict:
    """规范化后执行：refs 里的 evidence 移入 evidence[]，并标注文件是否真实存在。"""
    graph_refs, moved = _split_refs(env.get("refs"))
    env["refs"] = graph_refs
    if moved:
        existing = [e for e in (env.get("evidence") or []) if isinstance(e, dict)]
        known = {e.get("id") for e in existing}
        base = core_layout_evidence()
        for ref in moved:
            if ref.get("id") in known:
                continue
            entry = {"id": ref.get("id"), "role": "evidence"}
            if not os.path.isfile(os.path.join(base, str(ref.get("id")))):
                entry["missing"] = True
                entry["hint"] = "证据文件不存在；先 shiban-store evidence save 落盘"
            existing.append(entry)
            known.add(ref.get("id"))
        env["evidence"] = existing
    return env


def core_layout_evidence() -> str:
    return _layout()["evidence"]


def _norm_refs(refs) -> list:
    out = []
    if not isinstance(refs, list):
        return out
    for item in refs:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            out.append({"role": str(item.get("role") or "ref"), "id": item["id"].strip()})
        elif isinstance(item, str) and item.strip():
            out.append({"role": "ref", "id": item.strip()})
    return out


def _normalize(envelope: dict, old: dict | None, expected_rev: int | None) -> dict:
    """补全固定字段、定 rev、维护 history。返回写入用的新 dict（不改入参）。"""
    env = dict(envelope)

    # subject_line / producer 类型守卫
    if "subject_line" in env and not isinstance(env["subject_line"], dict):
        raise ShibanError("bad_envelope", "subject_line 必须是对象", "形如 {scope, topic, date, kp}")
    if "producer" in env and not isinstance(env["producer"], dict):
        raise ShibanError("bad_envelope", "producer 必须是对象", "形如 {atom, skills_loaded}")

    # 列表字段归一化
    for field in _LIST_FIELDS:
        if field in env and not isinstance(env[field], list):
            raise ShibanError("bad_envelope", f"{field} 必须是列表", "")
        if field == "refs" and "refs" in env:
            env["refs"] = _norm_refs(env["refs"])

    now = _now()
    env["schema"] = SCHEMA_ID

    if old is None:
        env.setdefault("rev", 1)
        env["rev"] = 1
        env.setdefault("created_at", now)
        env["updated_at"] = now
        env.setdefault("status", "in_progress")
        env.setdefault("producer", {})
        env.setdefault("subject_line", {})
        for field in _LIST_FIELDS:
            env.setdefault(field, [])
        history = list(env.get("history") or [])
        env["history"] = history
    else:
        old_rev = int(old.get("rev") or 0)
        if expected_rev is not None and int(expected_rev) != old_rev:
            raise ShibanError(
                "rev_conflict",
                f"rev 冲突：期望 {expected_rev}，实际 {old_rev}",
                "请先 get(id, 'index') 取最新 rev 后重试。",
            )
        env["rev"] = old_rev + 1
        env["created_at"] = old.get("created_at") or now
        env["updated_at"] = now
        # 更新时沿用旧 envelope 的未提供字段（部分更新语义）
        for field in ("producer", "subject_line") + _LIST_FIELDS:
            if field not in env:
                env[field] = old.get(field, {} if field in _DICT_FIELDS else [])
        history = list(old.get("history") or [])
        history.append({"rev": env["rev"], "at": now, "by": old_rev or (expected_rev or 0)})
        env["history"] = history
        if "status" in old and old["status"] in _statuses() and "status" not in envelope:
            env["status"] = old["status"]

    env.setdefault("status", "in_progress")
    if env["status"] not in _statuses():
        raise ShibanError(
            "bad_envelope",
            f"非法 status：{env['status']!r}",
            f"合法值：{', '.join(_statuses())}",
        )

    payload = env.get("payload")
    if payload is None:
        env["payload"] = {}
    elif not isinstance(payload, dict):
        raise ShibanError("bad_payload", "payload 必须是对象（dict）", "即使为空也要用 {}")

    return env


def _node_row(env: dict) -> tuple:
    sl = _subject_of(env)
    payload = env.get("payload") or {}
    title = sl.get("title") or payload.get("title") or ""
    row = (
        env.get("id"),
        env.get("kind"),
        env.get("status"),
        int(env.get("rev") or 0),
        str(sl.get("scope") or ""),
        str(sl.get("topic") or ""),
        str(sl.get("date") or ""),
        str(title),
        env.get("updated_at"),
    )
    return tuple("" if v is None else v for v in row)


def _upsert_node(conn: sqlite3.Connection, env: dict) -> None:
    conn.execute(
        "INSERT INTO nodes(id, kind, status, rev, scope, topic, date, title, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, status=excluded.status, "
        "rev=excluded.rev, scope=excluded.scope, topic=excluded.topic, date=excluded.date, "
        "title=excluded.title, updated_at=excluded.updated_at",
        _node_row(env),
    )


def _node_exists(conn: sqlite3.Connection, node_id: str) -> bool:
    cur = conn.execute("SELECT 1 FROM nodes WHERE id=?", (node_id,))
    return cur.fetchone() is not None


def _check_cycle(conn: sqlite3.Connection, src: str, refs: list) -> None:
    """若 src 的强边（目标已存在）中有"目标沿边能回到 src"的，即视为成环。"""
    for ref in refs:
        dst = ref["id"]
        if dst == src or not _node_exists(conn, dst):
            continue
        seen = set()
        frontier = [dst]
        while frontier:
            cur_id = frontier.pop()
            if cur_id == src:
                raise ShibanError(
                    "cycle",
                    f"引用成环：{src} → {dst} → … → {src}",
                    "请去掉造成环的那条 ref，或把关系改由上游节点单向声明。",
                )
            if cur_id in seen:
                continue
            seen.add(cur_id)
            rows = conn.execute("SELECT dst FROM edges WHERE src=?", (cur_id,)).fetchall()
            frontier.extend(r[0] for r in rows if r[0] not in seen)


def _rebuild_edges(conn: sqlite3.Connection, src: str, refs: list) -> None:
    conn.execute("DELETE FROM edges WHERE src=?", (src,))
    rows = []
    for ref in refs:
        if ref["id"] == src:
            continue  # 自引用无意义，不进图
        candidate = 0 if _node_exists(conn, ref["id"]) else 1
        rows.append((src, ref["id"], ref["role"], candidate))
    if rows:
        conn.executemany(
            "INSERT INTO edges(src, dst, role, candidate) VALUES(?,?,?,?)", rows
        )


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #


def put(envelope: dict, expected_rev: int | None = None) -> dict:
    """写入（新建或更新）一个产物。返回 ``{"id","rev","path","status"}``。

    任何异常都会回滚：本次新建的文件被删除；更新则恢复旧字节内容，
    且 graph.db 事务整体回滚。
    """
    if not isinstance(envelope, dict):
        raise ShibanError("bad_envelope", "envelope 必须是 dict", "")
    kind = envelope.get("kind")
    if kind not in _kinds():
        raise ShibanError(
            "bad_kind",
            f"未知产物类型：{kind!r}",
            f"合法值：{', '.join(_kinds())}",
        )
    if not isinstance(envelope.get("payload"), dict):
        raise ShibanError("bad_payload", "payload 必须是对象（dict）", "即使为空也要用 {}")

    layout = ensure_layout()
    env = dict(envelope)

    # 2) 无 id 时自动生成
    if not env.get("id"):
        sl = _subject_of(env)
        slug = sl.get("topic") or env["payload"].get("title") or "untitled"
        env["id"] = make_id(kind, sl.get("scope") or "na", slug, env["payload"])

    aid = _safe_id(env["id"])
    env["id"] = aid
    path = _artifact_path(aid)

    old = _read_json(path) if os.path.exists(path) else None
    if old is not None and not isinstance(old, dict):
        raise ShibanError("io", f"已有产物不是 JSON 对象：{path}", "请人工检查该文件。")

    keep_copies = []  # [(path, bytes)] 回滚时用
    if old is not None:
        with open(path, "rb") as fh:
            keep_copies.append((path, fh.read()))

    conn = _db()
    try:
        with _tx(conn):
            new_env = _apply_evidence_split(_normalize(env, old, expected_rev))
            # 兜底：确保事务结束时提交，否则 close() 会静默丢弃
            refs = new_env.get("refs") or []
            _upsert_node(conn, new_env)
            # 先建本节点的边，再做环检测：否则「A 引用已存在的 B，而 B 引用 A」
            # 这种情况在按序写入时检测不到。
            _rebuild_edges(conn, aid, refs)
            _check_cycle(conn, aid, refs)

            # 文件写入放在 db 事务内：db 失败 → 回滚文件
            payload = json.dumps(new_env, indent=2, ensure_ascii=False) + "\n"
            _atomic_write_text(path, payload)
    except BaseException:
        _rollback_files(keep_copies, path)
        raise
    finally:
        conn.close()

    return {"id": aid, "rev": new_env["rev"], "path": path, "status": new_env["status"]}


def _rollback_files(keep_copies: list, path: str) -> None:
    """恢复旧内容；无旧内容则删掉本次新建的文件。"""
    try:
        if keep_copies:
            old_path, old_bytes = keep_copies[0]
            with open(old_path, "wb") as fh:
                fh.write(old_bytes)
                fh.flush()
                os.fsync(fh.fileno())
        else:
            with contextlib.suppress(OSError):
                if os.path.exists(path):
                    os.remove(path)
        with contextlib.suppress(OSError):
            if os.path.exists(path + ".tmp"):
                os.remove(path + ".tmp")
    except OSError:
        pass  # 回滚尽力而为，不掩盖原始异常


# --------------------------------------------------------------------------- #
# 视图
# --------------------------------------------------------------------------- #


def _one_liner(payload: dict, limit: int = 80) -> str:
    for key in ("one_liner", "summary", "abstract", "title"):
        val = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(val, str) and val.strip():
            text = re.sub(r"\s+", " ", val.strip())
            return text if len(text) <= limit else text[: limit - 1] + "…"
    return ""


def _index_view(env: dict) -> dict:
    sl = _subject_of(env)
    payload = env.get("payload") or {}
    refs = env.get("refs") or []
    cites = env.get("citations") or []
    view = {
        "id": env.get("id"),
        "kind": env.get("kind"),
        "status": env.get("status"),
        "rev": env.get("rev"),
        "topic": sl.get("topic") or payload.get("title") or "",
        "date": sl.get("date") or "",
        "title": sl.get("title") or payload.get("title") or "",
        "refs_count": len(refs),
        "citations_count": len(cites),
        "one_liner": _one_liner(payload),
    }
    # 硬保证：< 2KB。超限时按"最不关键"到"最关键"的顺序丢字段。
    for drop in ("one_liner", "title", "date", "topic"):
        if len(json.dumps(view, ensure_ascii=False).encode("utf-8")) < INDEX_VIEW_MAX:
            break
        view.pop(drop, None)
    if len(json.dumps(view, ensure_ascii=False).encode("utf-8")) >= INDEX_VIEW_MAX:
        view["topic"] = str(view.get("topic") or "")[:32]
        view["title"] = str(view.get("title") or "")[:32]
    return view


def _scalar(x) -> str:
    if isinstance(x, bool):
        s = "true" if x else "false"
    elif x is None:
        s = "null"
    elif isinstance(x, (int, float)):
        s = json.dumps(x)
    else:
        s = str(x)
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= DIGEST_SCALAR_MAX else s[: DIGEST_SCALAR_MAX - 1] + "…"


def _shape(value, depth: int = 0):
    """结构摘要：只描述形状和短标量，绝不回显长文本。"""
    if depth > 2:
        return "…"
    if isinstance(value, dict):
        return {str(k): _shape(v, depth + 1) for k, v in list(value.items())[:24]}
    if isinstance(value, list):
        head = [_shape(v, depth + 1) for v in value[:3]]
        return {"_list": len(value), "_head": head}
    if isinstance(value, str):
        return _scalar(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _scalar(value)


def _digest_view(env: dict) -> dict:
    payload = env.get("payload") or {}
    view = _index_view(env)
    keys = list(payload.keys())[:32]
    shapes = {k: _shape(payload[k]) for k in keys}
    lists = {
        k: len(v)
        for k, v in payload.items()
        if isinstance(v, list) and k in keys
    }
    view.update(
        {
            "payload_keys": keys,
            "payload_shapes": shapes,
            "list_sizes": lists,
            "refs": [
                {"role": r.get("role"), "id": r.get("id")}
                for r in (env.get("refs") or [])[:12]
            ],
            "degrade_count": len(env.get("degrade") or []),
            "controversy_count": len(env.get("controversy") or []),
        }
    )
    # digest 超限时退化为 index（保证仍"很小"）
    if len(json.dumps(view, ensure_ascii=False).encode("utf-8")) >= INDEX_VIEW_MAX:
        view.pop("payload_shapes", None)
        view.pop("list_sizes", None)
        view.pop("refs", None)
    return view


def get(artifact_id: str, view: str = "full") -> dict | None:
    """按视图读取产物；不存在返回 None。

    index / digest / section / full 四种视图，见 ``contracts/constants.json``。
    view="section" 时等价于 full 中的 payload（需用 ``get_section`` 取单节）。
    """
    if view not in _views():
        raise ShibanError(
            "bad_envelope",
            f"未知视图：{view!r}",
            f"合法值：{', '.join(_views())}",
        )
    path = _artifact_path(artifact_id)
    if not os.path.exists(path):
        return None
    env = _read_json(path)
    if not isinstance(env, dict):
        raise ShibanError("io", f"产物文件不是 JSON 对象：{path}", "")
    if view == "index":
        return _index_view(env)
    if view == "digest":
        return _digest_view(env)
    if view == "section":
        return {"id": env.get("id"), "payload": _digest_view(env).get("payload_keys", [])}
    return env


def _walk_section(payload, name: str):
    """解析 ``"S8"`` / ``"S8[2]"`` / ``"a.b[0].c"``，返回 (found, value)。"""
    if not isinstance(name, str) or not name.strip():
        return False, None
    node = payload
    for part in name.strip().split("."):
        part = part.strip()
        if not part:
            continue
        m = _SECTION_RE.match(part)
        if m is None:
            return False, None
        key = m.group(1).strip()
        idx = m.group(2)
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
        if idx is not None:
            if not isinstance(node, list):
                return False, None
            i = int(idx)
            if i < 0:
                i += len(node)
            if i < 0 or i >= len(node):
                return False, None
            node = node[i]
    return True, node


def get_section(artifact_id: str, name: str) -> dict | None:
    """取 payload 中的一节（如 ``"S8"``），支持 ``"S8[2]"`` 列表下标。

    返回 ``{"id", "rev", "name", "value"}``；不存在返回 None。
    """
    path = _artifact_path(artifact_id)
    if not os.path.exists(path):
        return None
    env = _read_json(path)
    found, value = _walk_section(env.get("payload") or {}, name)
    if not found:
        return None
    return {"id": env.get("id"), "rev": env.get("rev"), "name": name.strip(), "value": value}


def set_section(artifact_id: str, name: str, value) -> dict:
    """只替换 payload 的一个键（章节重做），其余内容原样保留，内部走 ``put()``。"""
    aid = _safe_id(artifact_id)
    path = _artifact_path(aid)
    if not os.path.exists(path):
        raise ShibanError("not_found", f"产物不存在：{aid}", "先 put() 建一个再改。")
    env = _read_json(path)
    payload = dict(env.get("payload") or {})
    m = _SECTION_RE.match(name or "")
    if not m:
        raise ShibanError("bad_name", f"非法节名：{name!r}", '形如 "S8" 或 "S8[2]"')
    key, idx = m.group(1), m.group(2)
    if idx is None:
        payload[key] = value
    else:
        if key not in payload or not isinstance(payload[key], list):
            raise ShibanError("bad_name", f"payload[{key!r}] 不是列表，无法按下标替换", "")
        lst = list(payload[key])
        i = int(idx)
        if i < 0:
            i += len(lst)
        if i < 0 or i >= len(lst):
            raise ShibanError("not_found", f"下标越界：{name}", f"当前长度 {len(lst)}")
        lst[i] = value
        payload[key] = lst
    env["payload"] = payload
    env["rev"] = int(env.get("rev") or 0)  # 让 put 以旧 rev 为基线递增
    res = put(env, expected_rev=int(env.get("rev") or 0))
    res["name"] = name.strip()
    return res


def list_artifacts(
    kind: str | None = None, scope: str | None = None, status: str | None = None
) -> list:
    """返回 index 视图列表，按 updated_at 倒序。"""
    layout = _layout()
    base = layout["artifacts"]
    if not os.path.isdir(base):
        return []
    kinds = [kind] if kind else _kinds()
    out = []
    for k in kinds:
        if k not in _kinds():
            raise ShibanError("bad_kind", f"未知产物类型：{kind!r}", f"合法值：{', '.join(_kinds())}")
        kdir = os.path.join(base, k)
        if not os.path.isdir(kdir):
            continue
        for fn in os.listdir(kdir):
            if not fn.endswith(".json") or fn.endswith(".tmp"):
                continue
            try:
                env = _read_json(os.path.join(kdir, fn))
            except (OSError, ValueError):
                continue
            if not isinstance(env, dict):
                continue
            if scope is not None and _subject_of(env).get("scope") != scope:
                continue
            if status is not None and env.get("status") != status:
                continue
            out.append(_index_view(env))
    out.sort(key=lambda v: (str(v.get("id", "")),), reverse=False)
    # updated_at 不在 index 视图里，用完整文件再排一次（不额外暴露给调用方）
    def _updated(view):
        try:
            return str(_read_json(_artifact_path(view["id"])).get("updated_at") or "")
        except (OSError, ValueError, ShibanError):
            return ""

    out.sort(key=_updated, reverse=True)
    return out


# --------------------------------------------------------------------------- #
# 状态
# --------------------------------------------------------------------------- #


def _require(aid: str) -> dict:
    path = _artifact_path(aid)
    if not os.path.exists(path):
        raise ShibanError("not_found", f"产物不存在：{aid}", "用 list_artifacts() 查现有 id。")
    env = _read_json(path)
    env["rev"] = int(env.get("rev") or 0)
    return env


def confirm(artifact_id: str, verdict: dict | None = None) -> dict:
    """把产物置为 confirmed；verdict 若有内容则记入 ``envelope.confirmation``。"""
    env = _require(artifact_id)
    env["status"] = "confirmed"
    if verdict:
        if not isinstance(verdict, dict):
            raise ShibanError("bad_envelope", "verdict 必须是对象", "")
        record = dict(verdict)
        record.setdefault("at", _now())
        history = list(env.get("confirmation_history") or [])
        history.append(record)
        env["confirmation"] = record
        env["confirmation_history"] = history
    return put(env, expected_rev=env["rev"])


def discard(artifact_id: str, reason: str = "") -> dict:
    """把产物置为 discarded（不删除文件，保留可追溯性）。"""
    env = _require(artifact_id)
    env["status"] = "discarded"
    if reason:
        env["discard_reason"] = str(reason)
    env["discarded_at"] = _now()
    return put(env, expected_rev=env["rev"])


def archive(artifact_id: str) -> dict:
    """置为 archived 并返回 index 视图（供调用方直接展示/写行）。"""
    env = _require(artifact_id)
    env["status"] = "archived"
    env["archived_at"] = _now()
    res = put(env, expected_rev=env["rev"])
    res["view"] = get(env["id"], "index")
    return res


def mark_stale(upstream_id: str) -> list:
    """沿 edges 向下遍历，把直接下游置 stale，返回受影响 id 列表。"""
    aid = _safe_id(upstream_id)
    conn = _db()
    try:
        rows = conn.execute(
            # 只有强边传播 stale：弱边（candidate=1，目标尚未落盘）没有下游可失效
            "SELECT DISTINCT e.dst FROM edges e JOIN nodes n ON n.id=e.dst "
            "WHERE e.src=? AND e.candidate=0",
            (aid,),
        ).fetchall()
    finally:
        conn.close()
    affected = []
    for (dst,) in rows:
        try:
            env = _require(dst)
        except (ShibanError, OSError, ValueError):
            continue
        if env.get("status") == "stale":
            affected.append(dst)
            continue
        # 教师已否决 / 已归档的产物不再随上游变化（归档是有意冻结的终态）
        if env.get("status") in ("discarded", "archived"):
            continue
        env["status"] = "stale"
        env["stale_since"] = _now()
        env["stale_by"] = aid
        put(env, expected_rev=env["rev"])
        affected.append(dst)
    return affected


# --------------------------------------------------------------------------- #
# 图
# --------------------------------------------------------------------------- #


def graph_neighbors(artifact_id: str, direction: str = "out") -> list:
    """查邻居。direction: out（出边）/ in（入边）/ both。

    每条：``{id, role, candidate, direction, kind, status, rev, topic, title, updated_at}``
    （弱边目标可能尚未落盘，此时 kind/status 等为 None）。
    """
    aid = _safe_id(artifact_id)
    if direction not in ("out", "in", "both"):
        raise ShibanError("bad_envelope", f"direction 非法：{direction!r}", "out | in | both")
    conn = _db()
    try:
        out = []
        if direction in ("out", "both"):
            for dst, role, cand in conn.execute(
                "SELECT dst, role, candidate FROM edges WHERE src=? ORDER BY dst, role", (aid,)
            ):
                out.append(_neighbor_row(conn, dst, role, cand, "out"))
        if direction in ("in", "both"):
            for src, role, cand in conn.execute(
                "SELECT src, role, candidate FROM edges WHERE dst=? ORDER BY src, role", (aid,)
            ):
                out.append(_neighbor_row(conn, src, role, cand, "in"))
    finally:
        conn.close()
    return out


def _neighbor_row(conn, other: str, role: str, cand, direction: str) -> dict:
    row = conn.execute(
        "SELECT kind, status, rev, topic, title, updated_at FROM nodes WHERE id=?", (other,)
    ).fetchone()
    return {
        "id": other,
        "role": role,
        "candidate": bool(cand),
        "direction": direction,
        "kind": row[0] if row else None,
        "status": row[1] if row else None,
        "rev": row[2] if row else None,
        "topic": row[3] if row else None,
        "title": row[4] if row else None,
        "updated_at": row[5] if row else None,
    }


def graph_query(sql_params: dict | None = None) -> dict:
    """图统计 ``{nodes, edges, by_kind, by_status}``。

    sql_params 可选过滤：``{"kind": "les", "status": "confirmed", "scope": "c1"}``。
    """
    params = sql_params or {}
    if not isinstance(params, dict):
        raise ShibanError("bad_envelope", "sql_params 必须是 dict 或 None", "")
    where, args = [], []
    for key in ("kind", "status", "scope"):
        if params.get(key) is not None:
            where.append(f"{key}=?")
            args.append(params[key])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = _db()
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM nodes{clause}", args).fetchone()[0]  # noqa: S608
        by_kind = {
            k: c
            for k, c in conn.execute(
                f"SELECT kind, COUNT(*) FROM nodes{clause} GROUP BY kind ORDER BY kind", args
            )
        }
        by_status = {
            s: c
            for s, c in conn.execute(
                f"SELECT status, COUNT(*) FROM nodes{clause} GROUP BY status ORDER BY status", args
            )
        }
        # 边统计限定在过滤后的节点集合内
        if where:
            scope_sql = f"SELECT id FROM nodes{clause}"
            m = conn.execute(
                f"SELECT COUNT(*) FROM edges WHERE src IN ({scope_sql})", args
            ).fetchone()[0]
        else:
            m = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    finally:
        conn.close()
    return {"nodes": n, "edges": m, "by_kind": by_kind, "by_status": by_status}


def rebuild_graph() -> dict:
    """从 artifacts 真源重建 graph.db（nodes + edges）。返回 ``{nodes, edges}``。"""
    layout = ensure_layout()
    base = layout["artifacts"]
    envs = []
    for k in _kinds():
        kdir = os.path.join(base, k)
        if not os.path.isdir(kdir):
            continue
        for fn in sorted(os.listdir(kdir)):
            if fn.endswith(".json") and not fn.endswith(".tmp"):
                try:
                    env = _read_json(os.path.join(kdir, fn))
                except (OSError, ValueError):
                    continue
                if isinstance(env, dict) and env.get("id"):
                    envs.append(env)
    conn = _db()
    try:
        with _tx(conn):
            conn.execute("DELETE FROM edges")
            conn.execute("DELETE FROM nodes")
            for env in envs:
                _upsert_node(conn, env)
            for env in envs:
                _rebuild_edges(conn, env["id"], _norm_refs(env.get("refs")))
            n = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            m = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    finally:
        conn.close()
    return {"nodes": n, "edges": m}


# --------------------------------------------------------------------------- #
# 证据（L0，只追加）
# --------------------------------------------------------------------------- #


def _evidence_path(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ShibanError("bad_name", f"非法证据名：{name!r}", "")
    nm = name.strip()
    if (
        nm in (".", "..")
        or ".." in nm
        or "/" in nm
        or "\\" in nm
        or not _EVIDENCE_NAME_RE.fullmatch(nm)
    ):
        raise ShibanError(
            "unsafe_path",
            f"证据名含路径成分或非法字符：{name!r}",
            "允许：字母数字下划线、中文、点、连字符；不得含 / \\ ..",
        )
    return os.path.join(_layout()["evidence"], nm)


def save_evidence(name: str, text: str) -> dict:
    """只追加地保存一段证据文本；同名已存在则拒绝。返回 ``{name, path, bytes, sha256}``。"""
    if not isinstance(text, str):
        raise ShibanError("bad_payload", "text 必须是字符串", "")
    layout = ensure_layout()
    path = _evidence_path(name)
    if os.path.exists(path):
        raise ShibanError(
            "exists",
            f"证据已存在：{name}",
            "证据只追加不改写；如需新版本请换名（如加日期后缀）。",
        )
    data = text.encode("utf-8")
    meta = {
        "name": os.path.basename(path),
        "path": path,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "created_at": _now(),
    }
    tmp = path + ".tmp"
    try:
        # 用独占创建防止并发覆盖
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(fd, "wb", closefd=True) as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise
    except FileExistsError as exc:
        raise ShibanError("exists", f"证据写入冲突：{name}", "请稍后重试或换名。") from exc
    # 旁挂 metadata（不参与 read_evidence 的正文）
    with contextlib.suppress(OSError, ShibanError):
        meta_path = os.path.join(layout["indexes"], "evidence.jsonl")
        os.makedirs(os.path.dirname(meta_path), exist_ok=True)
        line = json.dumps({k: meta[k] for k in ("name", "bytes", "sha256", "created_at")},
                          ensure_ascii=False)
        with open(meta_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return meta


def list_evidence() -> list:
    """列出证据文件：``[{name, bytes, sha256, created_at}]``，按名称排序。"""
    layout = ensure_layout()
    base = layout["evidence"]
    out = []
    if not os.path.isdir(base):
        return out
    for fn in sorted(os.listdir(base)):
        p = os.path.join(base, fn)
        if not os.path.isfile(p) or fn.endswith(".tmp"):
            continue
        with open(p, "rb") as fh:
            data = fh.read()
        st = os.stat(p)
        out.append(
            {
                "name": fn,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    return out


def read_evidence(name: str) -> dict:
    """读取证据全文：``{name, path, bytes, sha256, text}``。"""
    path = _evidence_path(name)
    if not os.path.isfile(path):
        raise ShibanError("not_found", f"证据不存在：{name}", "用 list_evidence() 查看现有证据。")
    with open(path, "rb") as fh:
        data = fh.read()
    return {
        "name": os.path.basename(path),
        "path": path,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "text": data.decode("utf-8", errors="replace"),
    }


# --------------------------------------------------------------------------- #
# 索引（L2，程序生成）
# --------------------------------------------------------------------------- #


def rebuild_indexes() -> dict:
    """扫 artifacts 下所有 json，生成 ``data/indexes/<kind>.jsonl``，返回各 kind 行数。

    原子替换：先写 ``<kind>.jsonl.tmp`` 再 rename；本 kind 无产物也会写出空文件，
    这样"空"与"没跑过"可区分。
    """
    layout = ensure_layout()
    base = layout["artifacts"]
    idx = layout["indexes"]
    os.makedirs(idx, exist_ok=True)
    by_kind = {k: [] for k in _kinds()}
    for k in _kinds():
        kdir = os.path.join(base, k)
        if not os.path.isdir(kdir):
            continue
        for fn in os.listdir(kdir):
            if not fn.endswith(".json") or fn.endswith(".tmp"):
                continue
            try:
                env = _read_json(os.path.join(kdir, fn))
            except (OSError, ValueError):
                continue
            if not isinstance(env, dict):
                continue
            by_kind[k].append(env)

    counts = {}
    for k, envs in by_kind.items():
        envs.sort(key=lambda e: str(e.get("updated_at") or ""), reverse=True)
        lines = [
            json.dumps(_index_view(e), ensure_ascii=False, sort_keys=True) for e in envs
        ]
        body = "\n".join(lines) + ("\n" if lines else "")
        _atomic_write_text(os.path.join(idx, k + ".jsonl"), body)
        counts[k] = len(lines)
    return counts


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

_SAMPLE = {
    "kind": "les",
    "status": "in_progress",
    "producer": {"atom": "lesson-plan", "skills_loaded": ["lesson-plan"]},
    "subject_line": {"scope": "c1", "topic": "DNA的复制", "date": "2026-11-02", "kp": ["DNA半保留复制"]},
    "refs": [{"role": "plan", "id": "lp-c1-dna-0000"}, {"role": "asset", "id": "asset-c1-demo-0000"}],
    "citations": [{"corpus_id": "bx2", "book_page": 55, "pdf_page": 64, "quote": "半保留复制",
                   "section": "S1.textbook"}],
    "degrade": [],
    "controversy": [{"section": "S4.objectives[2]", "issue": "弥散复制是否作考试要求",
                     "my_view": "作为思维工具", "teacher": "pending"}],
    "payload": {
        "title": "DNA的复制",
        "S1": {"textbook": "人教版必修2 第3章第3节", "pages": "P.53—56"},
        "S4": {"objectives": ["说出半保留复制", "用模型解释复制过程", "比较三种假说"]},
        "S8": [
            {"no": "一", "name": "情境导入", "minutes": 3},
            {"no": "二", "name": "假说提出", "minutes": 12},
            {"no": "三", "name": "模型建构", "minutes": 20},
        ],
    },
}


def _selfcheck() -> int:
    """最小自检：put → get → list → confirm → set_section → rebuild_indexes。"""
    tmp = tempfile.mkdtemp(prefix="shiban-core-selfcheck-")
    os.environ["SHIBAN_ROOT"] = tmp
    try:
        layout = ensure_layout()
        for key, path in layout.items():
            if key != "graph_db":
                assert os.path.isdir(path), f"缺少目录 {key}: {path}"

        res = put(_SAMPLE)
        aid = res["id"]
        assert aid.startswith("les-c1-"), aid
        assert res["rev"] == 1 and os.path.isfile(res["path"]), res

        idx = get(aid, "index")
        assert idx and idx["id"] == aid and idx["status"] == "in_progress", idx
        assert len(json.dumps(idx, ensure_ascii=False).encode("utf-8")) < 2048, "index 视图过大"

        dg = get(aid, "digest")
        assert dg and dg["list_sizes"]["S8"] == 3, dg
        assert len(json.dumps(dg, ensure_ascii=False).encode("utf-8")) < 2048, "digest 视图过大"

        sec = get_section(aid, "S8[1]")
        assert sec and sec["value"]["name"] == "假说提出", sec

        # probe：弱边（目标未落盘）应为 candidate=True
        nb = graph_neighbors(aid, "out")
        assert {n["id"] for n in nb} >= {"lp-c1-dna-0000"}, nb
        assert all(n["candidate"] for n in nb if n["id"].startswith("lp-")), nb

        # rev 冲突必须报错
        try:
            put(_SAMPLE, expected_rev=99)
            raise AssertionError("expected ShibanError(rev_conflict)")
        except ShibanError as exc:
            assert exc.code == "rev_conflict", exc

        sec_res = set_section(aid, "S8[1]", {"no": "二", "name": "假说—演绎推进", "minutes": 12})
        assert sec_res["rev"] == 2, sec_res
        assert get_section(aid, "S8[1]")["value"]["name"] == "假说—演绎推进"
        assert get_section(aid, "S1")["value"]["textbook"].endswith("第3节")

        lst = list_artifacts()
        assert isinstance(lst, list) and any(x["id"] == aid for x in lst), (lst, aid)

        conf = confirm(aid, {"by": "teacher", "note": "可用"})
        assert conf["status"] == "confirmed", conf
        assert get(aid, "index")["status"] == "confirmed"

        cnt = rebuild_indexes()
        assert cnt.get("les", 0) >= 1, cnt
        jl = os.path.join(layout["indexes"], "les.jsonl")
        with open(jl, "r", encoding="utf-8") as fh:
            assert len([ln for ln in fh if ln.strip()]) == cnt["les"]

        ev = save_evidence("课标摘录-2026.txt", "概念3：遗传信息控制生物性状……\n")
        assert ev["bytes"] > 0 and read_evidence("课标摘录-2026.txt")["text"].startswith("概念3"), (ev,)
        try:
            save_evidence("课标摘录-2026.txt", "改写")
            raise AssertionError("evidence 应只追加")
        except ShibanError as exc:
            assert exc.code == "exists", exc

        gq = graph_query()
        assert gq["nodes"] == 1 and gq["by_kind"] == {"les": 1}, gq

        # 环检测：先建上游再让它引用下游
        up = put({"kind": "lp", "subject_line": {"scope": "c1", "topic": "DNA的复制"},
                  "payload": {"title": "DNA的复制"}})
        down = put({"kind": "les", "subject_line": {"scope": "c1", "topic": "DNA的复制"},
                    "payload": {"title": "DNA的复制"}, "refs": [{"role": "plan", "id": up["id"]}]})
        try:
            put({"kind": "lp", "id": up["id"], "subject_line": {"scope": "c1", "topic": "DNA的复制"},
                 "payload": {"title": "DNA的复制"},
                 "refs": [{"role": "lesson", "id": down["id"]}]}, expected_rev=1)
            raise AssertionError("expected ShibanError(cycle)")
        except ShibanError as exc:
            assert exc.code == "cycle", exc
        assert get(up["id"], "index")["rev"] == 1, "环检测失败后必须回滚"

        # 语义：down 引用 up，所以 up 变化时失效的是 down。
        assert mark_stale(up["id"]) == [], "up 无下游，不应传播"
        stale = mark_stale(down["id"])
        assert stale == [up["id"]], stale
        assert get(up["id"], "index")["status"] == "stale"
        assert discard(aid, "不需要")["status"] == "discarded"
        assert archive(aid)["status"] == "archived"

        print("OK")
        return 0
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(_selfcheck())


# --------------------------------------------------------------------------- #
# 提问日志：记录"暂存 / 强制暂停 / 回答"，保证引导过程可追溯
# --------------------------------------------------------------------------- #
# DSH 只回传最终文本，指挥是否真的按协议提问无法从会话外验证；
# 因此每一次 B 档暂存、C 档强制暂停、以及答案回写，都落一条 JSONL。
# 位置：$SHIBAN_ROOT/data/ask/log.jsonl（追加，不覆盖）

def ask_log_path() -> str:
    layout = _layout()
    return os.path.join(layout["data"], "ask", "log.jsonl")


def log_ask(event: str, payload: dict) -> dict:
    """追加一条提问日志。

    event 取值：
      queue      —— B 档：问题进待答队列（继续推进）
      pause      —— C 档：待答数达到阈值，强制暂停并要求全部回答
      answer     —— 教师回答（可一次多条）
      unblock    —— 问题被移除（已回答 / 教师撤回 / 不再相关）
      over_budget—— 提问轮次超过 max_rounds，被迫出成品
    """
    allowed = {"queue", "pause", "answer", "unblock", "over_budget"}
    if event not in allowed:
        raise ShibanError("bad_args", f"未知提问事件：{event!r}",
                          f"允许：{', '.join(sorted(allowed))}")
    path = ask_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = {"at": _now(), "event": event, **payload}
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return {"ok": True, "logged": event, "path": path}


def read_ask_log(limit: int = 200) -> list:
    path = ask_log_path()
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows[-limit:]


def ask_stats() -> dict:
    """统计每类事件次数、暂停轮次、平均待答数——用于复盘"是否真的在引导"。"""
    rows = read_ask_log(limit=10_000)
    counts: dict = {}
    pauses = []
    pending_at_pause = []
    answered_after_pause = 0
    for r in rows:
        counts[r.get("event", "?")] = counts.get(r.get("event", "?"), 0) + 1
        if r.get("event") == "pause":
            pauses.append(r.get("at"))
            if isinstance(r.get("pending"), int):
                pending_at_pause.append(r["pending"])
        if r.get("event") == "answer":
            answered_after_pause += len(r.get("answers") or [])
    return {
        "events": counts,
        "pauses": len(pauses),
        "last_pause_at": pauses[-1] if pauses else None,
        "avg_pending_at_pause": (round(sum(pending_at_pause) / len(pending_at_pause), 2)
                                 if pending_at_pause else None),
        "answers_recorded": answered_after_pause,
        "log": ask_log_path(),
    }
