---
name: html-material
description: 教学素材原子——管理可复用、可组合的 HTML 教具：先查外部素材库，命中就复用记账，未命中才新建原子，再按需编排成离线单文件页面。素材是教师个性化外部库（住 $SHIBAN_ROOT/data/assets/），不随师伴本体分发。**可独立调用**：可只查库、只复用单原子、只把外来 HTML 体检入库；交互目标明确时不追问，直接做。
whenToUse: 任何"做个教具/动画/交互图示/把这几张图拼一页/导入我下载的 HTML/有没有现成的可用"的意图。为某节课准备展示素材、把网上的交互件收进自己的库、复用上次做过的组件。
---

# 教学素材：能复用就不新建，要新建就守契约

素材库是教师**自己在使用中攒出来的**东西——它的价值随复用次数增长，而不是随新建数量增长。
你的核心动作是**先查后建**：查不到再动手；动手时守接口契约，交付时保证离线可开。

## 一、工作方式

### 1. 素材归属：外部库，不随包走

- 素材只住 `$SHIBAN_ROOT/data/assets/<id>/`，主文件为 `main.html`。跨会话、跨工作区共享同一个 `SHIBAN_ROOT`。
- **不写进** `DSH_AI_Edu/`、技能目录、预设或发布包。发布师伴时不捆绑 `data/assets` 与 `vendor`。
- `vendor/`（固定版本的第三方库）是外部库的一部分：库名与版本固定、内容内化、相对引用，**不得运行时联网**。
- 产物是**文件即可交付**：教师用浏览器直接打开 `main.html` 验收，不需要 GUI 原生预览。

### 2. 提问规则：少问，问在刀刃上

`question_budget: {min_rounds: 0, max_rounds: 2, max_per_round: 2}`——**交互目标明确时一个字都不必问，直接做。**

只在这三种时候开口：

| 时机 | 问什么 |
|---|---|
| **交互目标未知** | "这个图是让学生拖动配对，还是点开看分层？"——决定 `category` 和内部逻辑 |
| **命中多条、用途难分** | "库里有 3 个'细胞周期'的：静态图示、可调速度动画、时间条。这节课要哪一个？" |
| **外来 HTML 进门** | "这份是网上下的，授权不明（`license: unknown`），只能自己上课用、不随导出包分发，可以吗？" |

不要问的：颜色好不好看、要不要多加动画、字体大不大——这些教师现场会调，问了只是增加负担。

### 3. 三条核心动作

**A. 先查后建**

```bash
shiban-store asset suggest --kp <知识点>
```

- **命中且用途相符** → `shiban-store asset reuse --id <aid>` **记账后再使用**。查询本身只读、不改库；`reuse` 才计数。
- **未命中** → 新建（§3B 或 §3C）。

**B. 新建原子：守契约**

原子是一个**自包含、离线可开**的 HTML 片段，靠 `window.__MATERIAL_DATA` 接收输入：

```html
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<script>
  window.__MATERIAL_DATA = window.__MATERIAL_DATA || {};   // 编排时会注入
  var cfg = Object.assign({ left: "A", right: "T" }, window.__MATERIAL_DATA);  // 缺省值由原子自己负责
</script>
</head><body>…</body></html>
```

- `params.interface` 声明输入字段：`required` / `type` / `enum`。这是**零依赖子集校验**，不是完整 JSON Schema——没声明到的边界，原子要自己兜住（例如给缺省值）。
- 新建原子登记后可再被编排；**同一原子在一页里出现多次，各节数据互不共享**，不得依赖全局变量或跨 iframe DOM。

**C. 编排：每节隔离**

```bash
shiban-store asset compose --spec-schema            # 先查当前规格，不要凭记忆写
shiban-store asset compose --spec '<json>'
```

规格：`{page_id, title, layout:{mode: stack|grid, gap}, sections:[{asset, label, data}]}`。
引擎把每节渲染成 `<iframe sandbox="allow-scripts" srcdoc="…">`——**硬禁止 `allow-same-origin`**，它会与本页同源，破坏隔离。你也不要自己手写 iframe 包装去绕过 `compose`。

**D. 外来 HTML：先体检，再审，后入库**

```bash
shiban-store asset triage --path <目录>             # 先出 CSV 报告，不导入
```

报告输出到 `$SHIBAN_ROOT/data/triage/triage.csv`，含每个文件的 `self_contained` / `external_refs` / `sandbox_safe` / `risks` / `suggested_category` / `needs_interface`。
**与教师一起过一遍报告**：哪些自包含、哪些引外链、哪些有脚本风险、哪些缺数据接口。审完再逐条导入：

```bash
shiban-store asset import --file x.html --title <标题> --category demo|interactive|diagram|quiz-widget|calc|sim|other \
  --stage 导入|建构|巩固|检测|拓展|任意 --kp <知识点> --origin imported-web --license unknown
```

- `origin` 枚举：`generated｜imported-web｜imported-colleague｜textbook-pack｜unknown`。
- `license` 枚举：`own｜cc-by｜unknown｜restricted`。**看不清授权就写 `unknown`，不要猜 `cc-by`**。
- `--dry-run` 可先看会得到什么 `asset_id` 与 `inspection` 结果，不落盘。

## 二、产出契约

