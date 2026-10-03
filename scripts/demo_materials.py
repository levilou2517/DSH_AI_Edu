#!/usr/bin/env python3
"""Generate isolated v0.4.3 teaching-material demos.

This is a developer/acceptance fixture, not a seed for a teacher's library.
It requires an explicit, non-default SHIBAN_ROOT and uses only stdlib plus the
existing shiban_store API. It creates synthetic atoms and compose pages under
that external root, then prints paths and compose specs for inspection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICES = HERE.parent / "services"
sys.path.insert(0, str(SERVICES))
import shiban_store as store  # noqa: E402


CYCLE_ANIMATION = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
.atom{font:16px system-ui,sans-serif;color:#17324d}.stage{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.cell{width:72px;height:72px;border-radius:50%;display:grid;place-items:center;border:3px solid #2b6cb0;background:#e8f1ff;transition:transform .3s}
.cell.active{transform:scale(1.12);background:#bee3f8}.arrow{color:#718096}.note{margin-top:12px;color:#4a5568}
</style></head><body><div class="atom"><div class="stage" id="cycle-stage">
<div class="cell" data-stage="G1">G1</div><span class="arrow">→</span><div class="cell" data-stage="S">S</div>
<span class="arrow">→</span><div class="cell" data-stage="G2">G2</div><span class="arrow">→</span><div class="cell" data-stage="M">M</div>
</div><p class="note" id="cycle-note">动画仅展示阶段顺序与相对节奏。</p></div>
<script>(function(){const d=window.__MATERIAL_DATA||{};const order=d.order||['G1','S','G2','M'];const cells=[...document.querySelectorAll('.cell')];let i=0;
function tick(){cells.forEach(x=>x.classList.toggle('active',x.dataset.stage===order[i%order.length]));document.querySelector('#cycle-note').textContent=(d.caption||'细胞周期阶段顺序')+'：'+order[i%order.length];i++;}
tick();setInterval(tick,Number(d.interval_ms||900));})();</script></body></html>"""

