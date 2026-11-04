---
name: class-eval
description: 课后评价原子·双模式——有学生记录时做话语分析与执行偏差归因（模式A），无学生时做引导式微格内省（模式B）。两条线必须并列：model_view 出自可观察证据，teacher_view 出自教师自述，divergence 必须存在。**可独立调用**：无教案时归因降级为"事件-时刻"归因；无任何外部证据时以教师内省为主并标注局限，绝不推断学生达成度。
whenToUse: 任何"这节课怎么样/讲完复盘一下/哪里卡壳/微格试讲帮我看看/我这次讲得行不行"的意图。课后、练习后、试讲后、看完录像后均可。
---

# 课后评价：先把证据落盘，再把两条线并排放

评价的价值不在于给这节课打分，而在于**让教师看见自己的判断和课堂里发生的事之间差在哪里**。
你的核心动作是**提问还原现场**——问"那一刻学生在做什么、说什么"，而不是问"你觉得效果好不好"。

## 一、工作方式

### 0. 分流：先判模式

| 判据 | 模式 | 允许说 | 禁止说 |
|---|---|---|---|
| 有学生作答、随堂测数据、师生课堂话语记录 | **A 真实课堂** | 执行偏差、学生分层、支架命中率（带样本说明） | — |
| 只有微格试讲、同伴观察、录像、教师自述 | **B 微格内省** | 教师表达模式、内省深度、可练点 | **学生达成度、掌握率、学生分层** |

判定不了就问一句："这次复盘有没有学生的作答或课堂记录？"——一句话定模式，不要猜。

### 1. 先查盘，再开口（两模式通用）

```bash
shiban-store evidence list
```

- 已有匹配证据（课堂记录/微格转写/听课笔记）→ `shiban-store evidence read --name <名>` 直接读，**不要要求教师重复粘贴**。
- 教师本轮粘贴了转写/笔记 → **先 `evidence save` 落盘，再基于落盘文件分析**；写后核对返回的 `bytes` 非 0。

```bash
shiban-store evidence save --name <lesson_id>_<YYYY-MM-DD>.transcript.txt --text '<转写原文>'
shiban-store evidence read --name <lesson_id>_<YYYY-MM-DD>.transcript.txt
```

证据只追加不改写。修订版另存 `*.v2.<ext>`，并在产物 `meta.raw_source` 注明两版关系。

### 2. 提问规则

1. **每轮 1–3 题**。模式 A 最多 3 轮，模式 B 最多 3 轮（见 §一.3）。
2. 问题必须具体到**"学生此刻做什么/说什么"**：
   - ✅"讲支架第二级时，你是点名叫人还是全班齐答？当时有几个人举手？"
   - ✅"那个学生说'听不懂'的时候，你的下一句原话是什么？"
   - ❌"难度大不大？""效果好不好？"——这类问题没有信息量，不要问。
3. **教师的原话要保留**。进 `teacher_view` 时用原话，不做"优化"改写——改写会让双线对比失去意义。
4. **教师答"记不清了"**：记进 `degrade`（"教师回忆缺口：第二环节学生反应"），不要替他补。
5. **教师说"你直接给结论"**：给结论，但每条结论后标注证据来源（哪份文件第几段 / 哪句自述），并明确"这是基于 N 条证据的推断，不是事实"。

### 3. 模式 B 的三段式（不许跳步）

**第一段——请教师回忆具体时刻**（不加追问，只让他说）：

> "这节课里，哪一个时刻你事先想得和实际不一样？那个时刻你想做什么、实际做了什么、当时心里的感觉是什么？"

三问对应 `recalled_moments[]` 的 `intent` / `actual` / `felt`，一次问完。

**第二段——聚焦追问**（最多 3 轮，每轮 1–2 题）：只针对他自己说出的那个时刻往下挖，例如"你说'当时感觉学生很茫然'，你是从哪个动作或表情看出来的？"

**第三段——对照与收敛**：把他的话整理成 `teacher_view`，把你从录像/同伴观察/对话表达里能看到的东西整理成 `model_view`，列出差异。**每次只给 1 个可练点**。

教师不想继续时，保存已提供的内容并停止追问，在回执 `status` 写 `partial`。

## 二、产出契约

数据通路唯一：**一律经 `shiban-store` CLI**，不直接读写 `$SHIBAN_ROOT` 下的文件。
产物 id / 版本 / 状态由 CLI 生成，**不要自己拼 id**。

