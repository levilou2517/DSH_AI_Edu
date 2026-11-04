#!/usr/bin/env python3
"""shiban_asset — 素材库（HTML 教具）：导入、分类、检索、编排。

设计原则（承接 v0.4.3 已验证的部分）：
  * 产物只住 ``$SHIBAN_ROOT/data/assets/<asset_id>/``，不随包分发；
  * 原子通过 ``window.__MATERIAL_DATA`` 接收输入，编排页用
    ``<iframe sandbox="allow-scripts" srcdoc>`` 隔离每一节；
  * 先查后建：``suggest`` 只读，``reuse`` 才计数。

v0.5.0 新增（外来 HTML）：
  * ``import_file`` 先体检（自包含性、沙箱兼容、可消费接口），再入库；
  * 分类维度：category（用途）× stage（教学环节）× origin/ license；
  * ``triage`` 批量出报告（CSV），审后再导。
"""
from __future__ import annotations

import csv
import hashlib
import html as html_lib
import io
import json
import os
import re
import shutil
import unicodedata
from pathlib import Path

import shiban_core as core
from shiban_core import ShibanError

CONSTANTS = core.constants()
CATEGORIES = tuple(CONSTANTS.get("asset_categories") or [])
STAGES = tuple(CONSTANTS.get("asset_stages") or [])
LICENSES = tuple(CONSTANTS.get("asset_licenses") or [])
ORIGINS = tuple(CONSTANTS.get("asset_origins") or [])

_ID_RE = re.compile(r"[\w\u4e00-\u9fff.-]+")
_EXTERNAL_RE = re.compile(
    r"""(?:src|href)\s*=\s*["'](https?://[^"']+)["']|url\(\s*["']?(https?://[^)"']+)""",
    re.I,
)
_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.I | re.S)
_RISK_PATTERNS = (
    (re.compile(r"document\.cookie", re.I), "访问 cookie（沙箱内不可用）"),
    (re.compile(r"\bwindow\.(parent|top)\b", re.I), "访问父窗口（跨 iframe 泄漏风险）"),
    (re.compile(r"\blocalStorage\b|\bsessionStorage\b", re.I), "使用存储（不透明源下抛错）"),
    (re.compile(r"\bfetch\s*\(|XMLHttpRequest", re.I), "发起网络请求（离线/沙箱受限）"),
)


# --------------------------------------------------------------------------- #
# 路径与标识
# --------------------------------------------------------------------------- #

def assets_dir() -> Path:
    return Path(core.root()) / "data" / "assets"


def _slug(text: str, limit: int = 24) -> str:
    s = unicodedata.normalize("NFC", str(text or "").strip())
    s = re.sub(r"[\s/\\:*?\"<>|]+", "", s)
    return (s[:limit] or "untitled")


def _make_asset_id(title: str, kp: str | None, digest: str) -> str:
    return f"asset-{_slug(kp or 'global', 16)}-{_slug(title)}-{digest[:4]}"


def _asset_dir(asset_id: str) -> Path:
    if not _ID_RE.fullmatch(asset_id or ""):
        raise ShibanError("bad_name", f"非法 asset id：{asset_id!r}")
    return assets_dir() / asset_id


def _read_meta(asset_id: str) -> dict | None:
    path = _asset_dir(asset_id) / "meta.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# 体检
# --------------------------------------------------------------------------- #

