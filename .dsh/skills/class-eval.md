---
name: class-eval
description: 课后评价原子·双模式。模式A「真实课堂」：有师生记录/随堂测时，做话语分析+执行偏差循证归因+学生分层。模式B「微格内省」：无学生（或仅同伴观察/录像）时，以引导教师回忆与结构化内省为核心，绝不推断学生达成度。主 Agent 按证据资源分流。
whenToUse: 任何课后/练习后回顾、反思、看看讲得怎样/哪里卡壳的意图。无课堂记录时不阻塞，走微格内省模式。
---

## 组合契约

| 项 | 说明 |
|---|---|
| 输入契约 | 先判证据资源：存在师生课堂记录或学生随堂测数据走模式A；无学生的微格试讲走模式B。可选：`current_lesson.json`、`current_quiz.json`、课堂录像转写、同伴观察、教师自述。 |
| 产出契约 | 模式A 写 `data/shiban/last_eval.json`；模式B 写 `data/shiban/last_microeval.json`。任务进行中保留详版和 `status: 进行中`；归档时另生成轻量索引，原详版与 L0 原始材料不覆盖。 |
| 独立可用性 | 两种模式均可独立。缺外部证据时用教师内省作为主要证据，明确标注局限。 |

## 模式选择与共同原则

- 有学生作答、师生课堂语言等真实课堂证据：模式A。
- 微格试讲、练习或无学生场景：模式B。不得输出学生分层、学生掌握率或学生达成度推断。
- 任一模式都并列呈现 `model_view`（基于可观察证据）与 `teacher_view`（教师自述/内省）；`divergence` 必须存在。无差异用 `status: aligned` 和空 `points`，证据不足用 `status: insufficient_evidence`。
- 不把主观体验伪装成客观观测，不把相关性写成因果；每条判断注明证据来源与置信边界。
- 评价行为与教学设计，不给教师贴人格标签；教师保有最终解释权。

## 模式A：真实课堂

以现有 `last_eval.json` 结构为基础保留 `meta`、`overall_diagnosis`、`scaffold_attribution`、`classroom_record_analysis`、`student_layers`、`recommendations` 等字段，并追加双线字段：

```json
{
  "model_view": {"observed_patterns": [], "evidence": [], "confidence": "low|medium|high"},
  "teacher_view": {"described_strength": [], "described_struggle": [], "source": "teacher_said", "confidence": "self_report"},
  "divergence": {"status": "aligned|divergent|partial|insufficient_evidence", "points": [{"dimension": "", "teacher": "", "model": "", "growth_implication": ""}]}
}
```

学生分层只可由真实学生作答/测验数据支持；样本或个体矩阵不足时标注估算方法和缺口，不虚构个体事实。具体原字段见 `data/shiban/last_eval.json` 与 `构建/双源整合评估报告_schema_v1.md`。

## 模式B：微格内省

输出到 `data/shiban/last_microeval.json`，使用以下结构：

```json
{
  "meta": {"mode": "microteaching", "topic": "", "status": "进行中", "raw_source": null, "evidence_note": ""},
  "recalled_moments": [{"at": "", "intent": "", "actual": "", "felt": "", "signal_type": "teacher_recall|recording|peer_observation", "prompt_used": ""}],
  "hesitation_points": [{"where": "", "hypothesis": "", "evidence": ""}],
  "teacher_view": {"described_strength": [], "described_struggle": [], "source": "teacher_introspection"},
  "model_view": {"observed_patterns": [], "evidence": [], "source": "micro_record|peer_observer|insufficient_evidence", "confidence": "low|medium|high"},
  "divergence": {"status": "aligned|divergent|partial|insufficient_evidence", "points": [{"dimension": "", "teacher": "", "model": "", "growth_implication": ""}]},
  "reflection_depth": {"level": "描述|分析|批判", "next_prompt": ""},
  "growth_focus": {"one_thing_to_practice": "", "observable_sign": "", "next_session_check": ""}
}
```

内省引导先邀请教师回忆具体时刻（意图、实际行为、当时感受/判断），再提出不超过 3 轮的聚焦追问。录像/同伴观察是可选补充，不得取代教师视角。每次只给 1 个可练点；若教师不愿继续，保存已提供内容并停止追问。没有录音/录像/同伴记录时，`model_view` 只能描述对话中可见的表达模式并将来源标成 `insufficient_evidence`，不得声称观察到课堂行为。

## 与 teacher-growth 的关系

本技能负责单次事件的证据整理与反思，不负责跨次趋势定论。完成后可由 `teacher-growth` 读取 L2 索引或教师指定的若干 L1 详版，综合成长趋势与下一次练习点。

## 允许的扩展字段

模式B 产物可在核心 schema 之外追加向前衔接字段，例如 `scaffold_candidates_for_next_lesson`（把本次内省结论导向下一次 `lesson-plan`）。扩展字段不得覆盖、删改 `model_view`、`teacher_view`、`divergence` 或 `meta.evidence_note` 的原始内容；若本次无外部证据，`evidence_note` 必须写明"不输出学生达成度推断"。
