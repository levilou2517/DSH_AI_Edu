# “师伴”系统实现方案与验收标准（V1.1）

**文档性质：** 架构验证阶段指导文件（基于DSH v0.1.2-rc.1实际机制修订）
**适用阶段：** 2026年7月—2026年10月（第二阶段核心工具开发）
**版本：** V1.1（替代V1.0，根据可行性扫描评估报告修订）
**修订日期：** 2026年9月


## 修订说明

V1.0文档基于旧版DSH Preset语法编写，经实地扫描（DSH v0.1.2-rc.1）发现存在代际差异。本版本按当前Cordis插件组合架构重写核心章节，保留原有的教育逻辑设计（过渡性知识评价、四模块闭环、课后对话提取），替换技术实现路径。


## 一、验证目标与边界

### 1.1 本阶段要验证什么

本阶段的目标不是构建生产级产品，而是验证“师伴”系统的**核心架构逻辑**是否成立。具体验证以下三个命题：

**命题一：四模块闭环在DSH中能否跑通。** “教案生成→随堂测→课堂评价→学情更新→下次备课”的数据流能否在主Agent的编排下自动流转。

**命题二：过渡性知识评价逻辑能否稳定运行。** 输入教案文本和学生前测水平，评价函数能否输出有意义的坡度判断（过易/适中/过难），且判断结果与人工判断的一致性达到可接受水平。

**命题三：课后反馈对话能否转化为结构化数据。** AI引导的对话结束后，系统能否从自由文本中提取出班级画像所需的结构化字段（如“支架类型偏好”“实际讲解时长”），提取结果的可用性如何。

### 1.2 本阶段不做的事

- 不接入真实课堂录音或音频转写（输入为结构化师生语言记录）
- 不做前端界面的完整开发（使用DSH Web UI作为交互载体）
- 不做长期记忆的向量检索优化（使用工作区内SQLite完成时序查询）
- 不开展准实验研究（仅用模拟数据和师范生小规模试用验证）

### 1.3 验证成功的标准

| 验证维度 | 通过标准 | 测量方式 |
|---------|---------|----------|
| 闭环跑通 | 从输入教案+学生数据到输出“有效性报告+画像更新”的完整流程可在DSH中自动完成，无需人工干预节点间数据传递 | 端到端流程测试 |
| 评价逻辑 | 对10组测试数据，评价函数输出的坡度判断与人工判断一致率≥70% | 人工标注对比 |
| 对话提取 | 从3-5轮对话中提取的结构化字段，与人工标注的一致率≥80% | 人工标注对比 |
| 成本可控 | 单次完整闭环的LLM API消耗≤0.05元 | ECNU平台credits消耗记录 |


## 二、总体架构：DSH Cordis插件组合

### 2.1 核心架构原则

根据DSH v0.1.2-rc.1的实际机制，本系统的架构原则从V1.0的“四个预置子Agent”调整为：

**一个主Agent（指挥）+ 一枚委派工具（spawn）+ 按需生成的临时子Agent + 工作区共享JSON**

主Agent的persona承担调度指令，负责意图识别和委派。四个模块（教案生成、随堂测、课堂评价、学情分析）不再作为常驻子Agent预置，而是作为**可复用的专家Prompt资产**（skill），在需要时由主Agent通过`tool-subagent`(spawn)携带对应技能指令生成临时子Agent执行任务。子Agent继承父方preset的工具与技能。

这一调整与DSH当前机制完全兼容：`dsh-agent-presets`明确子Agent加入父方组装，`subagent-model-selection`已启用，允许在委派时选择模型路由。

### 2.2 预设目录结构

在 `~/.dsh/.agent-presets/` 下创建 `shiban` 预设目录。**不要手写 `preset.yml + agent.cordis.yml` 从零生成**，应使用官方推荐的 `copy(standard, "shiban")` 复制整目录后修改，避免漏写realm或消费者行。

最终结构如下：

```
~/.dsh/.agent-presets/shiban/
├── preset.yml              # 元数据（name / description）
├── agent.cordis.yml        # cordis插件行列表
└── skills/                 # 技能资产（通过dsh-skill挂载）
    ├── lesson-plan.md
    ├── quiz.md
    ├── class-eval.md
    └── class-profile.md
```

`preset.yml` 仅需 `name` 和 `description`，否则选择器显示裸目录名。

### 2.3 agent.cordis.yml 配置

