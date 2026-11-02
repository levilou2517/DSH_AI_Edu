#!/usr/bin/env python3
"""shiban_migrate — 版本间迁移**积累的素材**。

## 何时执行

**只在部署时、且必须显式调用**（`shiban-store migrate`）。
开发阶段保持空包——不自动触发、不隐式导入任何数据。

## 迁移什么（只迁"积累的东西"）

| 迁移 | 不迁移 |
|---|---|
| `corpus/` 教材、课标、论文 | 代码、技能、模板 |
| `data/assets/` 素材库 | 配置、日志 |
| `theory/derived/` 教师补充文献 | 临时文件 |
| `data/evidence/` 原始证据 | `*.tmp`、`__pycache__` |
| `data/artifacts/` 教案等产物 | |
| `data/graph.db` 引用图 | |

## 规则

* **不覆盖**：目标已存在的同名文件跳过并记录，由用户决定。
* **先干跑**：默认 `dry_run=True`，只报计划不动手。
* **留清单**：执行后写 `MIGRATION.json`（源、目标、时间、逐项结果），可追溯。
* **可重复**：已迁移过的不会重复拷（按内容哈希判重）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import shiban_core as core
from shiban_core import ShibanError

# 需要继承的"积累物"：相对数据根的路径
CARRY = (
    "corpus",
    "data/assets",
    "theory/derived",
    "data/evidence",
    "data/artifacts",
    "data/graph.db",
    "data/indexes",
)

SKIP_SUFFIX = (".tmp", ".pyc", ".log")
SKIP_DIRS = {"__pycache__", "logs"}


# v0.5.0 是版本化数据根的第一版；更早的版本（v0.4.x 及以前）的素材不迁移。
MIN_VERSION = (0, 5, 0)


def _parse_version(slug: str) -> tuple:
    """v0_5_0 → (0,5,0)；解析不出返回空元组。"""
    m = re.fullmatch(r"v(\d+)_(\d+)_(\d+)", slug or "")
    return tuple(int(x) for x in m.groups()) if m else ()


def discover_sources() -> list[dict]:
    """找出**本版本之前、且 ≥ v0.5.0** 的数据根，供迁移选择。

    只认版本化布局：<legacy>/versions/vX_Y_Z/。
    v0.4.x 及更早的扁平布局（<legacy>/data、<legacy>/corpus）**不在迁移范围**，
    如需从旧版取素材，请用 --from 显式指定路径。
    """
    base = Path(core.legacy_root())
    current = Path(core.root()).resolve()
    found: list[dict] = []

    def carry_count(p: Path) -> int:
        n = 0
        for rel in CARRY:
            t = p / rel
            if t.is_file():
                n += 1
            elif t.is_dir():
                n += sum(1 for _ in t.rglob("*") if _.is_file())
        return n

    vers = base / "versions"
    if vers.is_dir():
        for d in sorted(vers.iterdir()):
            if not d.is_dir() or d.resolve() == current:
                continue
            ver = _parse_version(d.name)
            if not ver:
                continue
            if ver < MIN_VERSION:
                # 低于 v0.5.0 的不迁移；列出来但标不可迁，避免误以为找不到
                found.append({"path": str(d), "layout": "versions",
                              "version": d.name, "files": carry_count(d),
                              "migratable": False,
                              "why": "v0.5.0 之前的素材不迁移"})
                continue
            found.append({"path": str(d), "layout": "versions", "version": d.name,
                          "files": carry_count(d), "migratable": True})

    # 扁平旧布局属于 v0.4.x 时代，不自动识别
    if (base / "data").is_dir() or (base / "corpus").is_dir():
        if base.resolve() != current:
            found.append({"path": str(base), "layout": "flat", "version": "legacy",
                          "files": carry_count(base), "migratable": False,
                          "why": "v0.5.0 之前的素材不迁移；确有需要请用 --from 显式指定"})

    found.sort(key=lambda x: (x.get("migratable", False), x["version"]), reverse=True)
    return found


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(rel: str, src: Path, dst: Path, plan: list) -> None:
    s = src / rel
    if not s.exists():
        return
    if s.is_file():
        plan.append({"rel": rel, "kind": "file", "bytes": s.stat().st_size})
        return
    for root, dirs, files in os.walk(s):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(SKIP_SUFFIX):
                continue
            f = Path(root) / name
            plan.append({"rel": str(f.relative_to(src)), "kind": "file",
                         "bytes": f.stat().st_size})


def plan_migration(source: str) -> dict:
    """列出将要迁移的条目，不落盘。"""
    src = Path(source).expanduser().resolve()
    if not src.is_dir():
        raise ShibanError("not_found", f"源数据根不存在：{src}")
    dst = Path(core.root()).resolve()
    if src == dst:
        raise ShibanError("same_root", "源与目标相同，无需迁移")

    items: list = []
    for rel in CARRY:
        _walk(rel, src, dst, items)

    will_copy, will_skip = [], []
    for it in items:
        target = dst / it["rel"]
        source_file = src / it["rel"]
        entry = dict(it, from_=str(source_file), to=str(target))
        if target.exists():
            same = (target.is_file() and source_file.is_file()
                    and _sha(target) == _sha(source_file))
            entry["reason"] = "内容相同" if same else "目标已存在"
            will_skip.append(entry)
        else:
            will_copy.append(entry)

    return {
        "source": str(src), "target": str(dst),
        "found": len(items), "copy": len(will_copy), "skip": len(will_skip),
        "copy_bytes": sum(i["bytes"] for i in will_copy),
        "by_area": _by_area(items),
        "items_copy": will_copy, "items_skip": will_skip,
    }


def _by_area(items: list) -> dict:
    out: dict = {}
    for it in items:
        area = it["rel"].split("/")[0] if "/" in it["rel"] else it["rel"]
        if area == "data" and it["rel"].count("/") >= 1:
            area = "data/" + it["rel"].split("/")[1]
        out[area] = out.get(area, 0) + 1
    return out


def run_migration(source: str, dry_run: bool = True, force: bool = False) -> dict:
    """执行迁移。force=True 时覆盖目标已存在的文件（默认不覆盖）。"""
    report = plan_migration(source)
    if dry_run:
        return {"ok": True, "dry_run": True, **{k: report[k] for k in
                ("source", "target", "found", "copy", "skip", "copy_bytes", "by_area")},
                "items_copy": report["items_copy"][:50],
                "hint": "确认无误后加 --yes 执行"}

    dst = Path(report["target"])
    copied, skipped = [], []
    for it in report["items_copy"]:
        target = Path(it["to"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(it["from_"], target)
        copied.append({"rel": it["rel"], "bytes": it["bytes"]})
    for it in report["items_skip"]:
        src_file = Path(report["source"]) / it["rel"]
        if force and it.get("reason") != "内容相同":
            target = Path(it["to"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, target)
            copied.append({"rel": it["rel"], "bytes": it["bytes"], "overwritten": True})
        else:
            skipped.append({"rel": it["rel"], "reason": it.get("reason")})

    manifest = {
        "schema": "shiban.migration/1",
        "at": core._now(),
        "source": report["source"], "target": report["target"],
        "package_version": core.package_meta()["version"],
        "copied": len(copied), "skipped": len(skipped),
        "items": copied, "skipped_items": skipped,
    }
    path = dst / "MIGRATION.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 素材与产物迁入后重建索引与图
    try:
        core.rebuild_indexes()
        core.rebuild_graph()
    except Exception:  # noqa: BLE001 —— 重建失败不影响迁移本身
        pass

    return {"ok": True, "dry_run": False, "copied": len(copied),
            "skipped": len(skipped), "manifest": str(path),
            "hint": "核对 MIGRATION.json；要覆盖同名文件请加 --force"}
