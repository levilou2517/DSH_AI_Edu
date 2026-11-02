#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""师伴 Shiban · 教案渲染与校验模块（纯标准库，零第三方依赖）。

一份 lesson payload（schema = shiban.lesson/1）→ 两种体例的 Markdown / 自包含 HTML：

    template 版：完整十一章节 + 〇、基本信息（备课 / 校内评比）
    competition 版：无〇节，开篇为 教材行 + 章节行 + 一级标题 + 副标题 + 三列信息表（竞赛）

结构来源：framework/lesson-template/template-v1.md。
排版来源：书院杯已交付的 prince-print.css / md2html_prince.py（table-layout:fixed、
thead 跨页、中文字族分流、列宽类），但**不依赖 Mermaid 运行时**——设计思路与板书
一律用 <pre> ASCII/框线图输出。

公开 API：
    SCHEMA                   "shiban.lesson/1"
    empty_lesson()           -> dict
    validate(payload, strict=False) -> {"ok","errors","warnings"}
    render_markdown(payload, style="template") -> str
    render_html(payload, style="template", title=None) -> str
    render_cover_html(payload) -> str
    apply_section(payload, section_key, value) -> dict

命令行：
    python3 shiban_lesson.py                      # 自检（打印 OK）
    python3 shiban_lesson.py render lesson.json --style competition --out x.html
    python3 shiban_lesson.py validate lesson.json [--strict]
"""

import copy
import html
import json
import os
import re
from pathlib import Path

__all__ = [
    "SCHEMA",
    "SECTION_TITLES",
    "LIST_SECTIONS",
    "DIMENSIONS",
    "empty_lesson",
    "validate",
    "render_markdown",
    "render_html",
    "render_cover_html",
    "apply_section",
    "write_file",
]

SCHEMA = "shiban.lesson/1"

DIMENSIONS = ("生命观念", "科学思维", "科学探究", "社会责任")

# 章节键（与 payload 的一级键一一对应）。apply_section 只接受这些键。
SECTION_TITLES = {
    "meta": "〇、基本信息",
    "S1": "一、课标及教材分析",
    "S2": "二、学情分析",
    "S3": "三、教学重难点",
    "S4": "四、教学目标",
    "S5": "五、教学方法",
    "S6": "六、教学准备",
    "S7": "七、教学设计思路",
    "S8": "八、教学过程",
    "S9": "九、教学评价",
    "S10": "十、板书设计",
    "S11": "十一、教学创新点",
    "citations": "附录：引用",
    "controversy": "附录：争议点",
}

# 列表型章节（整节替换 / 重做时给 list）
LIST_SECTIONS = ("S4", "S5", "S8", "S11", "citations", "controversy")

# 章节 → 引用 section 前缀别名（兼容 "S1" / "S1.curriculum" / "一" 等写法）
_SECTION_ALIASES = {
    "S0": "meta", "0": "meta", "meta": "meta", "〇": "meta",
    "S1": "S1", "1": "S1", "一": "S1",
    "S2": "S2", "2": "S2", "二": "S2",
    "S3": "S3", "3": "S3", "三": "S3",
    "S4": "S4", "4": "S4", "四": "S4",
    "S5": "S5", "5": "S5", "五": "S5",
    "S6": "S6", "6": "S6", "六": "S6",
    "S7": "S7", "7": "S7", "七": "S7",
    "S8": "S8", "8": "S8", "八": "S8",
    "S9": "S9", "9": "S9", "九": "S9",
    "S10": "S10", "10": "S10", "十": "S10",
    "S11": "S11", "11": "S11", "十一": "S11",
}

_CN_NUM = "〇一二三四五六七八九十"
_CN_ORD = {"十": 10, "十一": 11, "十二": 12}


# ============================================================================
# 基础工具
# ============================================================================

def _s(value) -> str:
    """把任意值安全转成去掉首尾空白的字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (list, tuple)):
        parts = [_s(v) for v in value]
        return "；".join(p for p in parts if p)
    if isinstance(value, dict):
        parts = ["%s：%s" % (k, _s(v)) for k, v in value.items() if _s(v)]
        return "；".join(parts)
    return str(value).strip()


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _as_int(value, default=None):
    """尽量把 value 转成 int；失败返回 default。"""
    if _is_int(value):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        return int(value)
    return default


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _cn_num(n):
    """国际序数 → 中文序数（1..12）。"""
    if n == 0:
        return "〇"
    if 1 <= n <= 10:
        return _CN_NUM[n]
    if n == 11:
        return "十一"
    if n == 12:
        return "十二"
    return str(n)


# ---------------------------------------------------------------------------
# 行内 Markdown（自用极简版，替换原 md2html_prince.py 的 inline()）
# 先 escape，再处理 **bold** *em* `code`，避免注入。
# ---------------------------------------------------------------------------

def _inline(text) -> str:
    t = html.escape(_s(text).replace(_MD.PROSE, ""), quote=False)
    codes = []

    def _keep_code(m):
        codes.append(m.group(1))
        return "\x00CODE%d\x00" % (len(codes) - 1)

    t = re.sub(r"`([^`\n]+)`", _keep_code, t)
    t = re.sub(r"\*\*([^*\n]+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<em>\1</em>", t)
    for i, c in enumerate(codes):
        t = t.replace("\x00CODE%d\x00" % i, "<code>%s</code>" % c)
    return t


def _citation_ref(section: str, index: int = 1) -> str:
    """引用角标：S1.curriculum / S8.process[3] → 「[1]」。"""
    if re.search(r"\[\d+\]", section):
        return "[%d]" % index
    return ""


def _clip(text, n=30) -> str:
    t = _s(text).replace("\n", " ")
    return t[:n]


# ============================================================================
# 空 payload
# ============================================================================

def empty_lesson() -> dict:
    """返回一个空的 lesson payload：每个字段值给 "" 或 []，供 Agent 填充。"""
    return {
        "schema": SCHEMA,
        "meta": {
            "title": "",
            "subtitle": "",
            "grade": "",
            "textbook": "",
            "chapter": "",
            "course_type": "",
            "duration_min": 0,
            "class_desc": "",
            # 以下为可选项（封皮 / 页眉用）
            "teacher_name": "",
            "subject": "",
        },
        "core_question": "",
        "S1": {
            "curriculum": {
                "module": "",
                "big_idea": "",
                "important_idea": "",
                "subconcept": "",
                "achievement_req": "",
                "quality_level": "",
                "focus": "",
            },
            "textbook": {
                "position": "",
                "overview": "",
                "design_intent": "",
                "internal_role": "",
                "cross_links": [],
                "overall": "",
            },
        },
        "S2": {
            "general": {
                "cognitive_stage": "",
                "prior_knowledge": "",
                "thinking": "",
                "response": "",
            },
            "style": {
                "cognitive_mode": "",
                "cooperation": "",
                "preference": "",
                "response": "",
                "classroom_mgmt": "",
            },
            "starting": {
                "known": "",
                "preconceptions": [{"name": "", "evidence": "", "plan": ""}],
                "ladder": [],
            },
        },
        "S3": {
            "key_points": [],
            "difficulties": [],
            "difficulty_causes": [{"difficulty": "", "cause": ""}],
            "breakthrough": [{"difficulty": "", "strategy": ""}],
        },
        "S4": [
            {"id": "O1", "dimension": "生命观念", "on": "", "can": "",
             "develop": "", "assessable_sign": ""},
            {"id": "O2", "dimension": "科学思维", "on": "", "can": "",
             "develop": "", "assessable_sign": ""},
            {"id": "O3", "dimension": "科学探究", "on": "", "can": "",
             "develop": "", "assessable_sign": ""},
            {"id": "O4", "dimension": "社会责任", "on": "", "can": "",
             "develop": "", "assessable_sign": ""},
        ],
        "S5": [{"name": "", "basis": "", "how": "", "effect": ""}],
        "S6": {
            "environment": [],
            "student": [],
            "teacher_materials": [],
        },
        "S7": {
            "stages": [],
            "lines": {"situation": "", "knowledge": "", "literacy": ""},
            "core_idea": "",
        },
        "S8": [
            {"no": _cn_num(i), "name": "", "minutes": 0,
             "teacher_activity": [], "student_activity": [],
             "intent": "", "scaffolds": []}
            for i in range(1, 6)
        ],
        "S9": {
            "formative": {
                "participation": {
                    "weight": 20,
                    "rubric": {"A": "", "B": "", "C": "", "D": ""},
                },
                "objective_attainment": {
                    "weight": 30,
                    "rows": [
                        {"objective_id": "O%d" % i, "dimension": d, "target": ""}
                        for i, d in enumerate(DIMENSIONS, 1)
                    ],
                },
                "quick_check": [{"no": 1, "stem": "", "answer": "", "pitfalls": ""}],
            },
            "summative": {
                "weight": 50,
                "task": "",
                "requirements": [],
                "mapping": ["O1", "O2", "O3", "O4"],
            },
        },
        "S10": {
            "main": "",
            "side": "",
            "generative": "",
            "structure": {"type": "tree", "nodes": []},
        },
        "S11": [{"title": "", "what": "", "how": "", "effect": ""}],
        "citations": [],
        "controversy": [],
    }


# ============================================================================
# 校验
# ============================================================================

def _err(code, path, message):
    return {"code": code, "path": path, "message": message}


def _is_empty_section(payload: dict, key: str) -> bool:
    """章节是否为空（"必填章节为空"判定）。"""
    if key == "S1":
        return not any(_s(v) for v in _as_dict(payload.get("S1")).get("curriculum", {}).values())
    if key == "S2":
        s2 = _as_dict(payload.get("S2"))
        for sub in ("general", "style"):
            if any(_s(v) for v in _as_dict(s2.get(sub)).values()):
                return False
        st = _as_dict(s2.get("starting"))
        if _s(st.get("known")) or _as_list(st.get("ladder")) or _as_list(st.get("preconceptions")):
            return False
        return True
    if key in ("S4", "S5", "S8", "S11"):
        return not [x for x in _as_list(payload.get(key)) if _s(x)]
    if key == "S3":
        return not _as_list(_as_dict(payload.get("S3")).get("key_points"))
    if key == "S6":
        s6 = _as_dict(payload.get("S6"))
        return not any(_as_list(s6.get(k)) for k in ("environment", "student", "teacher_materials"))
    if key == "S7":
        s7 = _as_dict(payload.get("S7"))
        return not (_as_list(s7.get("stages")) or any(_s(v) for v in _as_dict(s7.get("lines")).values()))
    if key == "S9":
        s9 = _as_dict(payload.get("S9"))
        fo = _as_dict(s9.get("formative"))
        su = _as_dict(s9.get("summative"))
        return not (any(_s(v) for v in _as_dict(fo.get("participation")).get("rubric", {}).values())
                    or _as_list(_as_dict(fo.get("objective_attainment")).get("rows"))
                    or _s(su.get("task")))
    if key == "S10":
        s10 = _as_dict(payload.get("S10"))
        return not (_s(s10.get("main")) or _as_list(_as_dict(s10.get("structure")).get("nodes")))
    return not payload.get(key)


def _collect_citations(payload: dict) -> list:
    """汇总全局与各章节内嵌的引用。"""
    found = []
    for idx, c in enumerate(_as_list(payload.get("citations"))):
        if isinstance(c, dict):
            if _s(c.get("corpus_id")) and not (c.get("book_page") in (None, "")):
                found.append(("citations[%d]" % idx, c))
    for key in ("S1", "S2", "S3", "S5", "S7", "S9"):
        sec = payload.get(key)
        stack = [(key, sec)]
        while stack:
            path, node = stack.pop()
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "citation":
                        for j, c in enumerate(_as_list(v)):
                            if isinstance(c, dict) and _s(c.get("corpus_id")) \
                                    and not (c.get("book_page") in (None, "")):
                                found.append(("%s.citation[%d]" % (path, j), c))
                    else:
                        stack.append(("%s.%s" % (path, k), v))
            elif isinstance(node, list):
                for j, v in enumerate(node):
                    stack.append(("%s[%d]" % (path, j), v))
    return found


