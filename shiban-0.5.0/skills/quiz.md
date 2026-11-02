---
name: quiz
description: 随堂测原子——通过提问确定"要测什么、为什么要测这个"之后，生成归因型检测题与批阅模板。每题绑定支架环节或考点，附归因逻辑。**可独立调用**：无教案时可直接从知识点出题，支架绑定降级为"考点-认知层次"绑定。
whenToUse: 任何"出题/检验/看看学生懂没懂/查漏补缺"的意图。**不要求**先有教案。
---

# 随堂测：先问"你想知道什么"，再出题

一道题的价值不在于它考了什么，而在于**它错了能告诉你什么**。
你的第一动作永远是问：这次测，你最想从学生的错误里知道什么？

## 一、工作方式

1. **先问三件事**，不要直接出题：
   - 这次测是为了**诊断**（学生卡在哪一步）还是**过关**（能不能达标）？
   - 哪一道"原题"你预计学生会大面积错？错在哪一步？
   - 时长多少？可以占多少分钟？
2. **每题必须能回答**：“学生选 B 说明什么？→ 指向哪个教学环节？”
   写不出来的题，就是纯记忆题，删掉或改造。
3. **不问"难度大不大"**，问"你觉得学生会在哪一步卡壳"——后者才有信息量。
4. 教师要求"多来推演题"时，**确认推演的台阶**：从识别 → 推演 → 解释 → 反驳，每题落在哪一级。

## 二、产出契约

```bash
shiban-store artifact put --kind quiz --envelope '{
  "subject_line":{"scope":"c1","topic":"DNA的复制"},
  "refs":[{"role":"lesson","id":"les-…"}],
  "payload":{
    "meta":{"topic":"","course":"","design_intent":"","suggested_time_min":8,"total_score":35},
    "questions":[{"id":"Q1","type":"single_choice","stem":"","options":[],"score":3,
                  "answer":"","scoring":"","scaffold":"","attribution":""}],
    "grading_template":{"class_summary":{},"individual_grading":[]}
  }
}'
```

### 题目字段要求

| 字段 | 要求 |
|---|---|
| `type` | `single_choice` / `fill_in_blank` / `judgment_or_short_answer` |
| `scaffold` | 有教案时填**支架环节的课堂全称**（不要用 S1/S2 代号）；无教案时填考点+认知层次 |
| `attribution` | **必填**。写清"选 X 说明卡在哪；若多数人选 Y，要回到哪个环节" |
| `scoring` | 主观题必须给分布得分点，不能只给参考答案 |

### 三条硬约束

- **归因绑定**：每题都要有 `attribution`；无教案时在 `meta.design_intent` 声明"无教案锚点，归因降级为考点-认知层次"。
- **认知层次**：至少 1 题为应用/分析层；避免纯记忆选择题。
- **考点守恒**：删题时考点并入其他题，不丢弃；在 `revision_log` 记录每次修订。

## 三、先查后建

```bash
shiban-store ctx pack --for quiz --lesson <les-id>
```
包里给的是目标的 `id` 集合与支架环节清单——题目必须能落到这些 id 上。
若班级有历史数据，包里会带上次各题命中率，用它决定哪些考点要加测。

## 四、与教案的关系

- 有 `lesson`：每题绑一个目标（`objective_id`）与一个支架环节；
- 无 `lesson`：只绑考点与认知层次，并在 `design_intent` 里声明；
- 出完题后，若发现某个目标**没有任何题覆盖**，主动提示教师补齐。

## 五、返回给指挥的内容

```json
{"atom":"quiz","status":"ok","skills_loaded":["quiz"],
 "artifacts":[{"kind":"quiz","id":"quiz-…","rev":1}],
 "asked":["这次测是诊断还是过关？","你预计哪题会大面积错？"],
 "teacher_decisions":[{"question":"…","answer":"时长 8 分钟"}],
 "coverage":{"objectives_covered":["O1","O2","O3"],"uncovered":["O4"]},
 "degrade":[],
 "one_liner":"7 题 35 分 8 分钟；O4 未被覆盖，建议补 1 题"}
```

`coverage` 是必填——让"评价覆盖率"从模糊感觉变成可核对的事实。
