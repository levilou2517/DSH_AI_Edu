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

Agent 不直接碰文件；经此 CLI 或宿主服务访问 ~/.shiban/data。
"""
import argparse
import json
import sys

import shiban_store as S


def _loads(s, default=None):
    try:
        return json.loads(s) if s else (default or {})
    except json.JSONDecodeError:
        sys.stderr.write(f"[warn] 参数非 JSON，按字符串处理: {s}\n")
        return s


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
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())