def validate(payload: dict, strict: bool = False) -> dict:
    """校验 lesson payload。

    返回 {"ok": bool, "errors": [{"code","path","message"}], "warnings": [...]}。
    所有条目都带 path（如 S9.formative.objective_attainment.rows[1].objective_id）。
    """
    errors, warnings = [], []
    if not isinstance(payload, dict):
        return {"ok": False,
                "errors": [_err("E_SCHEMA_VERSION", "", "payload 必须是 JSON 对象")],
                "warnings": []}

    # ---- schema ----
    if payload.get("schema") != SCHEMA:
        got = payload.get("schema")
        errors.append(_err("E_SCHEMA_VERSION", "schema",
                           "缺少 schema 或版本不是 %s（当前：%s）" % (SCHEMA, json.dumps(got, ensure_ascii=False))))

    # ---- 必填章节 ----
    for key in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"):
        if _is_empty_section(payload, key):
            errors.append(_err("E_SECTION_MISSING", key,
                               "章节「%s」为空" % SECTION_TITLES[key]))

    # ---- S4 目标 ----
    s4 = _as_list(payload.get("S4"))
    objective_ids = []
    if not (3 <= len(s4) <= 4):
        errors.append(_err("E_OBJECTIVES_COUNT", "S4",
                           "教学目标应为 3—4 条，当前 %d 条" % len(s4)))
    for i, obj in enumerate(s4):
        obj = _as_dict(obj)
        dim = _s(obj.get("dimension"))
        oid = _s(obj.get("id")) or "O%d" % (i + 1)
        # 允许 "生命观念（结构与功能观）" 这类写法：取前缀匹配
        if dim not in DIMENSIONS and not any(dim.startswith(d) for d in DIMENSIONS):
            errors.append(_err("E_OBJECTIVE_DIM", "S4[%d].dimension" % i,
                               "素养维度「%s」不在 %s 之内" % (dim, "、".join(DIMENSIONS))))
        if not dim:
            errors[-1]["message"] = "素养维度为空，应为 %s 之一" % "、".join(DIMENSIONS)
        if _s(obj.get("id")) and _s(obj.get("id")) != "O%d" % (i + 1):
            warnings.append(_err("W_OBJECTIVE_ID_ORDER", "S4[%d].id" % i,
                                 "目标编号「%s」与位置不符（建议按 O1—O4 顺序编号）" % _s(obj.get("id"))))
        objective_ids.append(oid)
    dup = sorted({x for x in objective_ids if objective_ids.count(x) > 1})
    if dup:
        errors.append(_err("E_OBJECTIVE_DUPLICATE", "S4", "教学目标编号重复：%s" % "、".join(dup)))

    # ---- S9 形成性 · 目标达成 ----
    s9 = _as_dict(payload.get("S9"))
    fo = _as_dict(s9.get("formative"))
    oa = _as_dict(fo.get("objective_attainment"))
    rows = _as_list(oa.get("rows"))
    row_ids = []
    for j, r in enumerate(rows):
        r = _as_dict(r)
        rid = _s(r.get("objective_id"))
        row_ids.append(rid)
        if not rid:
            errors.append(_err("E_ATTAINMENT_MISMATCH",
                               "S9.formative.objective_attainment.rows[%d].objective_id" % j,
                               "目标达成评价行缺少 objective_id"))
        if _s(r.get("dimension")) and _s(r.get("dimension")) not in DIMENSIONS:
            warnings.append(_err("W_DIMENSION_UNKNOWN",
                                 "S9.formative.objective_attainment.rows[%d].dimension" % j,
                                 "素养维度「%s」不规范" % _s(r.get("dimension"))))
    missing = [x for x in objective_ids if x not in row_ids]
    extra = [x for x in row_ids if x and x not in objective_ids]
    if missing or extra or len(rows) != len(objective_ids):
        msg = "目标达成评价与教学目标不一一对应"
        if missing:
            msg += "；缺少：%s" % "、".join(missing)
        if extra:
            msg += "；多出：%s" % "、".join(x for x in extra if x)
        msg += "（S4 = %s，rows = %s）" % (objective_ids, row_ids)
        errors.append(_err("E_ATTAINMENT_MISMATCH", "S9.formative.objective_attainment.rows", msg))

    # ---- S9 终结性 · mapping ----
    su = _as_dict(s9.get("summative"))
    mapping = [_s(x) for x in _as_list(su.get("mapping")) if _s(x)]
    bad = [x for x in mapping if x not in objective_ids]
    if bad:
        errors.append(_err("E_SUMMATIVE_MAPPING", "S9.summative.mapping",
                           "终结性评价引用了不存在的目标编号：%s" % "、".join(bad)))
    elif not mapping:
        errors.append(_err("E_SUMMATIVE_MAPPING", "S9.summative.mapping",
                           "终结性评价未声明对应目标（mapping 为空）"))

    # ---- 权重 ----
    weights = []
    for path, w in (("S9.formative.participation.weight", _as_dict(fo.get("participation")).get("weight")),
                    ("S9.formative.objective_attainment.weight", oa.get("weight")),
                    ("S9.summative.weight", su.get("weight"))):
        wi = _as_int(w)
        if wi is None:
            warnings.append(_err("W_WEIGHT_INVALID", path, "权重不是整数：%r" % (w,)))
        else:
            weights.append(wi)
    if len(weights) == 3 and sum(weights) != 100:
        warnings.append(_err("W_WEIGHT_SUM", "S9.formative/summative",
                             "三项评价权重之和为 %d，建议为 100" % sum(weights)))

    # ---- S8 时长 ----
    s8 = _as_list(payload.get("S8"))
    total = 0
    for i, step in enumerate(s8):
        step = _as_dict(step)
        m = _as_int(step.get("minutes"), None)
        if m is None:
            errors.append(_err("E_MINUTES_INVALID", "S8[%d].minutes" % i,
                               "环节时长不是整数：%r" % (step.get("minutes"),)))
            m = 0
        else:
            total += m
        if m == 0:
            warnings.append(_err("W_MINUTES_UNEVEN", "S8[%d].minutes" % i,
                                 "环节「%s」时长为 0" % (_s(step.get("name")) or i + 1)))
    duration = _as_int(_as_dict(payload.get("meta")).get("duration_min"))
    if duration is None:
        errors.append(_err("E_MINUTES_SUM", "meta.duration_min",
                           "meta.duration_min 缺失或不是整数；环节时长合计 %d" % total))
    elif total != duration:
        errors.append(_err("E_MINUTES_SUM", "S8",
                           "环节时长合计 %d min ≠ 课时 %d min（差 %+d）" % (total, duration, duration - total)))

    # ---- 可选插槽的软提示 ----
    s3 = _as_dict(payload.get("S3"))
    if _as_list(s3.get("difficulties")) and not _as_list(s3.get("difficulty_causes")):
        warnings.append(_err("W_DIFFICULTY_NO_CAUSE", "S3.difficulty_causes",
                             "有教学难点但未写难点成因分析（第三节 3、可选）"))
    if not _as_list(payload.get("controversy")):
        warnings.append(_err("W_NO_CONTROVERSY", "controversy",
                             "未记录任何争议点（不代表错，仅提示：取舍要显式）"))
    if not _as_list(fo.get("quick_check")):
        warnings.append(_err("W_NO_QUICK_CHECK", "S9.formative.quick_check",
                             "未设课堂即时检测（随堂 2—3 题）"))
    part = _as_dict(fo.get("participation"))
    rubric = _as_dict(part.get("rubric"))
    if any(g not in rubric for g in ("A", "B", "C", "D")):
        warnings.append(_err("W_PARTICIPATION_RUBRIC", "S9.formative.participation.rubric",
                             "课堂参与评价应为 A/B/C/D 四级且都有描述"))
    if not _as_list(_as_dict(payload.get("S3")).get("breakthrough")):
        warnings.append(_err("W_NO_BREAKTHROUGH", "S3.breakthrough",
                             "未写突破策略（第三节 4、可选）"))
    if not _as_list(_as_dict(payload.get("S7")).get("stages")):
        warnings.append(_err("W_FLOW_NO_STAGES", "S7.stages",
                             "教学设计思路未给环节串（将按第八节环节自动生成图）"))
    if not _s(_as_dict(payload.get("meta")).get("teacher_name")):
        warnings.append(_err("W_NO_TEACHER_NAME", "meta.teacher_name",
                             "封皮缺 meta.teacher_name（渲染为空白下划线）"))

    # ---- 引用 ----
    cites = _collect_citations(payload)
    if strict and not cites:
        errors.append(_err("E_CITATION_REQUIRED", "citations",
                           "strict 模式下必须至少一条可核查引用（corpus_id + book_page）"))
    else:
        for path, c in _collect_citations(payload):
            if c.get("book_page") is None:
                warnings.append(_err("W_CITATION_NO_PAGE", path + ".book_page",
                                     "引用无页码，无法用 corpus read 复现"))

    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ============================================================================
# 派生数据（渲染共用）
# ============================================================================

def _meta(p):
    return _as_dict(p.get("meta"))


def _title(p) -> str:
    return _s(_meta(p).get("title"))


def _book_title(p) -> str:
    return "《%s》教学设计" % (_title(p) or "课题")


def _objectives(p) -> list:
    out = []
    for i, o in enumerate(_as_list(p.get("S4"))):
        o = _as_dict(o)
        out.append({
            "id": _s(o.get("id")) or "O%d" % (i + 1),
            "dimension": _s(o.get("dimension")),
            "on": _s(o.get("on")),
            "can": _s(o.get("can")),
            "develop": _s(o.get("develop")),
            "assessable_sign": _s(o.get("assessable_sign")),
        })
    return out


def _objective_text(o: dict, short: bool = False) -> str:
    """'on' + 'can' + 'develop' 拼成目标句；皆空则回落到 assessable_sign。"""
    on, can, dev = o["on"], o["can"], o["develop"]
    if not any((on, can, dev)):
        return o["assessable_sign"]
    parts = []
    if on:
        parts.append("通过%s" % on)
    if can:
        parts.append("能%s" % can)
    if dev:
        parts.append("发展%s" % dev)
    return "，".join(parts) + "。"


def _process(p) -> list:
    out = []
    for i, step in enumerate(_as_list(p.get("S8"))):
        step = _as_dict(step)
        out.append({
            "no": _s(step.get("no")) or _cn_num(i + 1),
            "name": _s(step.get("name")),
            "minutes": _as_int(step.get("minutes"), 0) or 0,
            "teacher_activity": [x for x in (_s(v) for v in _as_list(step.get("teacher_activity"))) if x],
            "student_activity": [x for x in (_s(v) for v in _as_list(step.get("student_activity"))) if x],
            "intent": _s(step.get("intent")),
            "scaffolds": [x for x in (_s(v) for v in _as_list(step.get("scaffolds"))) if x],
        })
    return out


def _stage_labels(p) -> list:
    """七、教学设计思路的环节串：S7.stages 优先，缺省由 S8 生成。"""
    stages = [_s(x) for x in _as_list(_as_dict(p.get("S7")).get("stages")) if _s(x)]
    if stages:
        return stages
    return [("%s%s（%d min）" % (s["no"], ("、" + s["name"]) if s["name"] else "", s["minutes"])
             or s["no"]) for s in _process(p)]


