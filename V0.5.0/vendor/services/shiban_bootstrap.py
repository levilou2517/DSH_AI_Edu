#!/usr/bin/env python3
"""shiban_bootstrap — 工作区首次使用时的一次性准备。

## 流程（两段式，绝不擅自触碰工作区外的东西）

1. **扫描（只读）**：在本工作区内找可导入的材料——PDF/MD 教材、课标、
   论文、HTML 教具、教案。**只看工作区内部**，不出边界。
2. **征求权限**：把扫描结果列给教师，问三件事——
   要不要建数据根、要不要导入这些材料、导入哪几类。
   **在得到同意之前，不创建目录、不复制任何文件。**
3. **执行**：同意后才建 `.shiban/`、导入选中材料、写 `state.json` 记录已做过。

## 为什么要问权限

首次使用就自动往工作区里复制几百 MB 教材，是越权行为。
而且材料可能包含不该被索引进库的东西（学生作业、个人笔记）。
所以：**先告知，再动手**。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import shiban_core as core
from shiban_core import ShibanError

STATE = "state.json"

# ===========================================================================
# 策略（可覆盖）：默认值面向"通用教育材料"，不依赖任何本机路径
# ===========================================================================
#
# 教师可在工作区放 .shiban/bootstrap.json 覆盖：
#   {
#     "policy": {
#       "include_dirs": ["教材", "materials"],
#       "exclude_dirs": ["私有"],
#       "kinds": {"textbook": {"ext": [".pdf"], "names": ["必修", "教科书"]}},
#       "name_noise": ["普通高中教科书"]
#     }
#   }
#
DEFAULT_POLICY = {
    # 目录名命中即跳过（个人证据、依赖、构建产物）
    "exclude_dirs": {
        ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
        ".shiban", ".dsh", ".idea", ".vscode",
        # 证据与个人数据：绝不参与"材料导入"
        "raw", "evidence", "triage", "logs",
        # 插件自身
        "vendor", "lib", "skills", "contracts", "framework",
    },
    # 文件名以这些开头的跳过（点文件、临时文件）
    "exclude_prefix": (".", "~$", "._"),
    # 说明性文件不是材料：README / INDEX / 目录 / 清单
    "exclude_names": ("readme", "index", "license", "changelog", "manifest",
                      "说明", "目录", "清单"),
    "max_depth": 4,
    # 类别判定：越具体的越先判
    "order": ["standard", "paper", "lesson", "asset", "textbook"],
    "kinds": {
        "standard": {
            "ext": (".pdf", ".md", ".txt"),
            # 规定性文件的强特征
            "names": ("课程标准", "课标", "考试大纲", "考试标准", "专业标准",
                      "职业能力标准", "应用指引", "教育知识与能力", "评分标准"),
            "dirs": ("标准", "课标", "standards", "大纲"),
        },
        "paper": {
            "ext": (".pdf", ".md"),
            "names": ("研究", "综述", "学位", "期刊", "journal", "review"),
            "dirs": ("文献", "论文", "研究", "papers", "literature"),
        },
        "lesson": {
            "ext": (".md", ".docx"),
            "names": ("教案", "教学设计", "lesson"),
            "dirs": ("教案", "教学设计", "lessons"),
        },
        "asset": {
            "ext": (".html", ".htm"),
            "names": (),
            "dirs": ("素材", "教具", "assets", "materials"),
        },
        "textbook": {
            "ext": (".pdf", ".md"),
            "names": ("必修", "教科书", "课本", "教材", "textbook"),
            "dirs": ("教材", "课本", "textbooks"),
        },
    },
    # 归一化文件名时去掉的通用前缀（用于 pdf/md 去重）
    "name_noise": ("普通高中教科书", "普通高中", "教科书", "人教版", "人教版高中",
                   "（2017年版2020年修订）", "2017年版2020年修订", "高中"),
}


def policy() -> dict:
    """读取工作区覆盖策略（.shiban/bootstrap.json 的 policy 段），与默认值浅合并。"""
    import copy
    merged = copy.deepcopy(DEFAULT_POLICY)
    for cand in (Path(core.root()) / "bootstrap.json",
                 Path(core.workspace_root()) / ".shiban" / "bootstrap.json"):
        if not cand.is_file():
            continue
        try:
            raw = json.loads(cand.read_text(encoding="utf-8")).get("policy") or {}
        except (OSError, ValueError):
            continue
        for key, val in raw.items():
            if key == "kinds" and isinstance(val, dict):
                for k, kv in val.items():
                    merged["kinds"].setdefault(k, {}).update(kv)
            elif isinstance(val, (set, list, tuple)):
                merged[key] = set(val) if key.endswith("dirs") else tuple(val)
            else:
                merged[key] = val
        break
    return merged


def _core_name(path: str, noise=None) -> str:
    """把「普通高中教科书·生物学必修2 遗传与进化.pdf」归一为「必修2 遗传与进化」。
    只用于 pdf/md 去重，不参与分类。"""
    words = noise if noise is not None else DEFAULT_POLICY["name_noise"]
    stem = Path(path).stem
    for w in words:
        stem = stem.replace(w, "")
    # 先删噪声词，再把分隔符归一，最后才去掉学科前缀
    for sep in ("·", "•", "_", "-", "—"):
        stem = stem.replace(sep, " ")
    stem = " ".join(stem.split())
    # 学科前缀（生物学/化学/物理…）可能紧贴在册次前
    for prefix in ("生物学", "生物", "化学", "物理", "地理", "历史"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):].strip()
            break
    return stem.lower()


def classify(name: str, relstr: str, ext: str, pol: dict | None = None) -> str | None:
    """纯函数：给文件名/相对目录/扩展名，返回类别或 None。

    规则：类别的 names 命中文件名，或 dirs 命中某一级目录名，即归类。
    判定不了就返回 None——**宁可不导，也不猜**。
    """
    pol = pol or DEFAULT_POLICY
    low = name.lower()
    rel_low = relstr.lower()
    parts = [x for x in rel_low.replace("\\", "/").split("/") if x]
    for kind in pol["order"]:
        rule = pol["kinds"].get(kind)
        if not rule or ext not in tuple(rule.get("ext") or ()):
            continue
        if any(w.lower() in low for w in rule.get("names") or ()):
            return kind
        # relstr 是文件所在目录的相对路径，所有层级都要看
        if any(p in {d.lower() for d in (rule.get("dirs") or ())} for p in parts):
            return kind
    return None


def _self_names() -> set:
    """本插件的包名（含历史名），用于识别"插件自身目录"。"""
    meta = core.package_meta()
    names = {(meta.get("name") or "").lower()}
    names |= {"@levilou/dsh-shiban", "@local/dsh-shiban", "@local/dsh-shiban-preset",
              "@local/dsh-shiban-v0-5-0" if False else "@levilou/dsh-shiban"}
    names.discard("")
    return names


def _is_self_dir(path: Path, pkg_names: set) -> bool:
    """目录里若有 package.json 且 name 属于本插件（或其旧名），视为插件自身。"""
    pj = path / "package.json"
    if not pj.is_file():
        return False
    try:
        name = (json.loads(pj.read_text(encoding="utf-8")).get("name") or "").lower()
    except (OSError, ValueError):
        return False
    return name in pkg_names


def state_path() -> Path:
    return Path(core.root()) / STATE


def read_state() -> dict | None:
    p = state_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_initialized() -> bool:
    """是否已完成首次准备（有 state.json 且 marked done）。"""
    st = read_state()
    return bool(st and st.get("completed"))


def scan(max_depth: int | None = None) -> dict:
    """**只读**扫描工作区内的候选材料。不创建任何东西。

    返回的 ``by_kind[k]["count"]`` 是**去重后的真实数量**，
    ``items`` 是其中最大的前 20 条明细，二者口径一致。
    """
    pol = policy()
    depth = max_depth if max_depth is not None else int(pol.get("max_depth") or 4)
    ws = Path(core.workspace_root())
    exclude = set(pol.get("exclude_dirs") or ())
    prefixes = tuple(pol.get("exclude_prefix") or ())
    found: dict = {k: [] for k in pol["order"]}

    for root, dirs, files in os.walk(ws):
        rel = Path(root).relative_to(ws)
        dirs[:] = [d for d in dirs
                   if d not in exclude and not d.startswith(".")]
        if len(rel.parts) >= depth:
            dirs[:] = []
        # 目录名或父级命中排除名单 → 整枝跳过
        if any(part in exclude for part in rel.parts):
            dirs[:] = []
            continue
        # 插件自身目录：含本包 package.json 的目录整枝跳过（不写死版本号路径）
        if rel.parts and _is_self_dir(Path(root), _self_names()):
            dirs[:] = []
            continue
        relstr = str(rel).replace(os.sep, "/")
        for name in files:
            if name.startswith(prefixes):
                continue
            stem_low = Path(name).stem.lower()
            if stem_low in set(pol.get("exclude_names") or ()):
                continue
            ext = Path(name).suffix.lower()
            kind = classify(name, relstr, ext, pol)
            if kind is None:
                continue
            path = Path(root) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            found.setdefault(kind, []).append(
                {"path": str(path.relative_to(ws)), "bytes": size})

    # 去重：同一份材料的 pdf 与 md 共存时只留 pdf，md 记为 also_found
    noise = pol.get("name_noise")
    for k, items in found.items():
        items.sort(key=lambda x: -x["bytes"])
        groups: dict = {}
        for it in items:
            groups.setdefault(_core_name(it["path"], noise), []).append(it)
        kept = []
        for members in groups.values():
            members.sort(key=lambda x: (Path(x["path"]).suffix.lower() != ".pdf",
                                        -x["bytes"]))
            primary = dict(members[0])
            others = [m["path"] for m in members[1:]]
            if others:
                primary["also_found"] = others
            kept.append(primary)
        kept.sort(key=lambda x: -x["bytes"])
        found[k] = kept

    total = sum(len(v) for v in found.values())
    return {
        "workspace": str(ws),
        "data_root": core.root(),
        "initialized": is_initialized(),
        "total": total,
        "by_kind": {
            k: {
                "count": len(v),
                "bytes": sum(x["bytes"] for x in v),
                "items": v[:20],          # 只截明细，count 保持真实值
                "truncated": max(0, len(v) - 20),
            }
            for k, v in found.items() if v
        },
        "empty_kinds": [k for k, v in found.items() if not v],
        "policy_source": str(Path(core.root()) / "bootstrap.json"),
    }


def plan(accept_kinds: list[str] | None = None) -> dict:
    """生成执行计划（不执行）。accept_kinds=None 表示全部类别。"""
    s = scan()
    kinds = accept_kinds if accept_kinds is not None else list(s["by_kind"].keys())
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        raise ShibanError("bad_args", f"未知类别：{unknown}",
                          f"可选：{', '.join(KINDS)}")
    steps = [
        {"step": "create_root", "detail": f"创建工作区数据根 {core.root()}"},
    ]
    for k in kinds:
        info = s["by_kind"].get(k)
        if not info:
            continue
        action = {"textbook": "corpus import（需 pdftotext）",
                  "standard": "corpus import",
                  "paper": "corpus import + 标注证据等级",
                  "asset": "asset import（先体检）",
                  "lesson": "作为参考材料登记，不入语料"}[k]
        steps.append({"step": f"import_{k}", "count": info["count"],
                      "bytes": info["bytes"], "action": action,
                      "items": [i["path"] for i in info["items"]]})
    return {**s, "plan": steps, "accepted": kinds,
            "note": "确认后执行 bootstrap run --accept " + ",".join(kinds)}


def run(accept_kinds: list[str] | None = None, copy: bool = True) -> dict:
    """执行首次准备。**只有调用此函数才会创建目录与复制文件。**"""
    s = scan()
    kinds = accept_kinds if accept_kinds is not None else list(s["by_kind"].keys())

    layout = core.ensure_layout()
    results = {"root": layout["root"], "created": True, "imported": {}, "skipped": []}

    ws = Path(core.workspace_root())
    for k in kinds:
        info = s["by_kind"].get(k)
        if not info:
            continue
        results["imported"][k] = []
        if k in ("textbook", "standard", "paper"):
            try:
                import shiban_corpus as corpus
            except ImportError:
                results["skipped"].append({"kind": k, "why": "corpus 模块不可用"})
                continue
            for item in info["items"]:
                src = ws / item["path"]
                cid = _corpus_id(src)
                try:
                    r = corpus.import_file(
                        str(src),
                        {"corpus_id": cid, "kind": k, "title": src.stem},
                    )
                    results["imported"][k].append({"path": item["path"], "corpus_id": cid,
                                                   "pages": r.get("pages_total")})
                except ShibanError as exc:
                    results["skipped"].append({"path": item["path"], "why": str(exc)})
        elif k == "asset":
            try:
                import shiban_asset as asset
            except ImportError:
                results["skipped"].append({"kind": k, "why": "asset 模块不可用"})
                continue
            for item in info["items"]:
                src = ws / item["path"]
                try:
                    r = asset.import_file(str(src), title=src.stem, category="other",
                                          stage="任意", origin="imported-web",
                                          license="unknown",
                                          provenance=f"工作区自动扫描：{item['path']}")
                    results["imported"][k].append({"path": item["path"],
                                                   "asset_id": r.get("asset_id")})
                except ShibanError as exc:
                    results["skipped"].append({"path": item["path"], "why": str(exc)})
        else:
            results["skipped"].append({"kind": k, "why": "教案类材料只登记不导入"})

    st = {
        "schema": "shiban.bootstrap/1",
        "at": core._now(),
        "version": core.package_meta()["version"],
        "workspace": s["workspace"],
        "root": layout["root"],
        "accepted_kinds": kinds,
        "completed": True,
        "summary": {k: len(v) for k, v in results["imported"].items()},
    }
    state_path().write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    return {**results, "state": str(state_path())}


def _corpus_id(path: Path) -> str:
    import re
    stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", path.stem)[:40].strip("-")
    digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:4]
    return f"{stem}-{digest}"


def status() -> dict:
    st = read_state()
    return {
        "initialized": bool(st and st.get("completed")),
        "root": core.root(),
        "state": st,
        "next": "已完成" if st else "首次使用：先 bootstrap scan，征得同意后 bootstrap run",
    }
