#!/usr/bin/env python3
"""shiban-store — 师伴持久数据层 CLI。

用法（零第三方依赖）：
  .venv/bin/python services/shiban_cli.py init
  .venv/bin/python services/shiban_cli.py teacher add --id T_LIU --name 刘老师 --profile '{"preferences":{"去选项化":true}}'
  .venv/bin/python services/shiban_cli.py class add --id c1 --teacher T_LIU --level 高二 --cohort 2026 --family 高二(1)班
  .venv/bin/python services/shiban_cli.py student add --id s1 --class c1 --name 王同学
  .venv/bin/python services/shiban_cli.py lesson add --class c1 --id l1 --date 2026-09-02 --topic DNA复制 \
        --kp DNA复制 --scaffold 类比 --level 理解 --pass 0.8
  .venv/bin/python services/shiban_cli.py obs add --class c1 --student s1 --id obs1 \
        --dimension '{"kp":"DNA复制"}' --evidence '{"ai_data":{"pass_rate":0.71}}' --alignment conflict \
        --integrated '概念识别达标'
  .venv/bin/python services/shiban_cli.py query --kp DNA复制 --scaffold 类比
  .venv/bin/python services/shiban_cli.py classes --teacher T_LIU
  .venv/bin/python services/shiban_cli.py asset add --id a1 --kind report --title 示例 --file out.json --kp DNA复制
  .venv/bin/python services/shiban_cli.py asset list [--kind report] [--kp ...] [--subject ...]
  .venv/bin/python services/shiban_cli.py asset get --id a1 | asset reuse --id a1
  .venv/bin/python services/shiban_cli.py asset suggest --kp DNA复制 [--kind html]     # 先查后建：库存+契约+建议
  .venv/bin/python services/shiban_cli.py asset compose --spec '{"page_id":"...","title":"...","sections":[...]}'
  .venv/bin/python services/shiban_cli.py asset compose --spec-schema                # 查 spec 输入契约

Agent 不直接碰文件；经此 CLI 或宿主服务访问 ~/.shiban/data。
"""
import argparse
import json
import sys
from pathlib import Path

import shiban_store as S


def _loads(s, default=None):
    """Parse optional JSON values; malformed JSON is a user input error."""
    if not s:
        return {} if default is None else default
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"参数不是合法 JSON: {e.msg} (第 {e.lineno} 行)") from e


def _load_spec(spec=None, spec_file=None, spec_stdin=False):
    """Load compose JSON from exactly one compatible input source."""
    selected = sum(value is not None for value in (spec, spec_file)) + int(spec_stdin)
    if selected != 1:
        raise ValueError("compose 必须且只能指定 --spec、--spec-file 或 --spec-stdin 之一")
    if spec_file is not None:
        try:
            text = Path(spec_file).read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"无法读取 spec 文件: {e}") from e
    elif spec_stdin:
        text = sys.stdin.read()
    else:
        text = spec
    if not text or not text.strip():
        raise ValueError("spec 内容为空")
    return _loads(text)


def _run(fn, *args, **kwargs):
    """统一错误出口：非法输入打印到 stderr 并以 2 退出，不抛 traceback。"""
    try:
        return fn(*args, **kwargs)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"[error] {e}\n")
        raise SystemExit(2) from e