def _flow_ascii(p) -> str:
    stages = _stage_labels(p)
    if not stages:
        return "（尚未填写教学设计思路）"
    width = max(len(x) for x in stages) + 4
    lines = []
    for i, st in enumerate(stages):
        label = "【%s】" % st if not st.startswith("【") else st
        lines.append("┌" + "─" * width + "┐")
        lines.append("│ " + label + " " * (width - 2 - len(label)) + " │")
        lines.append("└" + "─" * width + "┘")
        if i < len(stages) - 1:
            pad = " " * (width // 2)
            lines.append(pad + "│")
            lines.append(pad + "↓")
    return "\n".join(lines)


def _dw(text) -> int:
    """显示宽度：CJK 与全角符号按 2 计（板书框图对齐用）。"""
    w = 0
    for ch in _s(text):
        w += 2 if ("\u1100" <= ch <= "\u115f" or "\u2e80" <= ch <= "\ua4cf"
                   or "\uac00" <= ch <= "\ud7a3" or "\uf900" <= ch <= "\ufaff"
                   or "\ufe30" <= ch <= "\ufe4f" or "\uff00" <= ch <= "\uff60"
                   or "\uffe0" <= ch <= "\uffe6") else 1
    return w


def _pad(text, width) -> tuple:
    """按显示宽度右补空格，并把超宽部分截断，返回 (text, 实际宽度)。"""
    text = _s(text)
    out, w = "", 0
    for ch in text:
        cw = _dw(ch)
        if w + cw > width:
            break
        out += ch
        w += cw
    return out + " " * (width - w), w


def _board_ascii(p) -> str:
    """十、板书设计的 ASCII/框线图（不依赖 Mermaid）。

    S10.structure.type：
      tree  —— 层层分支的知识树（默认）；
      frame —— 方框框架图，页脚落核心观念；
      table —— nodes 里每条用「|」分列，画成对照表。
    """
    s10 = _as_dict(p.get("S10"))
    st = _as_dict(s10.get("structure"))
    nodes = [_s(x) for x in _as_list(st.get("nodes")) if _s(x)]
    kind = _s(st.get("type")) or "tree"
    lines7 = _as_dict(_as_dict(p.get("S7")).get("lines"))
    core = _s(_as_dict(p.get("S7")).get("core_idea"))
    if not nodes and kind == "tree":
        nodes = _stage_labels(p)
    if not nodes:
        return "（尚未填写板书结构）"

    title = "【%s】" % (_title(p) or "课题")
    body = []
    indent = "  "

    if kind == "table":
        rows = [[c.strip() for c in n.split("|")] for n in nodes]
        ncol = max(len(r) for r in rows)
        rows = [r + [""] * (ncol - len(r)) for r in rows]
        widths = [max(_dw(r[c]) for r in rows) + 2 for c in range(ncol)]
        sep = "+" + "+".join("-" * w for w in widths) + "+"
        body.append(title)
        body.append(sep)
        for r in rows:
            body.append("|" + "|".join(_pad(c, w - 1)[0] for c, w in zip(r, widths)) + "|")
            body.append(sep)
        if core:
            body.append("★ 核心观念：" + core)
        return "\n".join(body)

    if kind == "frame":
        content = list(nodes)
        if core:
            content.append("★ 核心观念：" + core)
        topic = _s(lines7.get("knowledge")) or core
        width = max([_dw(c) for c in content] + [_dw(title), _dw(topic), 30]) + 2
        top = "┌" + "─" * width + "┐"
        body.append(top)
        left = max(0, (width - 2) - _dw(title)) // 2
        body.append("│ " + " " * left + _pad(title, width - 2 - left)[0] + " │")
        body.append("├" + "─" * width + "┤")
        for c in content:
            body.append("│ " + _pad(c, width - 2)[0] + " │")
        body.append("└" + "─" * width + "┘")
        if topic and topic != core:
            body.append(topic)
        return "\n".join(body)

    # tree
    children = [n.lstrip("└├─-·> ") for n in nodes if n.strip()[:2] in ("└─", "├─", "- ", "· ")]
    roots = children or nodes
    body.append(indent + title)
    for i, n in enumerate(roots):
        last = i == len(roots) - 1
        body.append(indent + ("└─ " if last else "├─ ") + n)
        if last and core:
            body.append(indent + "   └─ ★ 核心观念：" + core)
    return "\n".join(body)


def _citations_for(p, section: str) -> list:
    """取属于某章节的引用。section 形如 'S8.process[4]'、'S1.curriculum'、'S1'。"""
    key = _s(section).split(".")[0].split("[")[0]
    key = _SECTION_ALIASES.get(key, key)
    out = []
    for i, c in enumerate(_as_list(p.get("citations"))):
        if not isinstance(c, dict):
            continue
        sk = _s(c.get("section"))
        ck = _SECTION_ALIASES.get(sk.split(".")[0].split("[")[0], sk.split(".")[0].split("[")[0])
        if key and ck == key:
            out.append((_s(c.get("section")) or "S%d" % i, c))
    # 章节内嵌 citation 字段
    node = p.get(key) if key in p else None
    stack = [(key, node)]
    while stack:
        path, nd = stack.pop()
        if isinstance(nd, dict):
            for k, v in nd.items():
                if k == "citation":
                    for c in _as_list(v):
                        if isinstance(c, dict):
                            out.append((path, c))
                else:
                    stack.append(("%s.%s" % (path, k), v))
        elif isinstance(nd, list):
            for j, v in enumerate(nd):
                stack.append(("%s[%d]" % (path, j), v))
    return out


def _controversy_lines_md(p, prefix: str) -> list:
    """某章节内的争议点提示行（Markdown 用，散文行，带 ※ 标记）。"""
    out = []
    for it in _controversy_for(p, prefix):
        txt = "※ 争议：%s" % it["issue"]
        if it["my_view"]:
            txt += "（我的取舍：%s）" % it["my_view"]
        out.append("- " + txt + _MD.PROSE)
    return out


def _cite_line(cites) -> str:
    if not cites:
        return ""
    parts = []
    seen = set()
    for sec, c in cites:
        cid = _s(c.get("corpus_id"))
        page = c.get("book_page")
        quote = _clip(c.get("quote"), 30)
        item = "%s P.%s「%s」" % (cid, page, quote)
        if item in seen:
            continue
        seen.add(item)
        ref = _citation_ref(sec, len(parts) + 1)
        parts.append((ref + " " if ref else "") + item)
    return "> 依据：" + "；".join(parts) + _MD.PROSE


def _controversy_for(p, prefix: str) -> list:
    out = []
    for i, c in enumerate(_as_list(p.get("controversy"))):
        if not isinstance(c, dict):
            continue
        sec = _s(c.get("section"))
        if not sec:
            continue
        sk = _SECTION_ALIASES.get(sec.split(".")[0].split("[")[0], sec.split(".")[0])
        if sk == prefix:
            out.append({"index": i + 1, "section": sec, "issue": _s(c.get("issue")),
                        "my_view": _s(c.get("my_view"))})
    return out


# ============================================================================
# Markdown 渲染
# ============================================================================

class _MD:
    """极简 Markdown 构造器。

    行内约定：以「\x01」结尾的行 = 散文行（列表项或子项），相邻散文行之间不留空行；
    其余为块行（标题、表格、引用、代码块）。出口规则（text()）：
      · 块行之后、下一个非空行之前必空一行；
      · 散文行之后紧跟「块行」或「列表尚未开始的新段」时补一行空行；
      · 连续空行压缩为一行，首尾空行去掉。
    """

    PROSE = "\x01"

    def __init__(self):
        self.lines = []

    def add(self, *lines):
        for ln in lines:
            if ln is not None:
                self.lines.append(ln if isinstance(ln, str) else str(ln))
        return self

    def prose(self, text, depth=0):
        """散文行（列表项 / 缩进子项）：与前一行不夹空行；depth 为缩进层数。"""
        t = _s(text)
        if t:
            self.lines.append("  " * int(depth) + t + self.PROSE)
        return self

    def bullet(self, text, depth=0):
        return self.prose("- " + _s(text), depth)

    def item(self, number, text, depth=0):
        return self.prose("%s. %s" % (number, _s(text)), depth)

    def sub(self, depth, text):
        return self.prose("- " + _s(text), depth)

    def blank_gap(self):
        if self.lines and self.lines[-1] != "":
            self.lines.append("")
        return self

    def h(self, level, text):
        return self.add("#" * level + " " + _s(text))

    def para(self, text):
        t = _s(text)
        if t:
            self.lines.append(t)
        return self

    def num(self, start, items):
        for k, it in enumerate(items):
            self.item(start + k, it)
        return self

    def table(self, header, rows):
        if not rows:
            return self
        self.add("| " + " | ".join(header) + " |")
        self.add("|" + "|".join(["---"] * len(header)) + "|")
        for r in rows:
            cells = []
            for c in r:
                s = c if isinstance(c, str) else _s(c)
                cells.append(s.replace("\n", "<br>").replace("|", "\\|"))
            self.add("| " + " | ".join(cells) + " |")
        return self

    def text(self):
        rows = []
        for ln in self.lines:
            if ln.endswith(self.PROSE):
                rows.append([ln[:-1], True])
            else:
                rows.append([ln, False])
        if rows:
            rows[-1][1] = False       # 末行总按块处理，保证文件以换行结束

        def indent_of(ln):
            return len(ln) - len(ln.lstrip(" "))

        GAP_BLOCKS = ("|", "```", ">")

        def zone(ln):
            for prefix in GAP_BLOCKS:
                if ln.startswith(prefix):
                    return prefix
            return ""

        # 拼接空行：列表项之间空一行（原模板与成品均为“松列表”），子项紧随其父项
        out = []
        for i, (ln, prose) in enumerate(rows):
            out.append(ln)
            if not ln or i + 1 >= len(rows):
                continue
            nxt, nxt_prose = rows[i + 1]
            zi, zn = zone(ln), zone(nxt)
            if zi or zn:
                if not nxt or zi != zn:
                    out.append("")            # 表格 / 代码块 / 引用两侧必空行，同区之内不空
                continue
            ind, nind = indent_of(ln), indent_of(nxt)
            next_is_list = nxt_prose and (nxt.startswith("- ") or bool(re.match(r"\d+\. ", nxt)))
            gap = not prose                                        # 块行之后总是空行
            if prose and nxt_prose and next_is_list and nind > ind:
                gap = False                                        # 进入子项：紧随父项
            elif prose and nxt_prose and next_is_list:
                gap = True                                         # 回到同级或另起一组：空一行
            if gap:
                out.append("")

        merged = []
        for ln in out:
            if ln == "" and (not merged or merged[-1] == ""):
                continue
            merged.append(ln)
        while merged and merged[-1] == "":
            merged.pop()
        merged.insert(0, "<!-- 由 shiban_lesson.py 生成；内容以 lesson.json 为准，请勿手改 -->")
        return "\n".join(merged) + "\n"


def _difficulty_label(value, index) -> str:
    """难点成因 / 突破策略里的 difficulty：'难点（1）' / '1' / '运用演绎推理……' → 可拼接的标签。"""
    t = _s(value)
    if not t:
        return "（%d）" % index
    mt = re.fullmatch(r"难点\s*[（(]?\s*(\d+|[一二三四五六七八九十]+)\s*[）)]?", t)
    if mt:
        return "（%s）" % mt.group(1)
    if re.fullmatch(r"\d+|[一二三四五六七八九十]+", t):
        return "（%s）" % t
    return "（%s）" % t


def _meta_rows(p) -> list:
    """〇、基本信息表（Markdown / HTML 共用）：[(项目, 内容)]。"""
    meta = _meta(p)
    rows = [
        ("课题名称", _s(meta.get("title"))),
        ("副标题/教学主张", _s(meta.get("subtitle"))),
        ("授课年级", _s(meta.get("grade"))),
        ("教材版本及位置", " ".join(x for x in (_s(meta.get("textbook")), _s(meta.get("chapter"))) if x)),
        ("课型", _s(meta.get("course_type"))),
        ("课时与时长", ("%s min" % _s(meta.get("duration_min"))) if _s(meta.get("duration_min")) else ""),
        ("授课对象", _s(meta.get("class_desc"))),
    ]
    if _s(meta.get("teacher_name")):
        rows.append(("授课教师", _s(meta.get("teacher_name"))))
    return rows


def _md_meta_table(m: _MD, p):
    m.table(["项目", "内容"], _meta_rows(p))


def _render_s1(m: _MD, p):
    s1 = _as_dict(p.get("S1"))
    cur = _as_dict(s1.get("curriculum"))
    m.h(2, "一、课标及教材分析")
    m.h(3, "1、课标分析")
    if _s(cur.get("module")):
        m.bullet("**所属模块**：%s" % _s(cur.get("module")))
    hierarchy = [(lb, cur.get(k)) for k, lb in (("big_idea", "大概念"), ("important_idea", "重要概念"),
                                                ("subconcept", "次位概念")) if _s(cur.get(k))]
    if hierarchy:
        m.bullet("**概念层级**：")
        for lb, v in hierarchy:
            m.prose("- %s：%s" % (lb, _s(v)), 2)
    for key, label in (("achievement_req", "学业要求"), ("quality_level", "学业质量水平定位"),
                       ("focus", "课标对本课的具体指向")):
        if _s(cur.get(key)):
            m.bullet("**%s**：%s" % (label, _s(cur.get(key))))
    m.para(_cite_line(_citations_for(p, "S1.curriculum")))
    for line in _controversy_lines_md(p, "S1"):
        m.add(line)

    tb = _as_dict(s1.get("textbook"))
    m.h(3, "2、教材分析")
    for key, label in (("position", "教材位置"), ("overview", "本节内容概述"),
                       ("design_intent", "编排意图"), ("internal_role", "章节内部地位"),
                       ("overall", "总体定位")):
        if _s(tb.get(key)):
            m.bullet("**%s**：%s" % (label, _s(tb.get(key))))
    links = [_s(x) for x in _as_list(tb.get("cross_links")) if _s(x)]
    if links:
        m.bullet("**跨章节/跨模块联系**：")
        for x in links:
            m.prose("- " + x, 2)
    m.para(_cite_line(_citations_for(p, "S1.textbook")))


def _render_s2(m: _MD, p):
    s2 = _as_dict(p.get("S2"))
    m.h(2, "二、学情分析")
    for sub, title, fields in (
        ("general", "1、一般特征分析",
         (("cognitive_stage", "认知发展阶段"), ("prior_knowledge", "已有知识基础"),
          ("thinking", "思维与能力特点"), ("response", "教学对策"))),
        ("style", "2、学习风格分析",
         (("cognitive_mode", "认知方式"), ("cooperation", "合作倾向"), ("preference", "学习偏好"),
          ("response", "教学对策"), ("classroom_mgmt", "课堂管理预案"))),
    ):
        src = _as_dict(s2.get(sub))
        m.h(3, title)
        for key, label in fields:
            if _s(src.get(key)):
                m.bullet("**%s**：%s" % (label, _s(src.get(key))))
        cites = _citations_for(p, "S2.%s" % sub)
        m.para(_cite_line(cites))

    st = _as_dict(s2.get("starting"))
    m.h(3, "3、学习起点分析")
    if _s(st.get("known")):
        m.bullet("**已知**：%s" % _s(st.get("known")))
    precs = [x for x in _as_list(st.get("preconceptions")) if isinstance(x, dict) and _s(x.get("name"))]
    if precs:
        m.bullet("**认知难点（前科学概念）**：")
        for i, x in enumerate(precs, 1):
            m.prose("- 前概念%d：%s" % (i, _s(x.get("name"))), 2)
            if _s(x.get("evidence")):
                m.prose("- 证据：%s" % _s(x.get("evidence")), 4)
            if _s(x.get("plan")):
                m.prose("- 对策：%s" % _s(x.get("plan")), 4)
    ladder = [_s(x) for x in _as_list(st.get("ladder")) if _s(x)]
    if ladder:
        m.bullet("**认知阶梯**：%s" % " → ".join(ladder))
    m.para(_cite_line(_citations_for(p, "S2.starting")))


def _render_s3(m: _MD, p):
    s3 = _as_dict(p.get("S3"))
    m.h(2, "三、教学重难点")
    m.h(3, "1、教学重点")
    m.num(1, _as_list(s3.get("key_points")))
    m.h(3, "2、教学难点")
    m.num(1, [(x if not isinstance(x, dict) else _s(x.get("text")) or _s(x)) for x in _as_list(s3.get("difficulties"))])
    causes = [x for x in _as_list(s3.get("difficulty_causes")) if isinstance(x, dict) and (_s(x.get("difficulty")) or _s(x.get("cause")))]
    if causes:
        m.h(3, "3、难点成因分析（可选）")
        for i, x in enumerate(causes, 1):
            m.bullet("难点%s的成因在于：%s" % (_difficulty_label(x.get("difficulty"), i), _s(x.get("cause"))))
    brk = [x for x in _as_list(s3.get("breakthrough")) if isinstance(x, dict) and (_s(x.get("difficulty")) or _s(x.get("strategy")))]
    if brk:
        m.h(3, "4、突破策略（可选）")
        for i, x in enumerate(brk, 1):
            m.bullet("针对难点%s %s" % (_difficulty_label(x.get("difficulty"), i), _s(x.get("strategy"))))
    for line in _controversy_lines_md(p, "S3"):
        m.add(line)
    m.para(_cite_line(_citations_for(p, "S3")))


def _render_s4(m: _MD, p):
    m.h(2, "四、教学目标")
    objs = _objectives(p)
    for i, o in enumerate(objs, 1):
        m.bullet("**%s（%s）** %s" % (o["id"], o["dimension"], _objective_text(o)))
    signs = [(o["id"], o["assessable_sign"]) for o in objs if o["assessable_sign"]]
    for oid, sign in signs:
        m.prose("- %s 达成标志：%s" % (oid, sign), 2)
    for line in _controversy_lines_md(p, "S4"):
        m.add(line)
    m.para(_cite_line(_citations_for(p, "S4")))


def _render_s5(m: _MD, p):
    m.h(2, "五、教学方法")
    for i, x in enumerate(_as_list(p.get("S5")), 1):
        if not isinstance(x, dict):
            if _s(x):
                m.item(i, "**%s**" % _s(x))
            continue
        name = _s(x.get("name")) or "方法%d" % i
        m.item(i, "**%s**" % name)
        for key, label in (("basis", "依据"), ("how", "做法"), ("effect", "作用")):
            if _s(x.get(key)):
                m.prose("- %s：%s" % (label, _s(x.get(key))), 4)
    m.para(_cite_line(_citations_for(p, "S5")))


def _render_s6(m: _MD, p):
    s6 = _as_dict(p.get("S6"))
    m.h(2, "六、教学准备")
    for key, title in (("environment", "1、教学环境"), ("student", "2、学生准备"),
                       ("teacher_materials", "3、教师教具准备")):
        m.h(3, title)
        m.num(1, _as_list(s6.get(key)))


def _render_s7(m: _MD, p):
    s7 = _as_dict(p.get("S7"))
    lines = _as_dict(s7.get("lines"))
    m.h(2, "七、教学设计思路")
    m.add("```text")
    m.add(_flow_ascii(p))
    m.add("```")
    m.prose("- **情境主线**：%s" % (_s(lines.get("situation")) or "（未填）"))
    m.prose("- **知识主线**：%s" % (_s(lines.get("knowledge")) or "（未填）"))
    m.prose("- **素养主线**：%s" % (_s(lines.get("literacy")) or "（未填）"))
    if _s(s7.get("core_idea")):
        m.prose("- **核心观念**：%s" % _s(s7.get("core_idea")))
    m.para(_cite_line(_citations_for(p, "S7")))


def _render_s8(m: _MD, p):
    m.h(2, "八、教学过程")
    steps = _process(p)
    rows = []
    for s in steps:
        label = "**%s、%s**<br>（%d min）" % (s["no"], s["name"], s["minutes"])
        rows.append([
            label,
            "<br>".join(s["teacher_activity"]),
            "<br>".join(s["student_activity"]),
            s["intent"],
        ])
    m.table(["教学环节", "教师活动", "学生活动", "设计意图"], rows)
    total = sum(s["minutes"] for s in steps)
    scaffolds = [(s["no"], x) for s in steps for x in s["scaffolds"]]
    for no, x in scaffolds:
        m.bullet("**支架（环节%s）**：%s" % (no, x))
    m.add("> 时间分配：合计 %d min。" % total)
    m.para(_cite_line(_citations_for(p, "S8")))


def _render_s9(m: _MD, p):
    s9 = _as_dict(p.get("S9"))
    fo = _as_dict(s9.get("formative"))
    su = _as_dict(s9.get("summative"))
    part = _as_dict(fo.get("participation"))
    oa = _as_dict(fo.get("objective_attainment"))
    weights = "参与 %s%% + 目标达成 %s%% + 终结性 %s%%" % (
        _s(part.get("weight")) or "?", _s(oa.get("weight")) or "?", _s(su.get("weight")) or "?")
    m.h(2, "九、教学评价")
    m.h(3, "1、形成性评价")
    m.para("权重：%s。" % weights)
    m.para("**（1）课堂参与评价（%s%%）**" % (_s(part.get("weight")) or ""))
    rubric = _as_dict(part.get("rubric"))
    m.table(["等级", "具体表现"], [(g, rubric.get(g)) for g in ("A", "B", "C", "D") if _s(rubric.get(g))])

    m.para("**（2）目标达成评价（%s%%）**" % (_s(oa.get("weight")) or ""))
    m.para("等级：A—完全达成、B—部分达成、C—基本达成、D—未达成。每一行对应一条教学目标。")
    objs = {o["id"]: o for o in _objectives(p)}
    rows = []
    for r in _as_list(oa.get("rows")):
        r = _as_dict(r)
        oid = _s(r.get("objective_id"))
        dim = _s(r.get("dimension")) or (objs.get(oid, {}).get("dimension") or "")
        rows.append([oid, dim, _s(r.get("target")), "", "", "", ""])
    m.table(["编号", "核心素养", "目标达成表现", "A", "B", "C", "D"], rows)

    qc = [x for x in _as_list(fo.get("quick_check")) if isinstance(x, dict) and (_s(x.get("stem")) or _s(x.get("answer")))]
    if qc:
        m.para("**（3）课堂即时检测（随堂 %d 题）**" % len(qc))
        qrows = [[_s(x.get("no")) or str(i), x.get("stem"), x.get("answer"), x.get("pitfalls")]
                 for i, x in enumerate(qc, 1)]
        m.table(["题号", "题目", "参考答案", "学生易错预估与应对"], qrows)

    m.h(3, "2、终结性评价")
    if _s(su.get("task")):
        m.para("**任务**：%s" % _s(su.get("task")))
    reqs = _as_list(su.get("requirements"))
    if reqs:
        m.para("**要求**：")
        m.num(1, reqs)
    mapping = [_s(x) for x in _as_list(su.get("mapping")) if _s(x)]
    if mapping:
        m.bullet("**对应目标**：%s" % "、".join(mapping))
    m.para(_cite_line(_citations_for(p, "S9")))


def _render_s10(m: _MD, p):
    s10 = _as_dict(p.get("S10"))
    m.h(2, "十、板书设计")
    m.add("```text")
    for ln in _board_ascii(p).split("\n"):
        m.add(ln)
    m.add("```")
    for key, label in (("main", "主板书"), ("side", "副板书"), ("generative", "生成性板书")):
        if _s(s10.get(key)):
            m.bullet("**%s**：%s" % (label, _s(s10.get(key))))
    m.para(_cite_line(_citations_for(p, "S10")))


def _render_s11(m: _MD, p):
    m.h(2, "十一、教学创新点")
    for i, x in enumerate(_as_list(p.get("S11")), 1):
        if not isinstance(x, dict):
            if _s(x):
                m.item(i, _s(x))
            continue
        title = _s(x.get("title")) or "创新点%d" % i
        m.item(i, "**%s**" % title)
        body = "；".join("%s：%s" % (lb, _s(x.get(k))) for k, lb in
                        (("what", "做了什么"), ("how", "怎么做的"), ("effect", "达成什么")) if _s(x.get(k)))
        if body:
            m.prose(body, 2)
    m.para(_cite_line(_citations_for(p, "S11")))


def render_markdown(payload: dict, style: str = "template") -> str:
    """渲染 Markdown。

    style="template"：完整十一章节（含〇、基本信息）；
    style="competition"：不输出〇节，开头为教材行 + 章节行 + 一级标题 + 副标题 + 三列信息表。
    """
    if style not in ("template", "competition"):
        raise ValueError("style 只能是 'template' 或 'competition'，收到 %r" % (style,))
    p = payload if isinstance(payload, dict) else {}
    meta = _meta(p)
    m = _MD()

    if style == "competition":
        # 比赛体例：教材行 + 章节行 + 一级标题 + 副标题 + 三列信息表（无〇节）
        book = _s(meta.get("textbook"))
        chapter = _s(meta.get("chapter"))
        m.add(book, chapter, "")
        m.h(1, _title(p) or "课题")
        if _s(meta.get("subtitle")):
            m.add("## ——%s" % _s(meta.get("subtitle")))
        subtitle = _s(meta.get("core_question"))
        m.table(["主题名称", "年级", "教材版本", "时间"], [[
            (_title(p) + ("<br>（%s）" % subtitle if subtitle else "")),
            meta.get("grade"),
            book if not chapter else "%s<br>%s" % (book, chapter),
            "%s<br>（%s min）" % (_s(meta.get("course_type")), _s(meta.get("duration_min"))),
        ]])
    else:
        m.add(" ".join(x for x in (_s(meta.get("textbook")), _s(meta.get("chapter"))) if x))
        m.h(1, _book_title(p))
        if _s(meta.get("subtitle")):
            m.add("## ——%s" % _s(meta.get("subtitle")))
        m.h(2, "〇、基本信息")
        _md_meta_table(m, p)

    _render_s1(m, p)
    _render_s2(m, p)
    _render_s3(m, p)
    _render_s4(m, p)
    _render_s5(m, p)
    _render_s6(m, p)
    _render_s7(m, p)
    _render_s8(m, p)
    _render_s9(m, p)
    _render_s10(m, p)
    _render_s11(m, p)
    return m.text()


# ============================================================================
# HTML 渲染
# ============================================================================

LESSON_CSS = """
@page { size: A4; margin: 22mm 18mm 20mm 18mm; }
@page { @top-center { content: string(lesson-title); font-size: 9pt; color: #888; } }
@page { @bottom-center { content: counter(page) " / " counter(pages); font-size: 9pt; color: #888; } }
body { font-family: "Times New Roman","SimSun","Noto Serif CJK SC",serif; font-size:10.5pt; line-height:1.75; color:#000; word-break:break-word; margin: 0 auto; max-width: 190mm; }
h1, h2, h3, h4, p, li, td, th, pre, blockquote { font-family: "Times New Roman","SimSun","Noto Serif CJK SC",serif; }
h1 { font-size:18pt; font-weight:bold; text-align:center; margin: 0 0 4mm 0; string-set: lesson-title content(); }
h2 { font-size:14pt; border-bottom:1px solid #333; margin: 6mm 0 3mm 0; padding-bottom: 1mm; page-break-after: avoid; }
h3 { font-size:12pt; margin: 4mm 0 2mm 0; page-break-after: avoid; }
h4 { font-size: 10.5pt; margin: 3mm 0 2mm 0; }
p { margin: 0 0 2mm 0; text-align: justify; }
ul, ol { margin: 0 0 2.5mm 0; padding-left: 7mm; }
li { margin: 0 0 1mm 0; }
table { width:100%; border-collapse:collapse; table-layout:fixed; margin: 3mm 0 4mm 0; page-break-inside: auto; }
thead { display: table-header-group; }
tfoot { display: table-footer-group; }
tr { page-break-inside: avoid; }
th,td { border:1px solid #999; padding:6px 8px; vertical-align:top; font-size:9.5pt; word-break: normal; overflow-wrap: break-word; }
th { background:#e8e8e8; font-weight:bold; text-align:center; }
.process-table col:nth-child(1){width:16%} .process-table col:nth-child(2){width:36%}
.process-table col:nth-child(3){width:24%} .process-table col:nth-child(4){width:24%}
.process-table { font-size: 9pt; }
.achieve-table col:nth-child(1){width:8%} .achieve-table col:nth-child(2){width:13%} .achieve-table col:nth-child(3){width:43%}
.achieve-table col:nth-child(4){width:9%} .achieve-table col:nth-child(5){width:9%} .achieve-table col:nth-child(6){width:9%} .achieve-table col:nth-child(7){width:9%}
.grade-table col:nth-child(1){width:12%} .grade-table col:nth-child(2){width:88%}
.quiz-table col:nth-child(1){width:7%} .quiz-table col:nth-child(2){width:24%} .quiz-table col:nth-child(3){width:33%} .quiz-table col:nth-child(4){width:36%}
.quiz-table td:nth-child(1), .quiz-table th:nth-child(1) { text-align: center; }
.meta-table col:nth-child(1){width:22%} .meta-table td:nth-child(1){font-weight:bold; background:#f2f2f2;}
.info-table col:nth-child(1){width:26%} .info-table col:nth-child(2){width:16%} .info-table col:nth-child(3){width:34%} .info-table col:nth-child(4){width:24%}
pre { font-family: "Noto Sans Mono CJK SC","SimSun",monospace; font-size:9pt; line-height:1.45; background:#f7f7f7; border:1px solid #ccc; padding:3mm; white-space: pre-wrap; word-break: break-all; page-break-inside: avoid; }
code { font-family: "Noto Sans Mono CJK SC","SimSun",monospace; font-size: 9.5pt; }
blockquote { margin: 2mm 0 3mm 0; padding: 2mm 3mm; border-left: 2px solid #999; color: #333; background: #fafafa; }
.cite { font-size: 9pt; color: #444; }
.mermaid-fallback{color:#c00}
.tag { color: #b00; font-weight: bold; }
.sup { font-size: 8pt; vertical-align: super; }
.ct { margin: 0 0 2mm 0; }
.center { text-align: center; }
.blank-line { display: inline-block; min-width: 60mm; border-bottom: 1px solid #000; }
hr { border: none; border-top: 1px solid #ccc; margin: 5mm 0; }
.subtitle { text-align: center; font-size: 14pt; font-weight: bold; margin: 0 0 5mm 0; }
.book-line, .chapter-line { text-align: right; margin: 0; font-size: 11pt; }
.section-note { font-size: 9.5pt; color: #444; }
.sign-list { margin: 0; padding-left: 7mm; font-size: 9.5pt; }
@media screen { body { padding: 10mm; background: #fff; box-shadow: 0 0 6px #ddd; } }
@media print { body { max-width: none; box-shadow: none; padding: 0; } }
"""

COVER_CSS = """
@page { size: A4; margin: 0; }
body { font-family: "Times New Roman","SimSun","Noto Serif CJK SC",serif; font-size: 16pt; line-height: 1.9; color:#000; margin: 0; }
.cover { height: 297mm; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; }
.cover-title { font-size: 30pt; font-weight: bold; letter-spacing: 8pt; margin: 0 0 28mm 0; }
.cover-rows { font-size: 18pt; text-align: left; }
.cover-row { margin: 0 0 12mm 0; }
.cover-label { display: inline-block; width: 40mm; text-align: right; padding-right: 4mm; }
.cover-value { display: inline-block; min-width: 90mm; border-bottom: 1px solid #000; text-align: center; padding: 0 2mm; }
@media print { .cover { height: 297mm; } }
"""


class _HTML:
    def __init__(self):
        self.parts = []

    def add(self, s):
        if s:
            self.parts.append(s)
        return self

    def text(self):
        return "".join(self.parts)


def _h(text) -> str:
    return _inline(text)


def _table_html(cls, headers, rows, cols=None) -> str:
    out = ['<table class="%s">' % cls]
    if cols:
        out.append("<colgroup>" + "".join('<col style="width:%s">' % c for c in cols) + "</colgroup>")
    out.append("<thead><tr>" + "".join("<th>%s</th>" % _h(x) for x in headers) + "</tr></thead>")
    out.append("<tbody>")
    for r in rows:
        out.append("<tr>" + "".join("<td>%s</td>" % (c if _looks_html(c) else _h(c)) for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _looks_html(value) -> bool:
    """只有本模块自己拼出的白名单标签才当作 HTML 直出（其余一律 escape，含「＜」「>」等正文符号）。"""
    return isinstance(value, str) and bool(re.search(r"</?(br|strong|em|code|ul|ol|li|p|span|sub|sup)\b[^<>]*>", value))


def _bul(items) -> str:
    items = [_s(x) for x in items if _s(x)]
    if not items:
        return ""
    return "<ul>" + "".join("<li>%s</li>" % _h(x) for x in items) + "</ul>"


def _ol(items, start=1) -> str:
    items = [_s(x) for x in items if _s(x)]
    if not items:
        return ""
    return '<ol start="%d">' % start + "".join("<li>%s</li>" % _h(x) for x in items) + "</ol>"


def _kv_list(pairs) -> str:
    """[(label, text)] → <ul><li><strong>label</strong>：text</li></ul>（跳过空项）。"""
    items = [(lb, _s(v)) for lb, v in pairs if _s(v)]
    if not items:
        return ""
    return "<ul>" + "".join("<li><strong>%s</strong>：%s</li>" % (_h(lb), _h(v)) for lb, v in items) + "</ul>"


def _cite_html(cites) -> str:
    line = _cite_line(cites)
    if not line:
        return ""
    return '<p class="cite">%s</p>' % _h(line.replace("> ", "", 1))


def _ct_html(items) -> str:
    items = [x for x in items if x]
    if not items:
        return ""
    return "".join('<p class="ct"><span class="tag">※</span>%s</p>' % _h(x) for x in items)


def _controversy_lines(p, prefix, idx):
    items = _controversy_for(p, prefix)
    return ["%s（%s）%s" % (it["issue"], it["section"],
                           ("；我的取舍：" + it["my_view"]) if it["my_view"] else "")
            for it in items], {it["index"]: it for it in items}


def _subtitle_html(p) -> str:
    sub = _s(_meta(p).get("subtitle"))
    return '<p class="subtitle">——%s</p>' % _h(sub) if sub else ""


def _html_sections(p, style) -> str:
    h = _HTML()
    meta = _meta(p)
    objs = _objectives(p)

    # ---- 〇 ----
    if style == "template":
        rows = [
            ("课题名称", meta.get("title")),
            ("副标题/教学主张", meta.get("subtitle")),
            ("授课年级", meta.get("grade")),
            ("教材版本及位置", " ".join(x for x in (_s(meta.get("textbook")), _s(meta.get("chapter"))) if x)),
            ("课型", meta.get("course_type") or _s(meta.get("course_type"))),
            ("课时与时长", ("一课时（%s min）" % _s(meta.get("duration_min"))) if meta.get("duration_min") else ""),
            ("授课对象", meta.get("class_desc")),
        ]
        if _s(meta.get("teacher_name")):
            rows.append(("授课教师", meta.get("teacher_name")))
        h.add("<h2>〇、基本信息</h2>")
        h.add(_table_html("meta-table", ["项目", "内容"], [(a, b) for a, b in rows],
                          cols=["22%", "78%"]))

    # ---- 一 ----
    s1 = _as_dict(p.get("S1"))
    cur, tb = _as_dict(s1.get("curriculum")), _as_dict(s1.get("textbook"))
    lines, cts = _controversy_lines(p, "S1", 0)
    h.add("<h2>一、课标及教材分析</h2>")
    h.add(_ct_html(cts.values() and [v["issue"] for v in cts.values()] or []))
    h.add("<h3>1、课标分析</h3>")
    h.add(_kv_list([("所属模块", cur.get("module"))]))
    disc = [(lb, cur.get(k)) for k, lb in (("big_idea", "大概念"), ("important_idea", "重要概念"),
                                           ("subconcept", "次位概念")) if _s(cur.get(k))]
    if disc:
        h.add("<ul>" + "".join("<li><strong>%s</strong>：%s</li>" % (_h(lb), _h(v)) for lb, v in disc) + "</ul>")
    h.add(_kv_list([("学业要求", cur.get("achievement_req")),
                    ("学业质量水平定位", cur.get("quality_level")),
                    ("课标对本课的具体指向", cur.get("focus"))]))
    h.add(_cite_html(_citations_for(p, "S1.curriculum")))
    h.add("<h3>2、教材分析</h3>")
    h.add(_kv_list([("本节内容概述", tb.get("overview") or tb.get("position")),
                    ("编排意图", tb.get("design_intent")),
                    ("章节内部地位", tb.get("internal_role")),
                    ("总体定位", tb.get("overall"))]))
    h.add(_bul(tb.get("cross_links")) if _as_list(tb.get("cross_links")) else "")
    h.add(_cite_html(_citations_for(p, "S1.textbook")))

    # ---- 二 ----
    s2 = _as_dict(p.get("S2"))
    h.add("<h2>二、学情分析</h2>")
    h.add("<h3>1、一般特征分析</h3>")
    g = _as_dict(s2.get("general"))
    h.add(_kv_list([("认知发展阶段", g.get("cognitive_stage")), ("已有知识基础", g.get("prior_knowledge")),
                    ("思维与能力特点", g.get("thinking")), ("教学对策", g.get("response"))]))
    h.add(_cite_html(_citations_for(p, "S2.general")))
    h.add("<h3>2、学习风格分析</h3>")
    st_ = _as_dict(s2.get("style"))
    h.add(_kv_list([("认知方式", st_.get("cognitive_mode")), ("合作倾向", st_.get("cooperation")),
                    ("学习偏好", st_.get("preference")), ("教学对策", st_.get("response")),
                    ("课堂管理预案", st_.get("classroom_mgmt"))]))
    h.add(_cite_html(_citations_for(p, "S2.style")))
    h.add("<h3>3、学习起点分析</h3>")
    start = _as_dict(s2.get("starting"))
    h.add(_kv_list([("已知", start.get("known"))]))
    precs = [x for x in _as_list(start.get("preconceptions")) if isinstance(x, dict) and _s(x.get("name"))]
    if precs:
        h.add("<ul><li><strong>认知难点（前科学概念）</strong>：<ul>")
        for i, x in enumerate(precs, 1):
            h.add("<li>前概念%d：%s<ul>" % (i, _h(x.get("name"))))
            if _s(x.get("evidence")):
                h.add("<li>证据：%s</li>" % _h(x.get("evidence")))
            if _s(x.get("plan")):
                h.add("<li>对策：%s</li>" % _h(x.get("plan")))
            h.add("</ul></li>")
        h.add("</ul></li></ul>")
    ladder = [_s(x) for x in _as_list(start.get("ladder")) if _s(x)]
    if ladder:
        h.add(_kv_list([("认知阶梯", " → ".join(ladder))]))
    h.add(_cite_html(_citations_for(p, "S2.starting")))

    # ---- 三 ----
    s3 = _as_dict(p.get("S3"))
    h.add("<h2>三、教学重难点</h2>")
    h.add("<h3>1、教学重点</h3>")
    h.add(_ol(s3.get("key_points")))
    h.add("<h3>2、教学难点</h3>")
    diffs = [_s(x.get("text")) or _s(x) if isinstance(x, dict) else _s(x) for x in _as_list(s3.get("difficulties"))]
    h.add(_ol(diffs))
    causes = [x for x in _as_list(s3.get("difficulty_causes")) if isinstance(x, dict)
              and (_s(x.get("difficulty")) or _s(x.get("cause")))]
    if causes:
        h.add("<h3>3、难点成因分析（可选）</h3>")
        h.add(_bul("难点%s的成因在于：%s" % (_difficulty_label(x.get("difficulty"), i), _s(x.get("cause")))
                   for i, x in enumerate(causes, 1)))
    brk = [x for x in _as_list(s3.get("breakthrough")) if isinstance(x, dict)
           and (_s(x.get("difficulty")) or _s(x.get("strategy")))]
    if brk:
        h.add("<h3>4、突破策略（可选）</h3>")
        h.add(_bul("针对难点%s %s" % (_difficulty_label(x.get("difficulty"), i), _s(x.get("strategy")))
                   for i, x in enumerate(brk, 1)))
    h.add(_cite_html(_citations_for(p, "S3")))

    # ---- 四 ----
    h.add("<h2>四、教学目标</h2>")
    if objs:
        h.add("<ol>" + "".join(
            "<li><strong>%s（%s）</strong>%s</li>" % (_h(o["id"]), _h(o["dimension"]), _h(_objective_text(o)))
            for o in objs) + "</ol>")
    signs = [(o["id"], o["assessable_sign"]) for o in objs if o["assessable_sign"]]
    if signs:
        h.add('<ul class="sign-list">' + "".join("<li>%s 达成标志：%s</li>" % (_h(a), _h(b)) for a, b in signs)
              + "</ul>")
    h.add(_cite_html(_citations_for(p, "S4")))

    # ---- 五 ----
    h.add("<h2>五、教学方法</h2>")
    s5 = _as_list(p.get("S5"))
    if s5:
        h.add("<ol>")
        for i, x in enumerate(s5, 1):
            if isinstance(x, dict):
                h.add("<li><strong>%s</strong>%s</li>" % (_h(_s(x.get("name")) or "方法%d" % i),
                                                         _kv_list([("依据", x.get("basis")), ("做法", x.get("how")),
                                                                   ("作用", x.get("effect"))])))
            else:
                h.add("<li>%s</li>" % _h(x))
        h.add("</ol>")
    h.add(_cite_html(_citations_for(p, "S5")))

    # ---- 六 ----
    s6 = _as_dict(p.get("S6"))
    h.add("<h2>六、教学准备</h2>")
    for key, title in (("environment", "1、教学环境"), ("student", "2、学生准备"),
                       ("teacher_materials", "3、教师教具准备")):
        h.add("<h3>%s</h3>" % title)
        h.add(_ol(s6.get(key)))
    h.add(_cite_html(_citations_for(p, "S6")))

    # ---- 七 ----
    s7 = _as_dict(p.get("S7"))
    ln = _as_dict(s7.get("lines"))
    h.add("<h2>七、教学设计思路</h2>")
    h.add("<pre>%s</pre>" % html.escape(_flow_ascii(p)))
    h.add(_kv_list([("情境主线", ln.get("situation")), ("知识主线", ln.get("knowledge")),
                    ("素养主线", ln.get("literacy")), ("核心观念", s7.get("core_idea"))]))
    h.add(_cite_html(_citations_for(p, "S7")))

    # ---- 八 ----
    h.add("<h2>八、教学过程</h2>")
    steps = _process(p)
    if steps:
        rows = []
        for s in steps:
            rows.append((
                "<strong>%s、%s</strong><br>（%d min）" % (_h(s["no"]), _h(s["name"]), s["minutes"]),
                "<br>".join(_h(x) for x in s["teacher_activity"]),
                "<br>".join(_h(x) for x in s["student_activity"]),
                _h(s["intent"]),
            ))
        h.add('<table class="process-table"><colgroup><col><col><col><col></colgroup>'
              "<thead><tr>" + "".join("<th>%s</th>" % x for x in ("教学环节", "教师活动", "学生活动", "设计意图"))
              + "</tr></thead><tbody>"
              + "".join("<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>" for r in rows)
              + "</tbody></table>")
        scaffolds = [(s["no"], x) for s in steps for x in s["scaffolds"]]
        if scaffolds:
            h.add(_bul("支架（环节%s）：%s" % (no, x) for no, x in scaffolds))
        h.add('<p class="section-note">时间分配：合计 %d min。</p>' % sum(s["minutes"] for s in steps))
    h.add(_cite_html(_citations_for(p, "S8")))

    # ---- 九 ----
    s9 = _as_dict(p.get("S9"))
    fo = _as_dict(s9.get("formative"))
    su = _as_dict(s9.get("summative"))
    part = _as_dict(fo.get("participation"))
    oa = _as_dict(fo.get("objective_attainment"))
    rubric = _as_dict(part.get("rubric"))
    h.add("<h2>九、教学评价</h2>")
    h.add("<h3>1、形成性评价</h3>")
    h.add("<h4>（1）课堂参与评价（%s%%）</h4>" % _h(part.get("weight") or ""))
    grades = [(g, rubric.get(g)) for g in ("A", "B", "C", "D") if _s(rubric.get(g))]
    if grades:
        h.add('<table class="grade-table"><colgroup><col><col></colgroup><thead><tr><th>等级</th>'
              "<th>具体表现</th></tr></thead><tbody>"
              + "".join("<tr><td>%s</td><td>%s</td></tr>" % (_h(a), _h(b)) for a, b in grades)
              + "</tbody></table>")
    h.add("<h4>（2）目标达成评价（%s%%）</h4>" % _h(oa.get("weight") or ""))
    h.add('<p class="section-note">等级：A—完全达成、B—部分达成、C—基本达成、D—未达成。每一行对应一条教学目标。</p>')
    omap = {o["id"]: o for o in objs}
    arows = []
    for r in _as_list(oa.get("rows")):
        r = _as_dict(r)
        oid = _s(r.get("objective_id"))
        dim = _s(r.get("dimension")) or omap.get(oid, {}).get("dimension", "")
        arows.append("%s|%s|%s" % (oid, dim, _s(r.get("target"))))
    if arows or omap:
        cells = [a.split("|") for a in arows] or [[o["id"], o["dimension"], o["assessable_sign"]] for o in objs]
        h.add(_table_html("achieve-table", ["编号", "核心素养", "目标达成表现", "A", "B", "C", "D"],
                          [c + ["", "", "", ""] for c in cells],
                          cols=["8%", "13%", "43%", "9%", "9%", "9%", "9%"]))
    qc = [x for x in _as_list(fo.get("quick_check")) if isinstance(x, dict)
          and (_s(x.get("stem")) or _s(x.get("answer")))]
    if qc:
        h.add("<h4>（3）课堂即时检测（随堂 %d 题）</h4>" % len(qc))
        h.add(_table_html("quiz-table", ["题号", "题目", "参考答案", "学生易错预估与应对"],
                          [(_s(x.get("no")) or str(i), _s(x.get("stem")), _s(x.get("answer")), _s(x.get("pitfalls")))
                           for i, x in enumerate(qc, 1)],
                          cols=["7%", "24%", "33%", "36%"]))
    h.add("<h3>2、终结性评价</h3>")
    if _s(su.get("task")):
        h.add("<p><strong>任务</strong>：%s</p>" % _h(su.get("task")))
    if _as_list(su.get("requirements")):
        h.add("<p><strong>要求</strong>：</p>" + _ol(su.get("requirements")))
    mapping = [_s(x) for x in _as_list(su.get("mapping")) if _s(x)]
    if mapping:
        h.add('<p class="section-note">对应目标：%s</p>' % _h("、".join(mapping)))
    h.add(_cite_html(_citations_for(p, "S9")))

    # ---- 十 ----
    s10 = _as_dict(p.get("S10"))
    h.add("<h2>十、板书设计</h2>")
    h.add("<pre>%s</pre>" % html.escape(_board_ascii(p)))
    h.add(_kv_list([("主板书", s10.get("main")), ("副板书", s10.get("side")),
                    ("生成性板书", s10.get("generative"))]))
    h.add(_cite_html(_citations_for(p, "S10")))

    # ---- 十一 ----
    h.add("<h2>十一、教学创新点</h2>")
    s11 = _as_list(p.get("S11"))
    if s11:
        h.add("<ol>")
        for i, x in enumerate(s11, 1):
            if isinstance(x, dict):
                h.add("<li><strong>%s</strong>%s</li>" % (
                    _h(_s(x.get("title")) or "创新点%d" % i),
                    _kv_list([("做了什么", x.get("what")), ("怎么做的", x.get("how")), ("达成什么", x.get("effect"))])))
            else:
                h.add("<li>%s</li>" % _h(x))
        h.add("</ol>")
    h.add(_cite_html(_citations_for(p, "S11")))

    # ---- 争议点附录 ----
    items = [c for c in _as_list(p.get("controversy")) if isinstance(c, dict) and _s(c.get("issue"))]
    if items:
        h.add("<h2>附录：争议点与我的取舍</h2><ol>")
        for c in items:
            h.add("<li><strong>%s</strong>（争议于 %s）%s</li>" % (
                _h(c.get("issue")), _h(c.get("section")),
                ("<br>我的取舍：%s" % _h(c.get("my_view"))) if _s(c.get("my_view")) else ""))
        h.add("</ol>")
    return h.text()


def _page(title, css, body, root_class="") -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>%s</title><style>%s</style></head><body%s>%s</body></html>"
        % (_h(title), css, (' class="%s"' % root_class) if root_class else "", body)
    )


def render_html(payload: dict, style: str = "template", title: str | None = None) -> str:
    """自包含 HTML（内联 <style>，无任何外部引用，无 Mermaid 运行时）。"""
    if style not in ("template", "competition"):
        raise ValueError("style 只能是 'template' 或 'competition'，收到 %r" % (style,))
    p = payload if isinstance(payload, dict) else {}
    meta = _meta(p)
    doc_title = title or _book_title(p)
    head = _HTML()
    if style == "competition":
        if _s(meta.get("textbook")):
            head.add('<p class="book-line">%s</p>' % _h(meta.get("textbook")))
        if _s(meta.get("chapter")):
            head.add('<p class="chapter-line">%s</p>' % _h(meta.get("chapter")))
    head.add("<h1>%s</h1>" % _h(_title(p) or "课题"))
    head.add(_subtitle_html(p))
    if style == "competition":
        topic = _title(p)
        if _s(p.get("core_question")):
            topic = "%s<br>（%s）" % (_h(topic), _h(_s(p.get("core_question"))))
        else:
            topic = _h(topic)
        info = _table_html(
            "info-table", ["主题名称", "年级", "教材版本", "时间"],
            [(topic,
              _h(meta.get("grade")),
              _h(" ".join(x for x in (_s(meta.get("textbook")), _s(meta.get("chapter"))) if x) or
                 _s(meta.get("textbook"))),
              "%s<br>（%s min）" % (_h(_s(meta.get("course_type"))), _h(_s(meta.get("duration_min")))))],
            cols=["26%", "16%", "34%", "24%"])
        head.add(info)
    if style == "template":
        head.add('<p class="center section-note">%s</p>' %
                 _h(" ".join(x for x in (_s(meta.get("textbook")), _s(meta.get("chapter"))) if x)))
    head.add(_html_sections(p, style))
    return _page(doc_title, LESSON_CSS, head.text())


def render_cover_html(payload: dict) -> str:
    """单页封皮：居中显示 姓名 / 科目 / 课题；缺省字段渲染为空白下划线。"""
    p = payload if isinstance(payload, dict) else {}
    meta = _meta(p)

    def val(x):
        x = _s(x)
        return _h(x) if x else "&nbsp;"

    rows = [
        ("姓　　名", val(meta.get("teacher_name"))),
        ("授课科目", val(meta.get("subject") or meta.get("grade"))),
        ("授课题目", val(meta.get("title"))),
    ]
    body = ('<div class="cover"><h1 class="cover-title">教 学 设 计</h1><div class="cover-rows">'
            + "".join('<p class="cover-row"><span class="cover-label">%s：</span>'
                      '<span class="cover-value">%s</span></p>' % (lb, v) for lb, v in rows)
            + "</div></div>")
    return _page("教案封皮 · %s" % (_title(p) or ""), COVER_CSS, body)


# ============================================================================
# 章节重做
# ============================================================================

def apply_section(payload: dict, section_key: str, value) -> dict:
    """深拷贝 payload 后替换一个章节键，返回新 payload（供「章节重做」）。"""
    new = copy.deepcopy(payload if isinstance(payload, dict) else {})
    if not isinstance(section_key, str) or not section_key.strip():
        raise ValueError("section_key 不能为空")
    key = section_key.strip()
    allowed = set(SECTION_TITLES.keys())
    if key not in allowed:
        raise KeyError("未知章节键 %r，可用：%s" % (section_key, "、".join(sorted(allowed))))
    if key in LIST_SECTIONS:
        if value is None:
            value = []
        if not isinstance(value, list):
            raise TypeError("章节 %s 需要 list，收到 %s" % (key, type(value).__name__))
        new[key] = copy.deepcopy(value)
    else:
        if value is None:
            raise TypeError("章节 %s 需要 dict，收到 None" % key)
        if not isinstance(value, dict):
            raise TypeError("章节 %s 需要 dict，收到 %s" % (key, type(value).__name__))
        merged = copy.deepcopy(_as_dict(new.get(key)))
        merged.update(copy.deepcopy(value))
        if key == "S9":
            for sub in ("formative", "summative"):
                if isinstance(value.get(sub), dict):
                    base = copy.deepcopy(_as_dict(_as_dict(new.get(key)).get(sub)))
                    base.update(copy.deepcopy(value[sub]))
                    merged[sub] = base
        new[key] = merged
    return new


def write_file(path, content: str) -> str:
    """一律 UTF-8 写文件，返回绝对路径。"""
    target = Path(os.path.expanduser(str(path)))
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return str(target.resolve())


# ============================================================================
# 自检（最小但合法的 payload）
# ============================================================================

def _selftest_payload() -> dict:
    p = empty_lesson()
    p["meta"].update({
        "title": "DNA的复制",
        "subtitle": "基于假说—演绎与建模的探究式教学",
        "grade": "高一",
        "textbook": "人教版高中生物学必修2《遗传与进化》",
        "chapter": "第3章第3节",
        "course_type": "新授课",
        "duration_min": 40,
        "class_desc": "普通高中高一平行班，48 人，4—5 人一组",
        "teacher_name": "示例教师",
        "subject": "生物",
    })
    p["core_question"] = "一份写在DNA里的信息，凭什么在经历无数次复制后仍能被精确读出？"
    p["S1"] = {
        "curriculum": {
            "module": "必修课程模块2「遗传与进化」",
            "big_idea": "概念3 遗传信息控制生物性状，并代代相传",
            "important_idea": "3.1 亲代传递给子代的遗传信息主要编码在DNA分子上",
            "subconcept": "3.1.3 概述DNA分子通过半保留方式进行复制",
            "achievement_req": "结合DNA双螺旋结构模型，阐明DNA作为遗传物质所具有的特征（生命观念、科学思维）",
            "quality_level": "知识性目标锚定水平1—2，科学思维目标指向水平3",
            "focus": "通过假说—演绎与建模，阐明半保留复制的过程与证据",
        },
        "textbook": {
            "position": "第3章第3节，教材P.53—56",
            "overview": "教材以三个「本节聚焦」问题展开：复制方式、探究证据、复制的意义。",
            "design_intent": "先推测后证据，本身即假说—演绎法的完整呈现",
            "internal_role": "承接第1、2节，为第4章基因的表达奠基",
            "cross_links": ["必修1第6章细胞的生命历程"],
            "overall": "承上启下的关键一节",
        },
    }
    p["S2"] = {
        "general": {"cognitive_stage": "形式运算阶段，抽象思维初步发展",
                    "prior_knowledge": "必修1核酸、酶与ATP、有丝分裂；本章第1—2节",
                    "thinking": "比较、归纳与逆向推理能力明显提升",
                    "response": "把重心放在综合运用已有工具解决新问题"},
        "style": {"cognitive_mode": "偏向场依存，依赖引导与直观模型",
                  "cooperation": "乐于小组讨论与上台展示",
                  "preference": "需要可视化工具与结构化支架",
                  "response": "角色分工保证人人有事做",
                  "classroom_mgmt": "设副板书「问题暂存区」收纳偏题问题"},
        "starting": {
            "known": "知道碱基互补配对与双螺旋结构，知道「DNA复制→遗传稳定性」",
            "preconceptions": [
                {"name": "天然默认全保留复制", "evidence": "前测中多数学生画出「整条双链照抄」",
                 "plan": "先画再说，让前概念外显后再排除"},
                {"name": "混淆细胞分裂次数与复制次数", "evidence": "教材练习第2题高频失分",
                 "plan": "即时检测第1题专门考查"},
            ],
            "ladder": ["前概念外显", "从结构生假说", "长推演切短", "抽象量具象化", "结论变证据"],
        },
    }
    p["S3"] = {
        "key_points": ["DNA半保留复制的实验证据", "DNA复制的过程与条件", "复制准确性的结构基础"],
        "difficulties": ["运用演绎推理预测各假说第一代、第二代的实验结果", "体会证据的充分性"],
        "difficulty_causes": [
            {"difficulty": "难点（1）", "cause": "需同时追踪三个变量，推理链条长；密度是抽象物理量"},
            {"difficulty": "难点（2）", "cause": "学生习惯把实验结果当作直接读数"},
        ],
        "breakthrough": [
            {"difficulty": "难点（1）", "strategy": "「预期—结果对照表」把长推演切成短推理单元"},
            {"difficulty": "难点（2）", "strategy": "引入弥散复制制造「证据不足」的冲突"},
        ],
    }
    p["S4"] = [
        {"id": "O1", "dimension": "生命观念",
         "on": "观察双螺旋模型并分析复制前后子代DNA的组成", "can": "阐明半保留复制的过程与四种基本条件",
         "develop": "结构与功能观", "assessable_sign": "能用自己的话说清「为什么两个子代DNA完全相同」"},
        {"id": "O2", "dimension": "科学思维",
         "on": "提出竞争性假说并完成「预期—结果对照表」", "can": "用排除法推出「DNA以半保留方式复制」",
         "develop": "演绎与建模的科学思维", "assessable_sign": "能独立贴出两代预期条带并说明排除依据"},
        {"id": "O3", "dimension": "科学探究",
         "on": "面对「如何区分新旧DNA」的困境", "can": "形成「标记—转移—取样离心」的实验方案",
         "develop": "实验设计与方案修正能力", "assessable_sign": "方案三步齐全且能回应他人质疑"},
        {"id": "O4", "dimension": "社会责任",
         "on": "古DNA研究资料", "can": "对「遗传信息被长期保存」作出理性解释",
         "develop": "崇尚实证的意识", "assessable_sign": "能指明结论只延伸到证据支持的地方"},
    ]
    p["S5"] = [
        {"name": "引导发现法", "basis": "课标倡导教学过程重实践", "how": "不给答案，控制支架发放时机", "effect": "突破难点（1）"},
        {"name": "小组合作学习法", "basis": "合作学习要求分工明确", "how": "四种角色分工", "effect": "人人有事做"},
        {"name": "演示法", "basis": "结构决定功能", "how": "磁吸模型由学生重演", "effect": "落实生命观念"},
    ]
    p["S6"] = {
        "environment": ["多媒体设备，投影清晰", "离线可用的交互式网页"],
        "student": ["前测问卷（不出现「半保留」等术语）", "预习课本第53—56页"],
        "teacher_materials": ["磁吸双螺旋模型1套", "离心管卡纸每组2张", "彩色条带贴若干"],
    }
    p["S7"] = {
        "stages": ["情境导入（3 min）", "先画再说（8 min）", "演绎推断（10 min）", "实验检验（9 min）", "过程建模与小结（10 min）"],
        "lines": {"situation": "古DNA信息「可读」→ 追问机制 → 完整解释", "knowledge": "结构→推测→证据→过程→意义",
                  "literacy": "以科学思维为主，其余随环节落实"},
        "core_idea": "结构决定功能",
    }
    p["S8"] = [
        {"no": "一", "name": "情境导入", "minutes": 3, "teacher_activity": ["【情境创设】展示古DNA报道"],
         "student_activity": ["【观察】明确遗传信息被长期保存"], "intent": "创设认知缺口", "scaffolds": []},
        {"no": "二", "name": "先画再说", "minutes": 8, "teacher_activity": ["【任务布置】画出想象中的复制方式"],
         "student_activity": ["【独立画图】并命名"], "intent": "外显前概念", "scaffolds": ["S1 学案假说推演表"]},
        {"no": "三", "name": "演绎推断", "minutes": 10, "teacher_activity": ["【提出困境】怎么区分新旧链"],
         "student_activity": ["【小组讨论】提思路"], "intent": "先想再给工具", "scaffolds": ["S2 材料卡3张"]},
        {"no": "四", "name": "实验检验", "minutes": 9, "teacher_activity": ["【呈现结果】三组离心结果"],
         "student_activity": ["【对照比对】填对照表"], "intent": "体验证据充分性", "scaffolds": []},
        {"no": "五", "name": "过程建模与情境回归", "minutes": 10, "teacher_activity": ["【学生重演】磁吸模型"],
         "student_activity": ["【回扣导入】完整作答"], "intent": "首尾呼应、系统化知识", "scaffolds": []},
    ]
    p["S9"] = {
        "formative": {
            "participation": {"weight": 20, "rubric": {
                "A": "主动上台展示并逻辑清晰地分享", "B": "配合分工，思维深度待提升",
                "C": "偶有分心，较少主动发言", "D": "回避提问，脱离课堂"}},
            "objective_attainment": {"weight": 30, "rows": [
                {"objective_id": "O%d" % i, "dimension": p["S4"][i - 1]["dimension"],
                 "target": p["S4"][i - 1]["assessable_sign"]} for i in range(1, 5)]},
            "quick_check": [
                {"no": 1, "stem": "分裂3次后含¹⁵N的细菌比例？", "answer": "100%", "pitfalls": "误答 1/4；追问「DNA分子数还是细菌数」"},
                {"no": 2, "stem": "第一代一条中带可排除哪种复制方式？", "answer": "排除全保留", "pitfalls": "误答「可排除全部」"},
                {"no": 3, "stem": "为什么两个子代DNA完全相同？", "answer": "母链作模板 + 碱基互补配对", "pitfalls": "循环解释"},
            ],
        },
        "summative": {"weight": 50, "task": "撰写科普推文配文「DNA的抄写员」",
                      "requirements": ["说明过程与条件（O1）", "附「推演—证据」表（O2）",
                                       "提出替代标记方案（O3）", "写两条个人思考（O4）"],
                      "mapping": ["O1", "O2", "O3", "O4"]},
    }
    p["S10"] = {
        "main": "假说树 → 证据 → 结论",
        "side": "左侧「问题暂存区」",
        "generative": "右下角课堂生成内容",
        "structure": {"type": "tree", "nodes": [
            "一、推测：半保留／全保留／弥散",
            "二、证据：¹⁵N标记 + 离心",
            "三、过程：解旋 → 合成子链 → 盘绕",
            "四、意义：保持遗传信息的连续性",
        ]},
    }
    p["S11"] = [
        {"title": "支架后移", "what": "关键支架发放时机整体后移", "how": "先画再说、先想再发卡", "effect": "实验设计从复述变为设计"},
        {"title": "弥散复制制造认知冲突", "what": "引入第三假说", "how": "第一代无法区分，必须取第二代", "effect": "亲历证据充分性"},
        {"title": "实物模型与数字化模型分工", "what": "三种表征各司其职", "how": "磁吸模型、卡纸条带、交互网页", "effect": "抽象量可触可贴"},
    ]
    p["citations"] = [
        {"corpus_id": "bx2", "book_page": 55,
         "quote": "DNA的复制是以半保留的方式进行的。", "section": "S1.textbook"},
        {"corpus_id": "std-bio-2017-2025", "book_page": 12,
         "quote": "3.1.3 概述DNA分子通过半保留方式进行复制", "section": "S1.curriculum"},
    ]
    p["controversy"] = [
        {"section": "S3.difficulties[1]", "issue": "弥散复制是否进课堂",
         "my_view": "仅作思维工具引入，不作考试要求"},
    ]
    return p


def _selftest() -> None:
    p = _selftest_payload()
    res = validate(p)
    assert res["ok"] is True, "validate 未通过：%s" % json.dumps(res["errors"], ensure_ascii=False)
    assert validate(p, strict=True)["ok"] is True, "strict 模式应有引用并通过"

    md_t = render_markdown(p, "template")
    md_c = render_markdown(p, "competition")
    h2_t = [ln for ln in md_t.split("\n") if ln.startswith("## ")]
    h2_c = [ln for ln in md_c.split("\n") if ln.startswith("## ")]
    # 模板约定的 H2：副标题（——…）+ 〇到十一，共 12 个；competition 版去掉〇，共 11 个。
    # 注：「附录：提交前检查清单」「附：可替换的课型适配提示」属于 template-v1.md 的编写指引，
    #      不进入渲染产物（成品不需要录入检查清单本身）。
    subtitle_h2 = "## ——基于假说—演绎与建模的探究式教学"
    section_h2 = ["## %s" % SECTION_TITLES["S%d" % i] for i in range(1, 12)]
    expected_t = [subtitle_h2, "## 〇、基本信息"] + section_h2
    expected_c = [subtitle_h2] + section_h2
    # 约定：template 版 H2 = 副标题 + 〇到十一（12 个）；competition 版 = 副标题 + 一到十一（11 个）
    assert h2_t == expected_t, "template 版 H2 序列不符：\n%s" % "\n".join(h2_t)
    assert h2_c == expected_c, "competition 版 H2 序列不符：\n%s" % "\n".join(h2_c)
    n_t = sum(1 for ln in h2_t if ln in expected_t)
    n_c = sum(1 for ln in h2_c if ln in expected_c)
    # 以期望序列为准，不再硬编码数量（模板结构演进时只需改 expected_t）
    assert n_t == len(expected_t), "template 版 H2 数量 %d != 期望序列 %d" % (n_t, len(expected_t))
    assert n_c == len(h2_c), "competition 版 H2 数量不符"
    assert "〇、基本信息" not in md_c, "competition 版不应输出〇节"
    assert md_c.index("# DNA的复制") < md_c.index("| 主题名称 |"), "competition 版开篇顺序错误"

    # 反例：错误必须可定位
    bad = copy.deepcopy(p)
    bad["S8"][0]["minutes"] = 4
    bad["S9"]["formative"]["objective_attainment"]["rows"][1]["objective_id"] = "O9"
    bad["S4"][0]["dimension"] = "审美情趣"
    res_bad = validate(bad)
    codes = {e["code"] for e in res_bad["errors"]}
    for code in ("E_MINUTES_SUM", "E_ATTAINMENT_MISMATCH", "E_OBJECTIVE_DIM"):
        assert code in codes, "反例未触发 %s：%s" % (code, codes)
    assert all(e["path"] for e in res_bad["errors"]), "每个 error 都必须带 path"
    assert "E_CITATION_REQUIRED" in {e["code"] for e in validate(copy.deepcopy(_no_cite(p)), strict=True)["errors"]}

    # apply_section 不改原对象
    new = apply_section(p, "S4", p["S4"][:3])
    assert len(new["S4"]) == 3 and len(p["S4"]) == 4
    new = apply_section(p, "S9", {"summative": {"weight": 50, "task": "改后的任务",
                                                "requirements": p["S9"]["summative"]["requirements"],
                                                "mapping": ["O1", "O2"]}})
    assert new["S9"]["summative"]["task"] == "改后的任务" and p["S9"]["summative"]["task"] != "改后的任务"
    assert new["S9"]["formative"]["quick_check"], "S9 子节合并时不应丢失 other 子节"

    print("OK")


def _no_cite(p):
    q = copy.deepcopy(p)
    q["citations"] = []
    s1 = q["S1"]
    s1["curriculum"].pop("citation", None)
    s1["textbook"].pop("citation", None)
    return q


# ============================================================================
# CLI
# ============================================================================

def _cli(argv) -> int:
    import sys
    args = list(argv)
    if not args:
        p = _selftest_payload()
        for style in ("template", "competition"):
            out = Path.cwd() / ("lesson-%s.md" % style)
            write_file(out, render_markdown(p, style))
        write_file(Path.cwd() / "lesson-template.html", render_html(p, "template"))
        write_file(Path.cwd() / "lesson-competition.html", render_html(p, "competition"))
        write_file(Path.cwd() / "lesson-cover.html", render_cover_html(p))
        print("已写出 lesson-template.md / lesson-competition.md / *.html")
        _selftest()
        return 0

    cmd = args[0]
    opts = {"file": None, "style": "template", "out": None, "format": "md", "strict": False}
    i = 1
    while i < len(args):
        a = args[i]
        if a in ("--file", "-f", "--style", "-s", "--out", "-o", "--format"):
            if i + 1 >= len(args):
                print("参数 %s 缺少取值" % a)
                return 2
            key = {"-f": "file", "-s": "style", "-o": "out"}.get(a, a.lstrip("-"))
            opts[key] = args[i + 1]
            i += 2
        elif a == "--strict":
            opts["strict"] = True
            i += 1
        else:
            print("未知参数：%s" % a)
            return 2
    if not opts["file"]:
        print("缺少 --file")
        return 2
    with open(os.path.expanduser(opts["file"]), encoding="utf-8") as fh:
        payload = json.load(fh)

    if cmd == "validate":
        res = validate(payload, strict=bool(opts["strict"]))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 2

    if cmd in ("render", "cover"):
        if cmd == "cover":
            text = render_cover_html(payload)
            out = opts["out"] or "lesson-cover.html"
        elif opts["format"] == "html":
            text = render_html(payload, opts["style"])
            out = opts["out"] or ("lesson-%s.html" % opts["style"])
        else:
            text = render_markdown(payload, opts["style"])
            out = opts["out"] or ("lesson-%s.md" % opts["style"])
        print(write_file(out, text))
        return 0

    print("未知命令：%s（可用：validate / render / cover）" % cmd)
    return 2


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        sys.exit(_cli(sys.argv[1:]))
    _selftest()
