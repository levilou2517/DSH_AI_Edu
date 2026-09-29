---
name: teacher-growth
description: 教师成长原子——基于多次课堂评价、微格内省与教师自评形成双线成长回顾。聚焦可练行为，不做人格判断，教师保有解释权。
whenToUse: 教师希望回看一段时间的教学成长、整合多次反思、追踪练习点或比较自我判断与外部证据时。
---

## 组合契约

| 项 | 说明 |
|---|---|
| 输入契约 | `必须`：教师指定的时间段、事件或成长问题之一。`可选`：L2 历史索引、教师指定的 L1 评价/微格记录、教师自述与偏好。缺少历史记录时可基于当前提供材料生成局部回顾，并声明不能判断趋势。 |
| 产出契约 | 对话摘要；需要留档时写 `data/shiban/teacher_growth_report.json`，含证据引用、AI/教师双线、差异、成长趋势与下一步练习。 |
| 独立可用性 | 可从教师指定的单条记录或自述开始；单次材料不得推断长期成长趋势。 |

## 工作方式

1. 先确认回顾范围和教师最关心的成长问题；不要求必须拥有完整历史库。
2. 默认先查 L2 轻量索引。只有在需要核实具体过程、教师要求回溯或索引证据不足时，才读取其引用的 L0 原始材料或 L1 详版。
3. 将观察分为 `model_view`（有来源的外部/文本证据）和 `teacher_view`（教师自我评价）；不可把教师未表达的观点代填进教师视角。
4. 必须呈现 `divergence`：并列差异及其可探究之处，不裁决谁“正确”。材料不足时明确写 `insufficient_evidence`。
5. 只描述具体行为、条件与变化，不推断人格、能力上限或教师动机。成长判断由教师确认或修订。
6. 每份报告最多提出 1 个优先练习点，给出可观察信号和下次复查问题；其他候选方向只在教师要求时列出。

## 输出 schema

```json
{
  "meta": {"report_id": "", "period": {"from": null, "to": null}, "status": "进行中", "evidence_refs": []},
  "timeline": [{"at": "", "event_ref": "", "focus": "", "evidence": ""}],
  "model_view": {"observed_patterns": [], "confidence": "low|medium|high", "basis": []},
  "teacher_view": {"self_described_changes": [], "self_assessment": "", "source": "teacher_reflection"},
  "divergence": {"status": "aligned|divergent|partial|insufficient_evidence", "points": [{"dimension": "", "teacher": "", "model": "", "growth_implication": ""}]},
  "growth_trend": [{"focus": "", "direction": "emerging|stable|needs_more_evidence", "evidence_refs": []}],
  "next_practice": {"one_thing_to_practice": "", "observable_sign": "", "next_session_check": ""},
  "teacher_confirmation": {"status": "pending|confirmed|revised", "note": ""}
}
```

## 边界

- `evidence_refs` 应使用稳定路径/记录 ID；不复制整段原始课堂材料进历史索引。
- 至少两次可比事件才描述趋势；只有单次材料时 `growth_trend` 标注 `needs_more_evidence`。
- 不能访问未提供或不存在的历史库；报告中列明实际读取的材料范围。
- 这是一面反思之镜，不是考核、排名或诊断教师人格的工具。
