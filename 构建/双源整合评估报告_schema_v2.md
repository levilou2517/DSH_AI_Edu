# 双源整合评估报告 · schema v2

**用途：** 将单次真实课堂或微格内省证据整理为双线评价，并供教师成长报告纵向合成。此 schema 描述产物，不规定物理存储；生命周期见 `数据生命周期与任务状态_v1.md`。

```json
{
  "report_id": "eval_<date>_<task_id>",
  "schema_version": "v2",
  "generated_at": "ISO-8601",
  "meta": {
    "mode": "classroom|microteaching",
    "topic": "",
    "status": "进行中|已归档",
    "period": {"from": null, "to": null},
    "evidence_refs": ["data/shiban/raw/..."],
    "evidence_note": "数据范围与缺口"
  },
  "timeline_evidence": [
    {"at": "", "source_ref": "", "dimension": "", "signal": "", "trend": "stable|up|down|unknown"}
  ],
  "model_view": {
    "observed_patterns": [],
    "assessment": "",
    "confidence": "low|medium|high",
    "data_basis": []
  },
  "teacher_view": {
    "described_strength": [],
    "described_struggle": [],
    "assessment": "",
    "basis": "",
    "source": "teacher_said|teacher_introspection",
    "confidence": "self_report"
  },
  "divergence": {
    "status": "aligned|divergent|partial|insufficient_evidence",
    "points": [
      {"dimension": "", "teacher": "", "model": "", "growth_implication": "", "next_evidence_to_check": ""}
    ]
  },
  "integrated": "并列呈现证据后的暂定综合，不抹平分歧",
  "growth_focus": {
    "one_thing_to_practice": "",
    "observable_sign": "",
    "next_session_check": ""
  },
  "teacher_confirmation": {"status": "pending|confirmed|revised", "note": ""},
  "audience_note": "面向教师本人；不用于人格判断、排名或未经同意的外部评价"
}
```

## 规则

1. `mode=classroom` 时可保留既有 `overall_diagnosis`、`scaffold_attribution`、`student_layers`、`recommendations` 等模式A扩展字段；学生相关结论必须有学生数据支撑。
2. `mode=microteaching` 时禁止出现学生达成度、学生分层、班级掌握率等推断；主证据是教师回忆，录像/同伴观察是补充。
3. `model_view` 只能描述实际提供的外部记录。无录像或观察记录时，明确标为证据不足，不把对话推断成课堂观察。
4. `teacher_view` 必须保持教师原意；AI 可以整理表达，不可代教师补写或裁决。
5. `divergence` 为必需字段。无差异用 `aligned` 与空数组；证据不足用 `insufficient_evidence`。
6. 每份单次评价最多给一个优先练习点。长期趋势由 `teacher-growth` 在至少两次可比记录上合成。
7. 归档时 L1 详版保留，只新增 L2 索引；原始来源 L0 不得覆盖或删除。