`agent.cordis.yml` 是**cordis插件行列表**，persona、skill、工具都是插件行。核心配置结构为：

```yaml
# persona：主Agent的调度指令
- id: dsh-persona
  config:
    text: |
      你是“师伴”教学辅助Agent，用户是高中生物学科的新手教师或师范生。
      你的核心目标是帮助教师设计坡度合适的过渡性知识，并通过循证方式持续优化。
      你需要根据对话上下文，通过 tool-subagent (spawn) 委派任务给携带对应
      专家指令的临时子Agent。
      行为准则：副驾驶模式。你提供选项、证据和理由，最终决策权永远在教师手中。

# 工具：文件读写、命令执行、委派
- id: dsh-tool-fs
- id: dsh-tool-bash
- id: dsh-tool-subagent
  config:
    provider: spawn

# 技能：四个模块的专家指令资产
- id: dsh-skill
  config:
    source: skills/lesson-plan.md
- id: dsh-skill
  config:
    source: skills/quiz.md
- id: dsh-skill
  config:
    source: skills/class-eval.md
- id: dsh-skill
  config:
    source: skills/class-profile.md
```

**说明：** 具体插件ID和配置字段以`copy(standard, "shiban")`生成的基准组合为准。上述配置为示意结构，实际落地时需对照基准文件调整。

### 2.4 模型路由配置

ECNU桥接**已配好**，无需重复配置。当前环境事实：

- `llm-pi-ai.providers.ecnu`：baseURL `https://chat.ecnu.edu.cn/open/api/v1`，协议 `openai-completions`
- 模型：`ecnu-max`（DeepSeek-V4.1-Flash）、`ecnu-plus`（Qwen3.8-27B）
- `ECNU_API_KEY` 凭据在位
- 默认模型：`agent-default-model=ecnu/ecnu-max`
- `subagent-model-selection` 已启用，允许子Agent使用`ecnu-plus`

模型分配策略通过**委派级路由**实现，而非preset内每子Agent字段：

| 模块 | 推荐模型 | 实现方式 |
|------|---------|---------|
| 教案生成 | ecnu-max | 委派时指定模型路由 |
| 随堂测生成 | ecnu-plus | 委派时指定模型路由 |
| 学情分析 | ecnu-plus | 委派时指定模型路由 |
| 课堂评价 | ecnu-max | 委派时指定模型路由 |

`reasoning_effort`参数同样由路由控制，在需要深度推理的教案生成场景中建议设为`high`。


## 三、四个模块的技能定义

四个模块的“专业技能定义”放在`skills/*.md`文件中，通过`dsh-skill`插件行挂载，由主Agent通过`tool-skill`读取后附给对应spawn的子Agent。**四个“模块”本质是四段可复用的专家Prompt资产，而非四个独立Agent。**

### 3.1 教案生成技能（skills/lesson-plan.md）

```markdown
你是高中生物教学设计专家，专精过渡性知识（教学支架）的设计。

输入：班级画像摘要、教学目标、知识点标识
输出：2-3个候选过渡性知识方案，每个方案包含：
  - 方案名称与描述
  - 认知坡度分析（概念复杂度/推理步骤数/抽象层级三个维度）
  - 推荐理由（必须引用班级画像中的具体数据）
  - 配套教学支架建议

约束：
  - 每个方案的认知跨度应在学生当前水平和目标水平之间
  - 推荐理由必须包含至少一条来自班级画像的证据
  - 如果班级画像数据不足（少于3次记录），仅呈现方案而不做优先级推荐
```

**评价函数的实现：** 验证阶段采用LLM直接判断，将“过小/适中/过大”量规嵌入上述技能定义，由ecnu-max基于量规对候选方案进行评分和排序。

### 3.2 随堂测技能（skills/quiz.md）

```markdown
你是高中生物随堂测设计专家。

输入：选定的过渡性知识描述、认知层次要求
输出：3-5道检测题（JSON格式），每道题包含：
  - 题干
  - 认知层次标签（记忆/理解/应用/分析）
  - 参考答案

约束：
  - 至少包含1道“应用”或“分析”层次的题目
  - 题目难度应与过渡性知识的预设难度一致
  - 客观题提供标准答案，主观题提供评分要点
```

### 3.3 学情分析技能（skills/class-profile.md）