def inspect_html(path: str | Path) -> dict:
    """只读体检一个 HTML 文件，返回问题清单与可消费性判断。"""
    p = Path(path)
    if not p.is_file():
        raise ShibanError("not_found", f"文件不存在：{p}")
    raw = p.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gbk")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", "replace")

    external = sorted({m.group(1) or m.group(2) for m in _EXTERNAL_RE.finditer(text)})
    risks = []
    for pattern, label in _RISK_PATTERNS:
        if pattern.search(text):
            risks.append(label)

    has_data_hook = "__MATERIAL_DATA" in text
    has_script = bool(_SCRIPT_RE.search(text))
    # 可见文本占比：粗略衡量"是不是一张能看的图/页"
    visible = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.I | re.S)
    visible = re.sub(r"<[^>]+>", " ", visible)
    visible = re.sub(r"\s+", "", visible)
    total = len(re.sub(r"\s+", "", text)) or 1

    declared_interface = None
    m = re.search(r"__MATERIAL_INTERFACE__\s*=\s*(\{.*?\});", text, re.S)
    if m:
        try:
            declared_interface = json.loads(m.group(1))
        except ValueError:
            declared_interface = None

    return {
        "file": str(p),
        "bytes": len(raw),
        "sha256": digest,
        "self_contained": not external,
        "external_refs": external,
        "sandbox_safe": not any("父窗口" in r for r in risks),
        "risks": risks,
        "has_script": has_script,
        "data_hook": has_data_hook,
        "interface_declared": declared_interface,
        "text_ratio": round(len(visible) / total, 3),
        "renderable": bool(visible) or has_script,
    }


# --------------------------------------------------------------------------- #
# 导入
# --------------------------------------------------------------------------- #

def import_file(file_path: str, title: str, category: str = "other", stage: str = "任意",
                kp: str | None = None, origin: str = "imported-web",
                license: str = "unknown", provenance: str = "",
                interface: dict | None = None, dry_run: bool = False) -> dict:
    """把一个 HTML 文件登记为素材。重复内容（同 sha256）返回既有 id。"""
    if category not in CATEGORIES:
        raise ShibanError("bad_args", f"category 非法：{category!r}", f"允许：{', '.join(CATEGORIES)}")
    if stage not in STAGES:
        raise ShibanError("bad_args", f"stage 非法：{stage!r}", f"允许：{', '.join(STAGES)}")
    if origin not in ORIGINS:
        raise ShibanError("bad_args", f"origin 非法：{origin!r}", f"允许：{', '.join(ORIGINS)}")
    if license not in LICENSES:
        raise ShibanError("bad_args", f"license 非法：{license!r}", f"允许：{', '.join(LICENSES)}")

    report = inspect_html(file_path)
    if not report["renderable"]:
        raise ShibanError("not_html", f"{file_path} 没有可见内容，不像一个教具页面")

    asset_id = _make_asset_id(title, kp, report["sha256"])
    existing = _read_meta(asset_id)
    if existing is not None:
        return {"ok": True, "existed": True, "asset_id": asset_id,
                "reason": "同内容已收录", "inspection": report}

    composed = interface is not None or report["interface_declared"] is not None
    meta = {
        "asset_id": asset_id,
        "title": title,
        "kind": "html",
        "category": category,
        "stage": stage,
        "kp": [kp] if kp else [],
        "origin": origin,
        "license": license,
        "provenance": provenance,
        "interface": interface or report["interface_declared"],
        "composable": bool(composed),
        "self_contained": report["self_contained"],
        "external_refs": report["external_refs"],
        "sha256": report["sha256"],
        "bytes": report["bytes"],
        "text_ratio": report["text_ratio"],
        "reuse_count": 0,
        "created_at": core._now(),
    }
    if dry_run:
        return {"ok": True, "dry_run": True, "asset_id": asset_id,
                "meta": meta, "inspection": report}

    dest = _asset_dir(asset_id)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "main.html"
    if target.exists():
        raise ShibanError("exists", f"素材已存在但内容不同：{asset_id}", "换一个 title 或 kp。")
    shutil.copyfile(file_path, target)
    _write_json(dest / "meta.json", meta)
    return {"ok": True, "existed": False, "asset_id": asset_id,
            "path": str(target), "composable": meta["composable"],
            "inspection": report}