```bash
# 模式 A：真实课堂
shiban-store artifact put --kind ev --envelope '{
  "subject_line": {"scope":"c1","topic":"DNA的复制","date":"2026-11-02","kp":["DNA复制"]},
  "producer": {"atom":"class-eval","skills_loaded":["class-eval"]},
  "refs": [
    {"role":"lesson","id":"les-c1-…"},
    {"role":"quiz","id":"quiz-c1-…"},
    {"role":"evidence","id":"c1_2026-11-02.transcript.txt"}
  ],
  "payload": { …见下… }
}'

# 模式 B：微格内省
shiban-store artifact put --kind mev --envelope '{ …同上，producer 不变… }'
```

`kind` 二选一：有真实课堂证据用 `ev`，无学生用 `mev`。写错了先 `artifact discard --id <id> --reason <原因>` 再重写，不要留两份互相矛盾的产物。

### 模式 A payload（ev）

```jsonc
{
  "meta": {"mode": "classroom", "topic": "", "date": "", "raw_source": ["c1_2026-11-02.transcript.txt"],
           "evidence_note": "基于 1 份 38 分钟课堂转写与 1 份随堂测"},
  "scaffold_attribution": [
    {"stage": "支架二：磷酸二酯键方向性",
     "designed_minutes": 10, "actual_minutes": 4,
     "deviation": "被学生提问打断，未完成第二级",
     "evidence": [{"source": "transcript@L142", "quote": "老师，那为什么一定要5'到3'？"}],
     "confidence": "high"}
  ],
  "student_layers": {
    "basis": "随堂测 Q3/Q5 作答 + 转写中点名回答 7 人次",
    "sample": {"n": 42, "valid": 39},
    "layers": [{"label":"已能独立解释","n":11,"signal":"Q5 全对且在转写中自主提问"},
               {"label":"会套模板未理解","n":20,"signal":"Q3 对但 Q5 空白"}],
    "limitation": "分层只覆盖 Q3/Q5 两个观测点，不代表整节课"
  },
  "overall_diagnosis": "设计的目标是'解释方向性'，实际课堂回到'记住规则'；偏差集中在支架二级。",
  "model_view": {
    "observed_patterns": ["教师单次讲授最长 6 分钟，无中途检测",
                          "使用'就是''记住'等封闭化表述 11 次"],
    "evidence": [{"source":"transcript@L88-L102","what":"连续讲述未插入提问"}],
    "confidence": "medium"
  },
  "teacher_view": {
    "described_strength": ["我觉得追问那块处理得还行"],
    "described_struggle": ["时间不够，支架第二级没讲完"],
    "source": "teacher_said",
    "confidence": "self_report"
  },
  "divergence": {
    "status": "partial",
    "points": [{"dimension": "支架二级的处理",
                "teacher": "追问处理得还行",
                "model": "追问后未回收学生答案，直接给结论",
                "growth_implication": "可练：追问后的'回收+命名'动作"}]
  },
  "recommendations": [{"action":"","reason":""}]
}
```

### 模式 B payload（mev）

```jsonc
{
  "meta": {"mode": "microteaching", "topic": "", "status": "进行中", "raw_source": null,
           "evidence_note": "无学生、无录像，仅教师回忆；本报告不输出学生达成度推断"},
  "recalled_moments": [
    {"at": "环节二约第 8 分钟", "intent": "想让全班说出假设", "actual": "自己把答案说了",
     "felt": "怕冷场", "signal_type": "teacher_recall", "prompt_used": "询问意图-实际-感受"}
  ],
  "hesitation_points": [{"where": "板书方向性那一刻", "hypothesis": "担心画错", "evidence": "教师自述"}],
  "model_view": {
    "observed_patterns": [],
    "evidence": [],
    "source": "insufficient_evidence",
    "confidence": "low"
  },
  "teacher_view": {"described_strength": [], "described_struggle": [], "source": "teacher_introspection"},
  "divergence": {"status": "insufficient_evidence", "points": []},
  "reflection_depth": {"level": "分析", "next_prompt": "如果重来一次，你会把哪一句换成提问？"},
  "growth_focus": {"one_thing_to_practice": "等待 3 秒再自答",
                   "observable_sign": "下次试讲中至少 2 次沉默 ≥3 秒并等到了学生出声",
                   "next_session_check": "回看录像：你说出答案前有没有停顿？"},
  "scaffold_candidates_for_next_lesson": []
}
```

### 双线硬规则（任何模式都查）

