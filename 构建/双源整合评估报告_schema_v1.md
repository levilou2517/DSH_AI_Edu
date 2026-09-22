# 双源整合评估报告 · schema（可交付体 v1）

> 依据：构建/技术设计文档_数据与评估层_v1.md §5。
> 产出：由 store 的观测点累积 → 沿时间轴合成。
> 原则：报告 = AI 判断 ⊕ 教师判断；冲突**显式化**而非抹掉；面向教师本人（内部洞察）。

```json
{
  "report_id": "eval_2026-09-02_CLS2026_3_STU083",
  "schema_version": "v1",
  "generated_at": "2026-09-22T12:00:00Z",

  "student":     { "student_id": "STU083", "class_id": "cls_2026_g1", "name": "王同学" },
  "period":      { "from": "2026-09-01", "to": "2026-12-31" },

  "timeline_evidence": [
    { "from": "观测 obsA", "at": "2026-09-02", "dimension": {"kp": "DNA复制", "scaffold": "类比", "level": "理解"},
      "signal": "识别层 0.92 → 推演层 0.71", "trend": "down" }
  ],

  "ai_view": {
    "assessment": "识别层达标、推演层下滑，综合转换层未达成",
    "confidence": "中（仅班级级统计，无个体作答矩阵）",
    "data_basis": ["obsA: pass 0.71 下探", "obsB: 识别 0.92"]
  },

  "teacher_view": {
    "assessment": "后半节状态回升，最后题能做，前面走神所致",
    "basis": "课堂观察（模型记录不到的当堂状态）",
    "source": "teacher_said",
    "confidence": "0.9"
  },

  "alignment": {
    "status": "conflict",
    "points": [
      { "dimension": "推演能力",
        "ai": "停滞（0.71 下探）",
        "teacher": "状态波动非能力缺口",
        "resolution": "以连续两轮小测 + 后续课观察定夺" }
    ]
  },

  "integrated": "概念识别达标；推演表现受课堂状态干扰，属状态波动而非能力缺口，建议下一课专注观察其推演环节",
  "recommendation": "给该生的支架补强 / 课堂观察点",

  "audience_note": "本报告面向教师本人（内部洞察）；如需交付外部，须去除冲突展示并标注责任边界"
}
```

## 生成规则
1. `ai_view` 由 store 里该生的观测点 `evidence.ai_data` 沿时间轴统计/推演而成。
2. `teacher_view` 来自观测点 `evidence.teacher_said`（source=teacher_said, confidence 标注）。
3. `alignment.status` = 逐观测点的 alignment 汇总（全部 agreed → agreed；出现 conflict → conflict）。
4. `timeline_evidence` 按 recorded_at 排序，只取标量信号。
5. 个体原始数据仅在本班可见；跨班只走聚合（reference），不进入本报告。