CYCLE_TIMELINE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
.atom{font:16px system-ui,sans-serif;color:#17324d}.row{display:grid;grid-template-columns:90px 1fr;gap:12px;margin:8px 0}.bar{height:22px;background:#dbeafe;border-left:4px solid #2563eb;padding-left:8px}
</style></head><body><div class="atom"><div id="timeline"></div></div>
<script>(function(){const d=window.__MATERIAL_DATA||{};const target=document.querySelector('#timeline');(d.items||[{name:'G1',summary:'生长与物质准备',share:30},{name:'S',summary:'DNA复制',share:30},{name:'G2',summary:'分裂准备',share:20},{name:'M',summary:'核分裂与胞质分裂',share:20}]).forEach(x=>{const r=document.createElement('div');r.className='row';const name=document.createElement('b');name.textContent=x.name;const bar=document.createElement('div');bar.className='bar';bar.style.width=Math.min(100,Math.max(10,Number(x.share)||10))+'%';bar.textContent=x.summary;r.append(name,bar);target.appendChild(r);});})();</script></body></html>"""

PAIRING = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
.atom{font:16px system-ui,sans-serif;color:#17324d}.pair{display:grid;grid-template-columns:1fr 70px 1fr;gap:10px;align-items:center;max-width:430px}.base{padding:12px;text-align:center;border:2px solid #2f855a;border-radius:8px;background:#f0fff4}.bond{text-align:center;color:#805ad5}.hint{margin-top:12px;color:#744210}
</style></head><body><div class="atom"><div class="pair"><div class="base" id="left">A</div><div class="bond" id="bond">⇄</div><div class="base" id="right">T</div></div><div class="hint" id="hint">配对关系图示；具体教学表述由教师确认。</div></div>
<script>(function(){const d=window.__MATERIAL_DATA||{};document.querySelector('#left').textContent=d.left||'A';document.querySelector('#right').textContent=d.right||'T';document.querySelector('#bond').textContent=d.bond||'⇄';document.querySelector('#hint').textContent=d.hint||'配对关系图示；具体教学表述由教师确认。';})();</script></body></html>"""

STRUCTURE_SCHEMATIC = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
.atom{font:16px system-ui,sans-serif;color:#17324d}.diagram{max-width:430px;border:1px solid #cbd5e0;padding:14px}.diagram svg{width:100%;height:180px}.label{text-align:center;font-weight:700}.warning{color:#9c4221;font-size:13px;margin-top:8px}
</style></head><body><div class="atom"><div class="diagram"><svg viewBox="0 0 430 180" role="img" aria-label="碱基结构示意"><polygon points="100,65 140,40 180,65 180,115 140,140 100,115" fill="#bee3f8" stroke="#2b6cb0" stroke-width="3"/><polygon points="180,65 225,50 253,90 225,130 180,115" fill="#c6f6d5" stroke="#2f855a" stroke-width="3"/><text x="111" y="96" font-size="14">六元环</text><text x="187" y="96" font-size="14">五元环</text></svg><div class="label" id="label">腺嘌呤：嘌呤双环骨架示意</div><div class="warning">只展示稠合五元环与六元环；省略 N/C、取代基与键级，不是完整化学结构式。</div></div></div>
<script>(function(){const d=window.__MATERIAL_DATA||{};document.querySelector('#label').textContent=(d.base||'A')+'：'+(d.label||'结构骨架示意');})();</script></body></html>"""


def write_source(root: Path, name: str, html: str) -> Path:
    path = root / "demo-source" / f"{name}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def add(root: Path, aid: str, title: str, kp: str, source: Path, interface: dict) -> dict:
    return store.add_asset(aid, "html", title, str(source), subject="生物",
                           knowledge_point=kp, params={"interface": interface},
                           tags="v0.4.3-demo,synthetic,not-teacher-data")


def main() -> int:
    ap = argparse.ArgumentParser(description="Create isolated v0.4.3 material demos")
    ap.add_argument("--root", required=True, help="explicit isolated SHIBAN_ROOT; must not be the default real library")
    args = ap.parse_args()
    root = Path(args.root).expanduser().resolve()
    default_root = Path(os.path.expanduser("~/.shiban")).resolve()
    if root == default_root or not root.name.startswith(("demo-", "test-", "tmp-")):
        ap.error("拒绝使用默认真实库；--root 必须是显式隔离目录名（demo-/test-/tmp-）")
    os.environ["SHIBAN_ROOT"] = str(root)
    # store constants are read at import time; this script is intentionally a
    # subprocess-style fixture and sets the root before any store call.
    store.ROOT = str(root); store.DATA_DIR = str(root / "data"); store.SHIBAN_DATA = str(root / "data/shiban")
    store.RAW_DIR = str(root / "data/shiban/raw"); store.META_DB = str(root / "data/meta.db"); store.REF_DB = str(root / "data/reference.db")
    store.init()
    print(json.dumps({"data_root": str(root), "asset_root": str(root / "data/assets"), "mode": "isolated-synthetic"}, ensure_ascii=False))

    atoms = [
        add(root, "demo-cycle-animation", "细胞周期阶段动画（演示）", "细胞周期", write_source(root, "cycle-animation", CYCLE_ANIMATION),
            {"order": {"type": "array"}, "interval_ms": {"type": "number"}, "caption": {"type": "string"}}),
        add(root, "demo-cycle-timeline", "细胞周期时间表（演示）", "细胞周期", write_source(root, "cycle-timeline", CYCLE_TIMELINE),
            {"items": {"type": "array", "required": True}}),
        add(root, "demo-base-pairing", "碱基配对图示（演示）", "碱基配对", write_source(root, "base-pairing", PAIRING),
            {"left": {"type": "string"}, "right": {"type": "string"}, "bond": {"type": "string"}, "hint": {"type": "string"}}),
        add(root, "demo-base-structure-schematic", "碱基结构骨架示意（演示）", "碱基结构式", write_source(root, "base-structure-schematic", STRUCTURE_SCHEMATIC),
            {"base": {"type": "string"}, "label": {"type": "string"}}),
    ]
    cycle_spec = {"page_id": "demo-cycle-page", "title": "细胞周期：动画与时间表", "knowledge_point": "细胞周期", "layout": {"mode": "stack", "gap": 18}, "sections": [
        {"asset": "demo-cycle-animation", "label": "阶段顺序动画", "data": {"order": ["G1", "S", "G2", "M"], "interval_ms": 800, "caption": "细胞周期"}},
        {"asset": "demo-cycle-timeline", "label": "大纲时间表", "data": {"items": [{"name": "G1", "summary": "生长与准备", "share": 30}, {"name": "S", "summary": "DNA复制", "share": 30}, {"name": "G2", "summary": "分裂准备", "share": 20}, {"name": "M", "summary": "分裂过程", "share": 20}]}}]}
    pair_spec = {"page_id": "demo-base-page", "title": "碱基：配对图示与结构骨架", "knowledge_point": "碱基配对", "layout": {"mode": "grid", "gap": 18}, "sections": [
        {"asset": "demo-base-pairing", "label": "A-T 配对关系图示", "data": {"left": "A", "right": "T", "bond": "⇄"}},
        {"asset": "demo-base-structure-schematic", "label": "A 的结构骨架示意", "data": {"base": "A", "label": "A：结构骨架示意"}}]}
    nested_spec = {"page_id": "demo-nested-page", "title": "嵌套编排验收页", "sections": [{"asset": "demo-cycle-page", "label": "已编排页面作为组件", "data": {}}]}
    for spec in (cycle_spec, pair_spec):
        print(json.dumps({"compose_spec": spec, "result": store.compose_asset(spec)}, ensure_ascii=False))
    print(json.dumps({"nested_spec": nested_spec, "result": store.compose_asset(nested_spec)}, ensure_ascii=False))
    print(json.dumps({"assets": store.list_assets(kind="html")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
