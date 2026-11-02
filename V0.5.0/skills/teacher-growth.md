---
name: teacher-growth
description: 教师成长原子——把若干次课堂评价、微格内省与教师自评放在一条时间线上，形成 AI/教师双线的成长回顾，每次只给 1 个可练点。**可独立调用**：可从教师指定的事件或自述起步；单次材料不描述趋势，只做局部回顾并声明证据不足。不做人格判断、不做考核排名，教师保有解释权。
whenToUse: 任何"我这段时间有没有进步/回头看看这学期/把几次反思串起来/我总在同一个地方卡/帮我定个练习点"的意图。期中期末回顾、连续试讲后、连续 N 次课后咨询均可。
---

# 教师成长：给一面镜子，不给一张成绩单

成长回顾最容易翻车的地方，是把"我看到的行为变化"说成"你这个人如何"。
你的核心动作是**只谈行为、只谈条件、只给一个练点**——其余候选方向留到教师主动问再说。

## 一、工作方式

### 1. 三个开场问题（必须问，但只问一题就先问第一个）

1. **范围**："这次想回看哪一段？从哪次课到哪次课，还是就这两三次？"
2. **教师的成长问题**："你自己最想知道的是哪件事——是某个环节总卡住，还是整体节奏，还是别的？"
3. **可比性**："这几节课是不是同一个班、同一类课？"——不同班级不同课型**不可比**，问清楚了才能谈趋势。

一次最多 2 题。教师说"你看着办"：按最近 3 条 `ev`/`mev` 出，并在 `degrade` 声明"范围由我代定"。

### 2. 证据规则（这是本原子的生命线）

- **≥ 2 次可比证据**才描述趋势。1 次 → `growth_trend[].direction = needs_more_evidence`，直接说"一次材料看不出变化"。
- **可比 = 同班或同类课 + 同维度**。"口头表达节奏"和"课堂提问设计"是不同维度，不能合成一条趋势。
- **只描述具体行为、条件与变化**：
  - ✅"由'提问后 1 秒自答'变为'提问后停顿并点名'，出现于 11-02 与 11-05 两次课堂"
  - ❌"你的课堂掌控力提升了""你缺乏耐心"——前者是空话，后者是人格判断，都不要写。
- **教师未表达的观点不得代填进 `teacher_view`**。教师没说"我觉得自己进步了"，`teacher_view` 就是空的，不能从你的嘴上长出来。
- **不裁决谁"对"**。`divergence` 只呈现差异与可探究之处，不写"教师判断有误"。
- **成长判断由教师确认或修订**：`teacher_confirmation.status` 收尾为 `pending | confirmed | revised`，不许停在未询问状态就交付。

### 3. 只给一个练点

`next_practice` 只写 **1 个**，且三件套齐全：

| 字段 | 要求 | 反例 |
|---|---|---|
| `one_thing_to_practice` | 一个**具体动作**，不是一种品质 | ❌"提高课堂互动" ✅"等 3 秒再自答" |
| `observable_sign` | 别人（同伴/录像/自己）能数出来的信号 | ❌"互动变多" ✅"一次课中出现 ≥2 次停顿≥3 秒" |
| `next_session_check` | 下次回来时要问的一个问题 | ❌"下次再看看" ✅"回看 11-12 录像：说出答案前有没有停顿？" |

其他候选方向只写进 `defer_candidates[]`（教师主动要时才展开），**不要在报告正文里列三条建议**——列出来就等于做了选择，而选择权是教师的。

### 4. 不做的事

不做考核、排名、等级评定；不推断人格、能力上限、动机（"你其实不太想教"这类话一句都不能有）；不在报告里把某一节课的失误重放给教师看。

## 二、产出契约

数据通路唯一：**一律经 `shiban-store` CLI**，不直接读写 `$SHIBAN_ROOT` 下文件。产物 id / 版本 / 状态由 CLI 生成。

### 读：默认只用 L2 索引

```bash
shiban-store artifact list --kind ev --scope c1
shiban-store artifact list --kind mev --scope c1
shiban-store artifact get --id <ev-id> --view index          # 默认就停在 index
shiban-store artifact get --id <ev-id> --view digest         # 要结构时才下钻一层
shiban-store artifact get --id <ev-id> --view section --name divergence   # 要具体结论
shiban-store artifact get --id <ev-id> --view full           # 只在必须核对原句时
```

**升级规则**：`index` → `digest` → `section` → `full`，每升一级都要有理由。
只有"某个具体事件与本次成长问题直接相关"时才读 `full`——读全量详版会让趋势被单次细节绑架。
报告里要写清 `materials_read[]`：实际读了哪几个 id、读到哪一级。**没读的不许写成读过。**

### 写：`--kind growth`

```bash
shiban-store artifact put --kind growth --envelope '{
  "subject_line": {"scope":"c1","topic":"教师成长回顾 2026-11","date":"2026-11-12"},
  "producer": {"atom":"teacher-growth","skills_loaded":["teacher-growth"]},
  "refs": [
    {"role":"source","id":"ev-c1-…"},
    {"role":"source","id":"mev-c1-…"}
  ],
  "degrade": [],
  "payload": { …见下… }
}'
```

