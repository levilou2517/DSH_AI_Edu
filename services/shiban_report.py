#!/usr/bin/env python3
"""shiban_report — 从观测点合成「双源整合评估报告」。

设计依据：构建/双源整合评估报告_schema_v1.md + 技术设计文档 §5。
从 store 累积的学生观测点(observation)沿时间轴合成为可交付报告：
  ai_view(数据推演) ⊕ teacher_view(教师观点) ⊕ 显式冲突(alignment)。
"""
import json
from datetime import datetime, timezone

import shiban_store as S


def build_student_report(student_id, period_from=None, period_to=None):
    """从该生的观测点累积合成双源整合报告。个体数据仅本班可见。"""
    obs_list = S.list_observations(student_id=student_id)
    if not obs_list:
        return {"report_id": f"eval_{student_id}", "status": "no_observations",
                "note": "该生尚无观测点，无法评估发展"}

    # 学生与班级元数据
    m = S._connect(S.META_DB, S.META_SCHEMA)
    stu = m.execute("SELECT * FROM students WHERE student_id=?", (student_id,)).fetchone()
    cls = None
    if stu:
        cls = m.execute("SELECT * FROM classes WHERE class_id=?", (stu["class_id"],)).fetchone()
    m.close()
    if not stu:
        return {"report_id": f"eval_{student_id}", "status": "student_not_found"}

    # 时间轴证据（标量，排序）
    timeline = []
    for o in obs_list:
        try:
            dim = json.loads(o["dimension"])
            ev = json.loads(o["evidence"])
        except (TypeError, json.JSONDecodeError):
            dim, ev = {}, {}
        ai = ev.get("ai_data", {})
        signal = None
        if "pass_rate" in ai:
            signal = f"pass {ai['pass_rate']}"
        timeline.append({
            "from": f"观测 {o['obs_id']}", "at": o["recorded_at"],
            "dimension": {"kp": dim.get("knowledge_point"), "scaffold": dim.get("scaffold_type"), "level": dim.get("cognitive_level")},
            "signal": signal, "trend": ai.get("trend", "flat"),
        })

    # ai_view：从观测点推演（示意规则：看懂不懂入口；后续接 LLM 深化）
    ai_view = {
        "assessment": "由 %d 个观测点累积：%s" % (
            len(obs_list), "；".join(t["signal"] for t in timeline if t["signal"])),
        "confidence": "中（基于已记录观测点）",
        "data_basis": [t["from"] for t in timeline],
    }

    # teacher_view：取最近的 teacher_said 观测
    teacher_view = None
    for o in obs_list:
        try:
            ev = json.loads(o["evidence"])
        except (TypeError, json.JSONDecodeError):
            ev = {}
        ts = ev.get("teacher_said")
        if ts and isinstance(ts, dict):
            teacher_view = {
                "assessment": ts.get("text", ""),
                "source": "teacher_said",
                "confidence": str(ts.get("confidence", "0.9")),
            }
            break

    # alignment：冲突显式化
    statuses = [o["alignment"] for o in obs_list if o.get("alignment")]
    status = "conflict" if "conflict" in statuses else ("partial" if "partial" in statuses else "agreed")
    conflicts = []
    for o in obs_list:
        if o.get("alignment") != "conflict":
            continue
        try:
            dim = json.loads(o["dimension"]) if o.get("dimension") else {}
        except (TypeError, json.JSONDecodeError):
            dim = {}
        conflicts.append({
            "dimension": {"kp": dim.get("knowledge_point"), "scaffold": dim.get("scaffold_type"), "level": dim.get("cognitive_level")},
            "ai": "数据侧", "teacher": "教师侧", "resolution": o.get("integrated"),
        })

    return {
        "report_id": f"eval_{student_id}",
        "schema_version": "v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "student": {"student_id": stu["student_id"], "class_id": str(stu["class_id"]), "name": stu["name"]},
        "period": {"from": period_from, "to": period_to},
        "timeline_evidence": timeline,
        "ai_view": ai_view,
        "teacher_view": teacher_view,
        "alignment": {"status": status, "points": conflicts},
        "integrated": "；".join(str(o.get("integrated") or "") for o in obs_list if o.get("integrated")) or "暂无整合结论",
        "recommendation": "建议后续课重点观测并对照小测验证",
        "audience_note": "面向教师本人（内部洞察）；交付外部须去除冲突展示并标注责任边界",
    }


if __name__ == "__main__":
    import sys
    sid = sys.argv[1] if len(sys.argv) > 1 else "stu_2026_01"
    print(json.dumps(build_student_report(sid), ensure_ascii=False, indent=2))