def main():
    ap = argparse.ArgumentParser(prog="shiban-store")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    sub.add_parser("classes").add_argument("--teacher")

    t = sub.add_parser("teacher"); ts = t.add_subparsers(dest="sub", required=True)
    ta = ts.add_parser("add"); ta.add_argument("--id", required=True); ta.add_argument("--name", required=True); ta.add_argument("--profile")
    ta2 = ts.add_parser("get"); ta2.add_argument("--id", required=True)

    c = sub.add_parser("class"); cs = c.add_subparsers(dest="sub", required=True)
    ca = cs.add_parser("add"); ca.add_argument("--id", required=True); ca.add_argument("--teacher", required=True)
    ca.add_argument("--level", default="高二"); ca.add_argument("--cohort", required=True); ca.add_argument("--family", required=True)

    st = sub.add_parser("student"); sts = st.add_subparsers(dest="sub", required=True)
    sa = sts.add_parser("add"); sa.add_argument("--id", required=True); sa.add_argument("--class", dest="class_id", required=True)
    sa.add_argument("--name", required=True); sa.add_argument("--external")

    l = sub.add_parser("lesson"); ls = l.add_subparsers(dest="sub", required=True)
    la = ls.add_parser("add"); la.add_argument("--class", dest="class_id", required=True); la.add_argument("--id", required=True)
    la.add_argument("--date", required=True); la.add_argument("--topic", required=True); la.add_argument("--kp", required=True)
    la.add_argument("--scaffold", required=True); la.add_argument("--level", required=True); la.add_argument("--pass", dest="passrate", type=float, required=True)

    o = sub.add_parser("obs"); os_ = o.add_subparsers(dest="sub", required=True)
    oa = os_.add_parser("add"); oa.add_argument("--class", dest="class_id", required=True); oa.add_argument("--student", required=True)
    oa.add_argument("--id", required=True); oa.add_argument("--dimension"); oa.add_argument("--evidence")
    oa.add_argument("--alignment", required=True); oa.add_argument("--integrated", required=True)

    q = sub.add_parser("query"); q.add_argument("--scaffold"); q.add_argument("--kp"); q.add_argument("--level")

    ast = sub.add_parser("asset"); ats = ast.add_subparsers(dest="sub", required=True)
    aa = ats.add_parser("add")
    aa.add_argument("--id", required=True); aa.add_argument("--kind", required=True)
    aa.add_argument("--title", required=True); aa.add_argument("--file", required=True)
    aa.add_argument("--subject"); aa.add_argument("--kp"); aa.add_argument("--lesson")
    aa.add_argument("--tags"); aa.add_argument("--params")
    # v0.4.3 层级编排：--parent 自引用上层宿主页；--assembly JSON 编排子组件+喂数据
    aa.add_argument("--parent", dest="parent_asset")
    aa.add_argument("--assembly")
    al = ats.add_parser("list")
    al.add_argument("--kind"); al.add_argument("--kp"); al.add_argument("--subject")
    ag = ats.add_parser("get"); ag.add_argument("--id", required=True)
    ar = ats.add_parser("reuse"); ar.add_argument("--id", required=True)
    asc = ats.add_parser("scan"); asc.add_argument("--dry-run", action="store_true")
    # v0.4.3 编排：suggest=先查后建只读；compose=按 interface 校验喂数并装配页面
    asg = ats.add_parser("suggest")
    asg.add_argument("--kp"); asg.add_argument("--kind"); asg.add_argument("--subject")
    acp = ats.add_parser("compose")
    spec_group = acp.add_mutually_exclusive_group()
    spec_group.add_argument("--spec", help="编排规格 JSON（--spec-schema 查看契约）")
    spec_group.add_argument("--spec-file", help="从 UTF-8 文件读取编排规格 JSON")
    spec_group.add_argument("--spec-stdin", action="store_true", help="从 stdin 读取编排规格 JSON")
    acp.add_argument("--spec-schema", action="store_true", dest="spec_schema",
                     help="输出 store 提供的 compose JSON Schema")

    rw = sub.add_parser("raw"); rws = rw.add_subparsers(dest="sub", required=True)
    rs = rws.add_parser("save"); rs.add_argument("--name", required=True)
    src = rs.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="证据源文件路径（读取其内容落盘）")
    src.add_argument("--text", help="直接给定证据文本")
    src.add_argument("--stdin", action="store_true", help="从 stdin 读取证据全文")
    rws.add_parser("list")
    rr = rws.add_parser("read"); rr.add_argument("--name", required=True)

    a = ap.parse_args()
    out = None
    if a.cmd == "init":
        out = {"ok": True, "root": S.init()}
    elif a.cmd == "classes":
        out = S.list_classes(teacher_id=a.teacher)
    elif a.cmd == "teacher":
        if a.sub == "add":
            out = S.upsert_teacher(a.id, a.name, _loads(a.profile))
        else:
            out = S.get_teacher(a.id)
    elif a.cmd == "class":
        out = S.create_class(a.id, a.teacher, a.level, a.cohort, a.family)
    elif a.cmd == "student":
        out = S.create_student(a.id, a.class_id, a.name, external_ref=a.external)
    elif a.cmd == "lesson":
        out = S.add_lesson(a.class_id, a.id, a.date, a.topic, a.kp, a.scaffold, a.level, a.passrate)
    elif a.cmd == "obs":
        out = S.add_observation(a.class_id, a.student, a.id, _loads(a.dimension),
                                _loads(a.evidence), a.alignment, a.integrated)
    elif a.cmd == "query":
        out = S.query_reference(scaffold_type=a.scaffold, knowledge_point=a.kp, cognitive_level=a.level)
    elif a.cmd == "asset":
        if a.sub == "add":
            out = _run(S.add_asset, a.id, a.kind, a.title, a.file, subject=a.subject,
                       knowledge_point=a.kp, source_lesson=a.lesson,
                       params=_loads(a.params), tags=a.tags,
                       parent_asset=a.parent_asset, assembly=_loads(a.assembly) if a.assembly is not None else None)
        elif a.sub == "list":
            out = S.list_assets(kind=a.kind, knowledge_point=a.kp, subject=a.subject)
        elif a.sub == "get":
            out = S.get_asset(a.id)
        elif a.sub == "reuse":
            out = _run(S.reuse_asset, a.id)
        elif a.sub == "scan":
            out = S.scan_existing(dry_run=a.dry_run)
        elif a.sub == "suggest":
            out = _run(S.suggest_assets, knowledge_point=a.kp, kind=a.kind, subject=a.subject)
        elif a.sub == "compose":
            if a.spec_schema:
                out = S.compose_spec_schema()
            else:
                out = _run(S.compose_asset, _load_spec(a.spec, a.spec_file, a.spec_stdin))
    elif a.cmd == "raw":
        if a.sub == "save":
            text = sys.stdin.read() if a.stdin else (a.text if a.text is not None else Path(a.file).read_text(encoding="utf-8"))
            out = _run(S.save_raw_evidence, a.name, text)
        elif a.sub == "list":
            out = S.list_raw()
        elif a.sub == "read":
            out = _run(S.read_raw, a.name)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_run(main))