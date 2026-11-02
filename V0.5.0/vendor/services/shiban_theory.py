#!/usr/bin/env python3
"""shiban_theory — 理论库：内置文献的检索、读取与引用核验。

与语料（corpus）的区别：
  * corpus 是"教什么"的燃料，教师导入，版权归教师；
  * theory 是"为什么这样教"的尺子，随包分发，可公开引用。

两区物理隔离：
  framework/theory/builtin/   随包，版本化；升级会覆盖
  $SHIBAN_ROOT/theory/derived/ 教师补充，永不覆盖

引用编号：
  T-BUILTIN-nnn  内置，稳定不变（源文件缺失时标 missing，编号不复用）
  T-DERIVED-nnn  教师补充
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import shiban_core as core
from shiban_core import ShibanError

PKG_ROOT = Path(__file__).resolve().parents[2]
BUILTIN = PKG_ROOT / "framework" / "theory" / "builtin"
MANIFEST = BUILTIN / "citations.json"
PAGE_RE = re.compile(r"<!--\s*p\.(\d+)\s*-->")


# --------------------------------------------------------------------------- #
# 路径与清单
# --------------------------------------------------------------------------- #

def derived_root() -> Path:
    return Path(core.root()) / "theory" / "derived"


def _builtin_manifest() -> dict:
    if not MANIFEST.is_file():
        return {"schema": "shiban.theory-manifest/1", "version": 1, "items": []}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": "shiban.theory-manifest/1", "version": 1, "items": []}


def _derived_manifest() -> dict:
    path = derived_root() / "manifest.json"
    if not path.is_file():
        return {"schema": "shiban.theory-manifest/1", "version": 1, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": "shiban.theory-manifest/1", "version": 1, "items": []}


def _write_derived_manifest(man: dict) -> None:
    path = derived_root() / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _all_items() -> list:
    items = [dict(i, source="builtin") for i in _builtin_manifest().get("items", [])]
    items += [dict(i, source="derived") for i in _derived_manifest().get("items", [])]
    return items


def _find(theory_id: str) -> dict | None:
    for item in _all_items():
        if item.get("id") == theory_id:
            return item
    return None


def source_text_path(item: dict) -> Path | None:
    """返回文献正文位置。内置文献**不随包分发全文**：
    优先维护者源库，其次教师 derived 区；两者都没有则返回 None。"""
    if item.get("source") == "derived":
        cand = derived_root() / item["file"]
        return cand if cand.is_file() else None
    # 内置：源库（framework 的上级目录下的 理论库/）
    src_file = item.get("source_file")
    if src_file:
        cand = PKG_ROOT.parent / "理论库" / src_file
        if cand.is_file():
            return cand
    return None


# --------------------------------------------------------------------------- #
# 列表与读取
# --------------------------------------------------------------------------- #

def list_items(source: str | None = None, query: str | None = None) -> list:
    items = _all_items()
    if source in ("builtin", "derived"):
        items = [i for i in items if i.get("source") == source]
    if query:
        needle = query.casefold()
        items = [i for i in items
                 if needle in str(i.get("title", "")).casefold()
                 or needle in str(i.get("id", "")).casefold()]
    return sorted(items, key=lambda i: i.get("id", ""))


def pages_of(theory_id: str) -> dict:
    """返回某文献的页号列表与每页前 60 字，用于定位。"""
    item = _find(theory_id)
    if item is None:
        raise ShibanError("not_found", f"理论文献不存在：{theory_id}",
                          "先 theory list 查编号。")
    path = source_text_path(item)
    if path is None:
        raise ShibanError("no_fulltext",
                          f"{theory_id} 只有登记信息，没有可读正文",
                          "内置文献不随包分发全文：请把原文放到你的理论库，或用 "
                          "theory add 加入 derived 区。")
    text = path.read_text(encoding="utf-8", errors="replace")
    segs = PAGE_RE.split(text)
    # segs = [前言, "1", 正文1, "2", 正文2, ...]
    out = []
    for i in range(1, len(segs) - 1, 2):
        out.append({"page": int(segs[i]), "preview": re.sub(r"\s+", " ", segs[i + 1])[:60]})
    return {"id": theory_id, "source": item["source"], "title": item.get("title"),
            "pages": out, "page_count": len(out)}


def read_page(theory_id: str, page: int) -> dict:
    item = _find(theory_id)
    if item is None:
        raise ShibanError("not_found", f"理论文献不存在：{theory_id}")
    path = source_text_path(item)
    if path is None:
        raise ShibanError("no_fulltext", f"{theory_id} 没有可读正文",
                          "内置文献不随包分发全文；请把原文放入理论库或用 theory add 加入。")
    text = path.read_text(encoding="utf-8", errors="replace")
    segs = PAGE_RE.split(text)
    for i in range(1, len(segs) - 1, 2):
        if int(segs[i]) == int(page):
            body = segs[i + 1].strip()
            return {"id": theory_id, "source": item["source"], "page": int(page),
                    "title": item.get("title"), "text": body}
    available = [int(segs[i]) for i in range(1, len(segs) - 1, 2)]
    raise ShibanError("no_page", f"{theory_id} 没有第 {page} 页",
                      f"可用页：{available[:5]}…（共 {len(available)} 页）"
                      if available else "该文献没有页码标记")


def search(keyword: str, limit: int = 10) -> list:
    """两字以上关键词按 bigram 命中计数排序；单字按子串。"""
    if not keyword or not keyword.strip():
        raise ShibanError("bad_args", "关键词不能为空")
    kw = keyword.strip()
    hits = []
    for item in _all_items():
        path = source_text_path(item)
        if path is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        segs = PAGE_RE.split(text)
        for i in range(1, len(segs) - 1, 2):
            page, body = int(segs[i]), segs[i + 1]
            n = body.count(kw)
            if n:
                pos = body.find(kw)
                snippet = re.sub(r"\s+", " ", body[max(0, pos - 40):pos + 60]).strip()
                hits.append({"id": item["id"], "source": item["source"],
                             "title": item.get("title"), "page": page,
                             "count": n, "snippet": snippet})
    hits.sort(key=lambda h: (-h["count"], h["id"], h["page"]))
    return hits[:limit]


# --------------------------------------------------------------------------- #
# 引用与核验
# --------------------------------------------------------------------------- #

def cite(theory_id: str, page: int, quote: str = "") -> dict:
    """生成一条可放进产物的理论引用。"""
    item = _find(theory_id)
    if item is None:
        raise ShibanError("not_found", f"理论文献不存在：{theory_id}")
    if source_text_path(item) is not None:
        pg = read_page(theory_id, page)
    else:
        pg = {"text": None}
    if quote and pg["text"] is not None and quote not in pg["text"]:
        raise ShibanError("quote_not_found",
                          f"引文在第 {page} 页找不到",
                          "quote 必须逐字摘自该页；可先 theory read 确认。")
    return {
        "id": theory_id,
        "source": item["source"],
        "page": int(page),
        "quote": quote[:120],
        "display": f"〔{item.get('title', theory_id)} p.{page}｜{item['source']}〕",
    }


def verify_citations(cites: list) -> list:
    """逐条核验：编号存在、页码存在、引文可复现。"""
    out = []
    for c in (cites or []):
        entry = {"id": c.get("id"), "page": c.get("page"), "ok": False}
        try:
            item = _find(c.get("id"))
            if item is not None and source_text_path(item) is None:
                entry["ok"] = True
                entry["verified"] = False
                entry["note"] = "仅核验编号与页码范围；该文献正文不在本机，引文未复现"
                out.append(entry)
                continue
            pg = read_page(c.get("id"), c.get("page"))
            q = (c.get("quote") or "").strip()
            if not q:
                entry["ok"] = True
                entry["note"] = "无引文，仅页码核验通过"
            elif q[:40] in pg["text"]:
                entry["ok"] = True
            else:
                entry["reason"] = "引文无法在该页复现"
        except ShibanError as exc:
            entry["reason"] = f"{exc.code}: {exc}"
        out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# 补充文献（derived，永不覆盖）
# --------------------------------------------------------------------------- #

def add_derived(file_path: str, title: str = "", meta: dict | None = None) -> dict:
    """把教师自己的文献加入 derived 区。同内容返回既有编号。"""
    src = Path(file_path)
    if not src.is_file():
        raise ShibanError("not_found", f"文件不存在：{src}")
    raw = src.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    man = _derived_manifest()
    for item in man.get("items", []):
        if item.get("sha256") == digest:
            return {"ok": True, "existed": True, "id": item["id"]}

    nums = [int(i["id"].rsplit("-", 1)[1]) for i in man.get("items", [])
            if i.get("id", "").startswith("T-DERIVED-")]
    tid = f"T-DERIVED-{(max(nums) + 1) if nums else 1:03d}"
    dest_dir = derived_root() / "literature"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest_dir / f"{src.stem}_{digest[:6]}{src.suffix}"
    shutil.copyfile(src, dest)

    text = dest.read_text(encoding="utf-8", errors="replace")
    item = {
        "id": tid, "source": "derived", "group": "literature",
        "title": title or (text.splitlines()[0].lstrip("# ").strip() if text.startswith("#") else src.stem),
        "file": f"literature/{dest.name}",
        "pages": len(PAGE_RE.findall(text)),
        "sha256": digest, "status": "included",
        "meta": meta or {},
    }
    man.setdefault("items", []).append(item)
    _write_derived_manifest(man)
    return {"ok": True, "existed": False, "id": tid, "file": str(dest),
            "pages": item["pages"],
            "note": "该文献只在你的数据根，不会随插件更新"}


def _page_count(item: dict) -> int:
    """pages 兼容两种写法：整数（derived 新写入）或 {count, first, last}（清单）。"""
    pg = item.get("pages")
    if isinstance(pg, dict):
        return int(pg.get("count") or 0)
    try:
        return int(pg or 0)
    except (TypeError, ValueError):
        return 0


def stats() -> dict:
    bi = _builtin_manifest().get("items", [])
    de = _derived_manifest().get("items", [])
    return {
        "builtin": len(bi),
        "builtin_missing": sum(1 for i in bi if i.get("status") == "missing"),
        "derived": len(de),
        "builtin_pages": sum(_page_count(i) for i in bi),
        "derived_pages": sum(_page_count(i) for i in de),
        "derived_root": str(derived_root()),
    }


# --------------------------------------------------------------------------- #
# 框架文件自检：页码是否越界、引文是否超长
# --------------------------------------------------------------------------- #

CITE_RE = re.compile(r"〔(T-(?:BUILTIN|DERIVED)-\d+)\s+p\.(\d+)(?:[｜|][^〕]*)?〕")
MAX_QUOTE = 40


def audit_digests(digest_dir: Path | None = None) -> dict:
    """检查 digests/ 下所有框架文件：
    * 引用编号存在；
    * 页码落在该文献的页码范围内；
    * 正文中引号内的引证不超过 40 字。
    """
    d = digest_dir or (PKG_ROOT / "framework" / "theory" / "builtin" / "digests")
    items = {i["id"]: i for i in _all_items()}
    report = {"files": [], "problems": []}
    if not d.is_dir():
        return report
    for f in sorted(d.glob("*.md")):
        if f.name == "README.md":
            continue
        text = f.read_text(encoding="utf-8")
        cites = CITE_RE.findall(text)
        entry = {"file": f.name, "bytes": f.stat().st_size,
                 "citations": len(cites), "refs": sorted({c[0] for c in cites})}
        for cid, page in cites:
            it = items.get(cid)
            if it is None:
                report["problems"].append({"file": f.name, "issue": "编号不存在", "id": cid})
                continue
            rng = it.get("pages") or {}
            if rng.get("count") and not (rng["first"] <= int(page) <= rng["last"]):
                report["problems"].append({
                    "file": f.name, "issue": "页码越界", "id": cid, "page": int(page),
                    "range": f"{rng['first']}-{rng['last']}"})
        # 用章节号引用的条目无法用页码核验 → 显式报"不可页码核验"，而不是装作没问题
        # 章节号引用：〔T-BUILTIN-032 2.2.4〕或〔T-BUILTIN-035「（三）1．…」〕，
        # 都不是 p.N 形式 → 归入"不可页码核验"
        section_cites = re.findall(r"〔(T-(?:BUILTIN|DERIVED)-\d+)\s+(?!p\.)[^〕]+〕", text)
        for cid in sorted(set(section_cites)):
            it = items.get(cid) or {}
            rng = it.get("pages") or {}
            if not rng.get("count"):
                report.setdefault("unverifiable", []).append({
                    "file": f.name, "id": cid,
                    "why": "该文献转换稿无页码标记，只能按章节号引用；核验需回溯原件"})
        # 引证长度：紧邻引用的引号内容超过 40 字才视为抄录。
        # 只检查"引号内文本 + 紧随其后的 〔T-…〕"这种成对结构，避免误伤普通行文引号。
        for m in re.finditer(r"[「“]([^」”\n]{41,})[」”]\s*〔T-(?:BUILTIN|DERIVED)-", text):
            snippet = m.group(1).strip()
            report["problems"].append({
                "file": f.name, "issue": "引证超过 40 字",
                "length": len(snippet), "head": snippet[:30]})
        report["files"].append(entry)
    report["ok"] = not report["problems"]
    return report