```markdown
你是班级学情分析师，负责从随堂测数据和课堂记录中提取结构化指标，更新班级画像。

必填字段断言清单：
- class_id（班级标识）
- session_date（课堂日期）
- knowledge_point（知识点）
- scaffold_type（支架类型：类比/逻辑推导/可视化/实验演示）
- cognitive_level（认知层次：记忆/理解/应用/分析）
- pass_rate（通过率，0-1之间的小数）
- session_duration_min（实际讲解时长，分钟）
- teacher_note（课后对话摘要）

输出格式：JSON对象，包含上述所有字段。
如果某个字段无法从输入中提取，标记为 null 并说明原因。
```

### 3.4 课堂评价技能（skills/class-eval.md）

```markdown
你负责课堂话语分析和课后反思引导。

输入：师生语言记录（带说话人标签）、备课时的过渡性知识设计、随堂测数据
输出：
  1. 一致性判断：实际讲解与设计意图的语义距离（高/中/低）
  2. 归因诊断：如果效果不佳，从时间/互动/内容三个维度分析可能原因
  3. 反思对话引导：提出1-2个基于证据的具体追问

对话约束：
  - 追问不超过3轮
  - 追问指向具体事件（“学生当时的反应是什么”），不指向自我评价
  - 允许教师随时退出，已采集信息保存
```


## 四、数据存储：工作区内SQLite

### 4.1 沙箱约束

DSH的`tool-bash`受文件沙箱约束，`workspace-write`策略下只能写工作区（`/home/levi/Documents/WorkSpace/AI_Edu/DSH_AI_Edu`）。预设根目录在会话工作区之外，写入需`sandbox_permissions`升级。

**解决方案：** 将SQLite数据库文件放在工作区内，回避权限问题。

### 4.2 表结构

```sql
CREATE TABLE class_profile (
  id INTEGER PRIMARY KEY,
  class_id TEXT NOT NULL,
  session_date TEXT NOT NULL,
  knowledge_point TEXT,
  scaffold_type TEXT,
  cognitive_level TEXT,
  pass_rate REAL,
  session_duration_min INTEGER,
  teacher_note TEXT
);
```

### 4.3 核心查询

按`class_id + scaffold_type`分组，计算各支架类型的平均通过率，形成“支架类型×通过率”矩阵。这个矩阵是教案推荐的核心证据基础。

如果`sqlite3` CLI已够用，**暂不需要venv**。只有在需要pandas做矩阵计算或复杂数据处理时，才在`.venv/`下建环境。


## 五、Python依赖约定

若实现需要Python包，一律在项目文件夹内构建专用虚拟环境，不污染系统/全局Python。

**落地约定：**

- 虚拟环境目录：`/home/levi/Documents/WorkSpace/AI_Edu/DSH_AI_Edu/.venv/`
- 初始化：`python3 -m venv .venv`
- 激活/使用：一律用绝对路径 `.venv/bin/python`、`.venv/bin/pip`
- 依赖清单：`requirements.txt`（钉版本）
- 安装：`.venv/bin/pip install -r requirements.txt`
- 禁止：`pip install`到系统Python、`pip --user`、全局`conda`环境

**当前场景判定：**

- SQLite建在工作区：`sqlite3` CLI够用 → **暂不需要venv**
- 若把`class-profiler`的矩阵计算做成Python脚本 → 在`.venv/`下建环境，脚本放`scripts/`
- 若只用LLM输出JSON + bash落库 → **全程无需venv**


## 六、验证流程与测试用例

### 6.1 测试数据准备

**模拟班级画像数据：** 构造虚构班级“高二(3)班”的4次课堂记录：
- 支架类型：类比（3次）、逻辑推导（1次）
- 平均通过率：类比81%，逻辑推导68%
- 认知层次分布：记忆层92%，应用层58%

**模拟教案输入：** 高中生物“DNA复制”知识点，教学目标为“理解半保留复制的机制”。

**模拟师生语言记录：** 一段15分钟的课堂对话文本，教师使用“拉链”类比讲解半保留复制，学生有3-4次简短回应。

### 6.2 验证步骤

**Step 1：单模块验证（第1-2周）**

在DSH会话中选择`shiban`预设，分别测试每个模块的独立运行：
- 输入模拟班级画像+教学目标 → 观察教案生成是否输出2-3个候选方案，推荐理由是否引用画像数据
- 输入选定方案 → 观察随堂测是否生成3-5道题，是否包含应用/分析层次
- 输入模拟随堂测结果 → 观察学情分析是否正确写入SQLite
- 输入模拟课堂记录 → 观察课堂评价是否输出一致性判断和追问