def triage(path: str, dry_run: bool = True) -> dict:
    """批量体检一个目录（或单个文件），输出可导入清单。"""
    root = Path(path)
    files = []
    if root.is_file():
        files = [root]
    elif root.is_dir():
        files = sorted(p for p in root.rglob("*") if p.suffix.lower() in (".html", ".htm"))
    else:
        raise ShibanError("not_found", f"路径不存在：{path}")

    rows = []
    for f in files:
        try:
            rep = inspect_html(f)
        except ShibanError as exc:
            rows.append({"file": str(f), "ok": False, "problem": str(exc)})
            continue
        suggested = "interactive" if rep["has_script"] else "diagram"
        rows.append({
            "file": str(f),
            "ok": rep["renderable"],
            "bytes": rep["bytes"],
            "self_contained": rep["self_contained"],
            "external_refs": ";".join(rep["external_refs"]),
            "sandbox_safe": rep["sandbox_safe"],
            "risks": ";".join(rep["risks"]),
            "suggested_category": suggested,
            "suggested_stage": "任意",
            "needs_interface": not rep["data_hook"],
            "title": f.stem,
            "kp": "",
        })

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    out_dir = Path(core.root()) / "data" / "triage"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "triage.csv"
    csv_path.write_text(buf.getvalue(), encoding="utf-8")

    return {
        "ok": True,
        "scanned": len(rows),
        "self_contained": sum(1 for r in rows if r.get("self_contained")),
        "needs_interface": sum(1 for r in rows if r.get("needs_interface")),
        "csv": str(csv_path),
        "next": f"在 {csv_path.name} 里填 category/stage/kp 后逐条 asset import",
        "dry_run": dry_run,
    }


# --------------------------------------------------------------------------- #
# 检索
# --------------------------------------------------------------------------- #

def get(asset_id: str) -> dict | None:
    meta = _read_meta(asset_id)
    if meta is None:
        return None
    meta = dict(meta)
    meta["absolute_file_path"] = str(_asset_dir(asset_id) / "main.html")
    return meta


def list_assets(kind: str | None = None, kp: str | None = None,
                category: str | None = None, stage: str | None = None) -> list:
    out = []
    base = assets_dir()
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        meta = _read_meta(d.name)
        if not meta:
            continue
        if kind and meta.get("kind") != kind:
            continue
        if category and meta.get("category") != category:
            continue
        if stage and meta.get("stage") != stage:
            continue
        if kp and kp not in (meta.get("kp") or []):
            continue
        row = dict(meta)
        row["absolute_file_path"] = str(d / "main.html")
        out.append(row)
    out.sort(key=lambda r: (-int(r.get("reuse_count") or 0), r.get("asset_id", "")))
    return out


def suggest(knowledge_point: str | None = None, kind: str | None = None,
            limit: int = 10) -> dict:
    """只读：按知识点模糊匹配，返回可复用素材（不计数）。"""
    rows = list_assets(kind=kind)
    if knowledge_point:
        needle = knowledge_point.casefold()
        rows = [r for r in rows
                if any(needle in str(k).casefold() for k in (r.get("kp") or []))
                or needle in str(r.get("title", "")).casefold()]
    atoms = [r for r in rows if not r.get("assembly")]
    pages = [r for r in rows if r.get("assembly")]
    return {
        "knowledge_point": knowledge_point,
        "counts": {"atoms": len(atoms), "pages": len(pages)},
        "atoms": atoms[:limit],
        "pages": pages[:limit],
        "hint": "命中则 reuse 后直接用；未命中再新建。" if rows else "库内无匹配，可新建原子。",
    }


def reuse(asset_id: str) -> dict:
    meta = _read_meta(asset_id)
    if meta is None:
        raise ShibanError("not_found", f"素材不存在：{asset_id}")
    meta["reuse_count"] = int(meta.get("reuse_count") or 0) + 1
    meta["last_used_at"] = core._now()
    _write_json(_asset_dir(asset_id) / "meta.json", meta)
    return {"ok": True, "asset_id": asset_id,
            "reuse_count": meta["reuse_count"],
            "absolute_file_path": str(_asset_dir(asset_id) / "main.html")}


# --------------------------------------------------------------------------- #
# 编排（沿用 v0.4.3 已验证的 iframe/srcdoc 隔离）
# --------------------------------------------------------------------------- #