```jsonc
{
  "meta": {"report_id": "", "period": {"from":"2026-09-10","to":"2026-11-12"},
           "status":"confirmed", "focus_question": "我这学期提问环节有变化吗",
           "materials_read": [{"id":"ev-c1-…","depth":"index"},{"id":"ev-c1-…","depth":"section:divergence"}]},
  "timeline": [
    {"at":"2026-09-10","event_ref":"ev-c1-…","focus":"提问后回收","evidence":"写下结论未回收学生答案"},
    {"at":"2026-11-05","event_ref":"ev-c1-…","focus":"提问后回收","evidence":"追问后点名 2 人并归纳"}
  ],
  "model_view": {"observed_patterns":["自答→停顿→回收的动作序列出现，跨 2 次"],
                 "confidence":"medium",
                 "basis":["ev-c1-…(section:divergence)","ev-c1-…(section:divergence)"]},
  "teacher_view": {"self_described_changes":["我觉得第二次提问时没那么慌了"],
                   "self_assessment":"", "source":"teacher_reflection"},
  "divergence": {"status":"partial",
                 "points":[{"dimension":"提问后的处理",
                            "teacher":"感觉平稳了",
                            "model":"行为上自答次数减少，但回收学生答案仅 1 次",
                            "growth_implication":"可练：把'回收'单列为一个动作"}]},
  "growth_trend": [{"focus":"提问后回收","direction":"emerging",
                    "evidence_refs":["ev-c1-…","ev-c1-…"]}],
  "next_practice": {"one_thing_to_practice":"追问后先复述学生原话再评价",
                    "observable_sign":"一次课中 ≥2 次完整复述学生原话",
                    "next_session_check":"回看 11-19 录像：你说'对'之前有没有复述学生的话？"},
  "defer_candidates": [{"focus":"板书方向性","why":"仅 1 次证据，暂不建议"}],
  "teacher_confirmation": {"status":"pending","note":""}
}
```

### 字段硬约束

- **`divergence` 必须存在**：三条线一致 → `{"status":"aligned","points":[]}`；有差异 → `partial`/`divergent` 且每点四字段齐全；证据不足 → `insufficient_evidence`。
- **`growth_trend[].direction`** 只能是 `emerging｜stable｜needs_more_evidence`。用 `stable` 前问自己：是否 ≥ 2 次同维度、同方向的可比事件？不是就退回 `emerging`。
- **`next_practice` 恰好 1 条**。多出来的写进 `defer_candidates[]`。
- **`refs` 与 `timeline[].event_ref` 必须对得上**：时间线里出现的每个 id 都要在 `refs` 里，反之亦然（悬空引用会让 `shiban-store graph` 报错）。
- **`meta.materials_read` 是事实声明**：少读了就写少读，长报告也要诚实。

## 三、先查后建

```bash
shiban-store ctx pack --for teacher-growth --scope c1
```

| 包内字段 | 用途 |
|---|---|
| `preferences` | 教师对反馈方式的偏好（篇幅、是否要评分）——**必须在产出前遵守** |
| `carry_over` | 上次留的练习点是否兑现；未兑现的要在 `timeline` 里标出来，不要当成"没发生" |
| `degrade` | 证据面缺失（如无录像）时，`model_view.confidence` 不得高于 `low` |

如果包里 `carry_over` 显示"上次练习点未执行"：**不指责**，只写"上次的练点在本次材料中未见体现，是否调整练点？"——这是一个问题，不是一个结论。

## 四、与其它原子的关系

- **上游**：`class-eval` 的 `ev`/`mev` 是唯一素材。本技能**不产生新证据**，只做跨次合成。
- **区分**：`class-eval` 管**单次**（这节课哪里偏了），本技能管**跨次**（这几节课之间有没有变化）。教师问单次就交回 `class-eval`。
- **下游**：`lesson-plan` 可把 `next_practice` 的练点写进下一节课的教师活动里——但要教师同意，不要自动塞。
- **不越界**：不读 `class-profile` 的均值做成长证据（均值会掩盖单次波动，趋势必须回到 `ev` 本身）。

## 五、返回给指挥的内容

```json
{"task_id":"<原样带回>","atom":"teacher-growth","status":"ok",
 "skills_loaded":["teacher-growth"],
 "artifacts":[{"kind":"growth","id":"growth-c1-…","rev":1}],
 "evidence_used":{"count":2,"comparable":true,"ids":["ev-c1-…","ev-c1-…"],
                  "read_depth":["index","section:divergence"]},
 "asked":["这次想回看哪一段？","这几节课是不是同一个班？"],
 "teacher_decisions":[
   {"question":"回看范围","answer":"就这两次课","at":"2026-11-12"},
   {"question":"你自己最关心什么","answer":"提问环节有没有变化","at":"2026-11-12"}],
 "divergence_status":"partial",
 "next_practice":{"one_thing_to_practice":"追问后先复述学生原话再评价",
                  "observable_sign":"一次课中 ≥2 次完整复述","next_session_check":"回看 11-19 录像"},
 "degrade":["无录像，行为描述依据转写节选"],
 "needs_teacher":[
   {"id":"q1","question":"这个练点你认可吗？还是换成别的？","options":["认可，就练这个","换一个方向","暂不定"],
    "why":"成长判断须由教师确认，未确认前 teacher_confirmation.status 保持 pending"}],
 "next_suggest":[{"atom":"class-eval","why":"下次课后回来验证练点"}],
 "one_liner":"2 次可比证据：自答减少但回收仅 1 次；练点＝复述后评价"}
```

`asked` 与 `teacher_decisions` 是**必填**。本原子**至少要有 1 轮提问**（`question_budget.min_rounds: 1`）——范围不确认就出回顾，等于替教师决定了他该关心什么。
`teacher_confirmation.status` 停在 `pending` 时，`needs_teacher` 里必须有对应确认项；否则不得交付 `status: ok`，应写 `partial`。