**Step 2：闭环验证（第3-4周）**

不指定模块，仅向主Agent发送自然语言指令，观察其是否正确识别意图并委派：
- “我要备DNA复制的课” → 应触发教案生成
- “就用方案A，帮我出几道随堂测” → 应触发随堂测
- “课已经上完了，这是课堂记录” → 应触发课堂评价
- “帮我看看这个班最近的学情” → 应触发学情分析

**Step 3：数据一致性验证（第5-6周）**

用同一组输入数据运行3次完整闭环，对比评价函数的坡度判断是否稳定、对话提取的结构化字段是否一致、SQLite中的数据是否正确累积。

### 6.3 验证记录表

| 测试编号 | 测试模块 | 输入摘要 | 预期输出 | 实际输出 | 是否通过 | 备注 |
|---------|---------|---------|---------|---------|---------|------|
| T-001 | 教案生成 | 高二(3)班画像+DNA复制目标 | 2-3个方案，引用画像 | | | |
| T-002 | 随堂测 | 类比支架方案 | 3-5题，含应用层 | | | |
| ... | ... | ... | ... | ... | ... | ... |


## 七、实施步骤（最小验收闭环）

建议立即执行的最小验收闭环：

**第一步：复制基准预设**

```
copy(standard, "shiban")
```

走宿主侧，无需沙箱升级授权。

**第二步：修改persona与插件行**

编辑`agent.cordis.yml`，将persona改为“师伴主指挥”，挂载`tool-subagent`(spawn)、`tool-fs`、`tool-bash`，挂载四条模块skill。

**第三步：写四条模块skill**

在`skills/`目录下创建四个`.md`文件，包含字段断言清单与评价量规。

**第四步：工作区建SQLite**

在工作区内创建`class_profile`表，写入模拟数据。

**第五步：挂载校验**

用`standingKeyFor("shiban")`挂载校验，然后在新会话开真实试跑Step 1单模块 → Step 2闭环。


## 八、交付物清单

| 编号 | 交付物 | 格式 | 说明 |
|------|--------|------|------|
| D1 | `shiban` 预设包 | `.dshpreset` 文件 | 包含完整目录结构和配置文件 |
| D2 | 验证测试记录表 | Markdown表格 | 包含所有测试用例的输入、输出、判断 |
| D3 | 评价函数一致性报告 | Markdown文档 | 10组测试数据的判断结果与人工标注对比 |
| D4 | 对话提取质量报告 | Markdown文档 | 3-5轮对话的结构化提取与人工标注对比 |
| D5 | 成本消耗记录 | CSV表格 | 每次完整闭环的credits消耗量 |
| D6 | 问题清单与迭代建议 | Markdown文档 | 验证过程中发现的技术问题和改进方向 |


## 九、风险与应对

| 风险 | 现状修正 | 应对措施 |
|------|---------|---------|
| ecnu-max调用不稳定 | 已配置ecnu-max默认；`subagent-model-selection`已允许ecnu-plus降级 | 先用ecnu-plus测试全链路，再切换ecnu-max |
| 子Agent上下文丢失 | 不是“四个子Agent常驻”，而是主Agent多次spawn + JSON文件共享 | 在主Agent编排逻辑中定义中间产物文件规范 |
| SQLite写权限 | 库文件放工作区即规避；`tool-bash`受沙箱，勿指向工作区外 | 工作区建库 |
| 对话提取字段遗漏 | 用字段断言清单skill即可，机制支持 | 在技能定义中明确列出必填字段清单 |
| 预设写入沙箱 | 写`~/.dsh/.agent-presets/`需升级授权 | 用`copy()`规避 |
| 子Agent模型分配 | 靠委派级路由实现，非preset字段 | 在文档中更正表述 |

### 子Agent上下文传递的具体方案

主Agent编排多次spawn子Agent时，子Agent之间的数据传递（如教案生成的输出需要作为随堂测生成的输入）通过**工作区共享JSON文件**实现。在主Agent的调度指令中定义中间产物文件规范：

- 教案生成完成后，将选定方案写入`data/shiban/current_lesson.json`
- 随堂测生成时，从该文件读取选定方案
- 课堂评价完成后，将归因结果写入`data/shiban/last_eval.json`
- 学情分析时，从该文件读取课堂评价结果

子Agent继承父方文件工具与工作区，可读写同一中间JSON。文件系统充当子Agent之间的“共享内存”。