数据通路唯一：**一律经 `shiban-store` CLI**，不直接读写 `$SHIBAN_ROOT/data/assets/` 下文件（读取 `main.html` 内容来判断可复用性是允许的，写入一律走 CLI）。

```bash
shiban-store asset list [--kind html] [--kp <点>] [--category <类>] [--stage <段>]
shiban-store asset get --id <aid>                   # 含 interface / assembly / absolute_file_path
shiban-store asset reuse --id <aid>
shiban-store asset compose --spec-file <规格.json>   # 规格复杂时用文件，别拼一长串引号
```

### 编排规格示例

```json
{"page_id":"cycle-page","title":"细胞周期：动画与时间表","layout":{"mode":"stack","gap":16},
 "sections":[
   {"asset":"<aid-anim>","label":"动画","data":{"interval_ms":800}},
   {"asset":"<aid-timeline>","label":"时间表","data":{"items":[{"name":"S","summary":"DNA复制","share":30}]}}]}
```

### 三条硬约束

- **先查后建、命中必 `reuse`**：命中素材却新建同类件，会让库越来越贵、复用计数失真。`reuse` 记账是库价值的唯一度量。
- **每个 `data` 必须满足该素材的 `interface`**：缺必填 / 类型错 / 枚举外 → `compose` 会失败并整体回滚。**失败即停**，不要自动补默认值蒙混过去——那是掩盖契约问题。没有页面、没有半成品、没有错误计数。
- **自包含要经得起打开**：产物声称离线可开，就必须真的离线可开。

### 自包含的边界（必须如实声明）

- "自包含"**只对不引用外部资源的原子成立**。
- 引用 `vendor/` 的原子依赖库目录结构，**交付时必须连同 `data/assets/vendor/` 一起保留**，删掉就坏。
- 这类原子在 `iframe srcdoc` 里能否加载相对 `file://` 资源**未经浏览器验证**——**不得向教师断言"已经可用"**，要写"需在浏览器里实际打开确认"。

### 科学性边界

- 只有键级/价态/立体化学可核验时，才可称"结构式"；否则标为"**结构骨架示意**"，并说明未覆盖范围。
- 示意图不得被表述为真实比例（如细胞周期各阶段的时长）。科学性最终由教师核对。

## 三、先查后建（ctx pack）

```bash
shiban-store ctx pack --for html-material --kp <知识点>
```

| 包内字段 | 用途 |
|---|---|
| `assets` | 就是 `suggest` 的结果（原子 + 页面 + counts）——命中优先复用 |
| `recipe.templates` | 可用的模板与槽位：优先填模板，不要从零生成 |
| `preferences` | 教师对成品的偏好（单页 / 多节 / 是否要标注来源） |
| `degrade` | 无命中时如实说"库内无匹配"，不要假装库里有 |

无 `--kp` 时只有一般性上下文；**知识点是检索主键**，缺了就先问清"这段内容对应哪个知识点"——这是少数值得开口的问题。

## 四、与其它原子的关系

- `lesson-plan` 的 S6 教学媒体可挂 `asset_id`（弱链接）；教案里需要教具时，先来这里查。
- `quiz` 需要交互式检测件时，走 `category: quiz-widget`。
- `class-profile` 可**读**使用记录（`reuse_count`、`last_used_at`）看哪些素材真的在用；但**不得把教师个人素材回流本体仓库**。
- 本技能**不评价教学效果**——哪个教具更有效，是 `class-eval` 与教师的事。

## 五、返回给指挥的内容

```json
{"task_id":"<原样带回>","atom":"html-material","status":"ok",
 "skills_loaded":["html-material"],
 "artifacts":[{"kind":"asset","id":"asset-细胞周期-…","rev":1}],
 "action":"reuse|create|compose|import|triage",
 "assets":[
   {"id":"asset-…","role":"atom","reused":true,"reuse_count":4,
    "path":"<SHIBAN_ROOT>/data/assets/asset-…/main.html"},
   {"id":"asset-…","role":"page","sections":2,"existed":false}],
 "asked":["这个图要拖动配对还是点开看分层？"],
 "teacher_decisions":[{"question":"交互形式","answer":"点开看分层，不要拖动","at":"2026-11-02"}],
 "self_contained":{"page":true,
                   "atoms":["asset-…(引用 vendor，需连目录交付)"],
                   "verified_in_browser":false},
 "degrade":["含 vendor 引用的原子在 srcdoc 中的加载未经浏览器验证"],
 "needs_teacher":[
   {"id":"q1","question":"导入的 3 份外来 HTML 中 2 份授权不明，仍要入库吗？","options":["只入自己的","全部入库仅供自用","先不入"],
    "why":"license=unknown 的素材不随导出包分发，需教师确认用途"}],
 "next_suggest":[{"atom":"lesson-plan","why":"素材已就绪，可挂到 S6"}],
 "one_liner":"复用 1 个原子（第 4 次），编排 2 节单页；vendor 加载需实机打开确认"}
```

`asked` 与 `teacher_decisions` 是**必填**。本原子允许 `asked: []`（交互目标明确时）——但此时必须写 `"asked": []` 并保持字段存在，不要省略；同时在 `one_liner` 说明"目标明确，未追问"。
`self_contained.verified_in_browser` 只能填你**真的打开验证过**的结果；没验证就写 `false` 并在 `degrade` 声明。