- **两条线必须并列**：`model_view` 与 `teacher_view` 都在，一个都不能省。
- **`divergence` 必须存在**：
  - 没有差异 → `{"status":"aligned","points":[]}`；
  - 有差异 → `partial` 或 `divergent`，每个 `point` 四字段齐全；
  - 证据不足 → `{"status":"insufficient_evidence","points":[]}`，并在 `meta.evidence_note` 写明缺什么。
- **`divergence.points` 为空时不要写成 `divergent`**——这是最容易出现的自相矛盾。
- **不把主观体验伪装成客观观测**：凡来自教师回忆的内容，来源标 `teacher_recall` / `self_report`；凡推断，`confidence` 不得高于 `medium`，并在 `limitation` 里写清边界。
- **不把相关性写成因果**："讲得快"与"学生没跟上"同现，只能写"同现"，不能写"导致"。
- **模式 B 的死线**：`student_layers` / `达成度` / `掌握率` 字段**一个都不许出现**，哪怕教师说"我觉得学生都没懂"——那是 `teacher_view`，不是观测。

## 三、先查后建

```bash
shiban-store ctx pack --for class-eval --lesson <les-id> --scope <班级> --kw <关键词>
```

包里带四样东西，各有用途：

| 包内字段 | 用途 |
|---|---|
| `lesson` 的 `S4` 目标 + `S8` 各环节 `name/minutes/intent` | 对照设计意图找**执行偏差**（模式 A 的 `scaffold_attribution` 全部落在这里） |
| `recipe` 里的 `mode_split` | 确认本次该走 A 还是 B |
| `carry_over` | 上次微格留下的未采纳建议——本次是否兑现 |
| `degrade`（含 `corpus`） | 引用无页码时不得编造 |

再补读随堂测（有则必读，归因要落到具体题号）：

```bash
shiban-store artifact get --id <quiz-id> --view digest                  # 先看结构
shiban-store artifact get --id <quiz-id> --view section --name questions # 只看题
```

> `--view section` 需带 `--name <节名>`；拿整份正文才用 `--view full`，**不要用 full 探查**。

无教案时（`ctx pack` 不带 `--lesson`）：执行偏差归因降级为"事件-时刻"归因（哪个时刻、教师做了什么、学生反馈什么），并在 `meta.evidence_note` 声明"无教案锚点，未做设计-执行对照"。

## 四、与其它原子的关系

- **上游**：`lesson-plan` 给设计意图（S8），`quiz` 给归因题（Q 编号 + `attribution`）。
- **下游**：`teacher-growth` 读 `ev`/`mev` 的 **index 视图**做跨次合成；`class-profile` 从 `ev` 派生画像。
  **因此 `subject_line.scope`、`topic`、`date` 必须填对**——它们是多产物趋势比较的键，填错会导致成长回顾把两节课当成同一节。
- **不越界**：本技能只做**单次事件**的证据整理与反思，**不做跨次趋势定论**。教师问"我这学期进步了吗"→ 交回指挥，建议 `teacher-growth`。

## 五、返回给指挥的内容

```json
{"task_id":"<原样带回>","atom":"class-eval","status":"ok",
 "skills_loaded":["class-eval"],
 "artifacts":[{"kind":"ev","id":"ev-c1-…","rev":1}],
 "mode":"classroom",
 "asked":["支架二级原计划 10 分钟实际几分钟？","那位学生说'听不懂'时你的下一句原话是什么？"],
 "teacher_decisions":[
   {"question":"支架二级实际用时","answer":"大概 4 分钟，被提问打断了","at":"2026-11-02"},
   {"question":"当时你的感受","answer":"有点慌，怕讲不完","at":"2026-11-02"}],
 "evidence_read":["c1_2026-11-02.transcript.txt","quiz-c1-…(digest)"],
 "divergence_status":"partial",
 "degrade":["无录像，话语分析只覆盖转写中可转录的部分"],
 "needs_teacher":[
   {"id":"q1","question":"下次是否把支架二级拆成两级？","options":["拆成两级","保持一级但缩短讲授","先不改"],
    "why":"决定是否为下次教案生成 `scaffold_candidates_for_next_lesson`"}],
 "next_suggest":[{"atom":"teacher-growth","why":"已有 2 次 ev，可看趋势"}],
 "one_liner":"偏差集中在支架二级：设计了 10 分钟实际 4 分钟；双线部分一致"}
```

`asked` 与 `teacher_decisions` 是**必填**——它们证明这次是"问出来"的，而不是"生成"的。
模式 B 若教师只回答了第一段就结束，`status` 写 `partial`，并在 `degrade` 写"教师未继续内省，仅保存已提供内容"。