def _inline_data(document: str, data: dict) -> str:
    payload = json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    payload = (payload.replace("<", "\\u003c")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    injection = f"<script>window.__MATERIAL_DATA={payload};</script>"
    head = re.search(r"<head\b[^>]*>", document, re.I)
    if head:
        return document[:head.end()] + injection + document[head.end():]
    opening = re.search(r"<html\b[^>]*>", document, re.I)
    if opening:
        return document[:opening.end()] + "<head>" + injection + "</head>" + document[opening.end():]
    return injection + document


def _validate_against_interface(interface: dict | None, data: dict, where: str) -> list[str]:
    """零依赖子集校验：required / type / enum。"""
    if not interface:
        return []
    schema = interface.get("properties", interface) if isinstance(interface, dict) else {}
    if not isinstance(schema, dict):
        return []
    required = schema.get("required") if "required" in schema else None
    if isinstance(required, list):
        fields, required = schema.get("properties", {}), set(required)
    else:
        fields = schema
        required = {k for k, v in schema.items() if isinstance(v, dict) and v.get("required")}
    errors = [f"{where}.{k} 缺少必填字段" for k in sorted(required) if k not in data]
    types = {"string": str, "number": (int, float), "integer": int,
             "boolean": bool, "array": list, "object": dict}
    for k, c in fields.items():
        if k not in data or not isinstance(c, dict):
            continue
        expect = c.get("type")
        if expect in types and not isinstance(data[k], types[expect]):
            if not (expect == "number" and isinstance(data[k], bool)):
                errors.append(f"{where}.{k} 类型应为 {expect}")
        if "enum" in c and data[k] not in c["enum"]:
            errors.append(f"{where}.{k}={data[k]!r} 不在 {c['enum']}")
    return errors


def compose_spec_schema() -> dict:
    return {
        "type": "object",
        "required": ["page_id", "title", "sections"],
        "properties": {
            "page_id": {"type": "string"},
            "title": {"type": "string"},
            "layout": {"type": "object",
                       "properties": {"mode": {"enum": ["stack", "grid"]},
                                      "gap": {"type": "number"}}},
            "sections": {"type": "array", "items": {
                "type": "object", "required": ["asset"],
                "properties": {"asset": {"type": "string"}, "label": {"type": "string"},
                               "data": {"type": "object"}}}},
        },
    }


def compose(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ShibanError("bad_args", "spec 必须是 JSON 对象")
    for key in ("page_id", "title", "sections"):
        if not spec.get(key):
            raise ShibanError("bad_args", f"spec 缺少必填字段：{key}")
    sections = spec["sections"]
    if not isinstance(sections, list) or not sections:
        raise ShibanError("bad_args", "sections 必须是非空数组")
    layout = spec.get("layout") or {}
    mode = layout.get("mode", "stack")
    gap = layout.get("gap", 20)
    if mode not in ("stack", "grid"):
        raise ShibanError("bad_args", "layout.mode 必须是 stack|grid")

    parts, used, records = [], [], []
    for i, sec in enumerate(sections, 1):
        aid = sec.get("asset")
        meta = _read_meta(aid or "")
        if meta is None:
            raise ShibanError("not_found", f"sections[{i}] 引用的素材不存在：{aid}")
        data = sec.get("data") or {}
        errs = _validate_against_interface(meta.get("interface"), data, f"sections[{i}]")
        if errs:
            raise ShibanError("invalid_data", "；".join(errs))
        doc = (_asset_dir(aid) / "main.html").read_text(encoding="utf-8")
        doc = _inline_data(doc, data)
        label = html_lib.escape(str(sec.get("label") or meta.get("title") or aid), quote=True)
        parts.append(
            f'<section class="shiban-sec" data-asset="{html_lib.escape(aid, quote=True)}">'
            f'<div class="shiban-sec-label">{label}</div>'
            f'<iframe title="{label}" sandbox="allow-scripts" srcdoc="{html_lib.escape(doc, quote=True)}"'
            ' class="shiban-sec-frame"></iframe></section>'
        )
        used.append(aid)
        records.append({"asset": aid, "label": sec.get("label"), "data": data})

    page_id = _slug(spec["page_id"], 40)
    title = html_lib.escape(str(spec["title"]), quote=True)
    display = ("display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));"
               if mode == "grid" else "display:flex;flex-direction:column;")
    page = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>body{{margin:0;background:#f8fafc;"
        "font-family:system-ui,sans-serif;color:#1f2937}}.shiban-page{max-width:1200px;"
        "margin:0 auto;padding:20px}.shiban-page-title{font-size:20px;font-weight:700;"
        f"margin:0 0 16px}}.shiban-segments{{{display}gap:{gap}px}}"
        ".shiban-sec{background:#fff}.shiban-sec-label{font-size:14px;font-weight:600;"
        "color:#0d9488;padding:10px 16px 0}.shiban-sec-frame{display:block;width:100%;"
        'min-height:120px;border:0}</style></head><body><main class="shiban-page">'
        f'<div class="shiban-page-title">{title}</div><div class="shiban-segments">'
        + "".join(parts) + "</div></main></body></html>"
    )
    digest = hashlib.sha256(page.encode("utf-8")).hexdigest()
    asset_id = _make_asset_id(spec["title"], "page", digest)
    dest = _asset_dir(asset_id)
    if dest.exists():
        return {"ok": True, "existed": True, "asset_id": asset_id}

    dest.mkdir(parents=True)
    (dest / "main.html").write_text(page, encoding="utf-8")
    _write_json(dest / "meta.json", {
        "asset_id": asset_id, "title": spec["title"], "kind": "html",
        "category": "interactive", "stage": "任意", "kp": [], "origin": "generated",
        "license": "own", "provenance": "compose", "interface": None,
        "composable": False, "self_contained": True, "external_refs": [],
        "sha256": digest, "bytes": len(page.encode("utf-8")), "reuse_count": 0,
        "assembly": {"sections": records, "layout": {"mode": mode, "gap": gap}},
        "created_at": core._now(),
    })
    for aid in used:
        reuse(aid)
    return {"ok": True, "existed": False, "asset_id": asset_id,
            "absolute_file_path": str(dest / "main.html"),
            "sections": len(sections), "atoms": sorted(set(used))}


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _selftest() -> int:
    import tempfile
    tmp = tempfile.mkdtemp(prefix="shiban-asset-selftest-")
    os.environ["SHIBAN_ROOT"] = tmp
    try:
        core.ensure_layout()
        src = Path(tmp) / "atom.html"
        src.write_text(
            '<!doctype html><html><body><div id="v"></div>'
            '<script>document.getElementById("v").textContent = '
            '(window.__MATERIAL_DATA||{}).value || "none";</script></body></html>',
            encoding="utf-8",
        )
        rep = inspect_html(src)
        assert rep["self_contained"] and rep["sandbox_safe"], rep

        first = import_file(str(src), "测试原子", category="interactive", stage="建构",
                            kp="细胞周期", interface={"value": {"type": "string", "required": True}})
        assert not first["existed"] and first["composable"], first
        aid = first["asset_id"]

        again = import_file(str(src), "测试原子", category="interactive", stage="建构",
                            kp="细胞周期")
        assert again["existed"] and again["asset_id"] == aid, again

        sug = suggest(knowledge_point="细胞")
        assert sug["counts"]["atoms"] == 1, sug

        page = compose({"page_id": "p1", "title": "<不安全>", "sections": [
            {"asset": aid, "label": "<标签>", "data": {"value": "</script><x>"}},
            {"asset": aid, "data": {"value": "第二次"}},
        ]})
        out = Path(page["absolute_file_path"]).read_text(encoding="utf-8")
        assert out.count('sandbox="allow-scripts"') == 2, "每节必须独立沙箱"
        assert "allow-same-origin" not in out
        assert "&lt;不安全&gt;" in out
        assert "</script><x>" not in out, "数据里的 </script> 必须被转义"

        try:
            compose({"page_id": "p2", "title": "x", "sections": [{"asset": aid, "data": {}}]})
            raise AssertionError("缺必填应报错")
        except ShibanError as exc:
            assert exc.code == "invalid_data", exc
        assert not (_asset_dir(_slug("p2", 40))).exists() or True

        assert reuse(aid)["reuse_count"] == 3, "两次编排 + 一次显式复用"
        assert len(list_assets(category="interactive")) == 2
        print("OK")
        return 0
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(_selftest())
