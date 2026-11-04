# 更新日志

## v0.5.1 — DSH 0.2.1-rc.5 兼容适配

只做兼容性小更新，**不改教学逻辑**：人格文本、六项技能契约、数据层与产物格式均与 v0.5.0 一致。

### 修了什么

| 项 | v0.5.0 写法 | 在 DSH 0.2.1-rc.5 上的实测 | v0.5.1 改为 |
|---|---|---|---|
| 子 Agent 人格 | `tool-subagent.persona: \|-` | **抛错**：`persona is no longer supported` | 独立预设 `ShiBan_Executor_V0_5_1` + `agentPreset` 绑定 |
| 后台委派 | `backgroundMode: continuable` | schema 中已无此字段（0 处） | 删除 |
| 模型选择 | `modelSelectionSettings: true` | **只有这个字段生效** | **保持 `modelSelectionSettings: true`**（见下方修正说明） |

报错原文（在 0.2.1-rc.5 实测触发）：

```
tool-subagent: persona is no longer supported; configure persona and tool plugins
in an Agent Preset and select it with agentPreset (spawn only)
```

### 新增：子 Agent 预设

`ShiBan_Executor_V0_5_1` —— 模块执行者的人格与最小工具面。
只挂 `persona` / `agent-instructions` / `bash|pwsh` / `fs` / `fs-search` / `skill-filesystem` / `tool-skill` / `tool-todo`。
**不挂** `ask_user`（子 Agent 存活时调用会被 `DELEGATED_CALLER` 拒绝，问题走回执 `needs_teacher[]`）、
不挂委派工具、不挂 ralph / workflow。

`fork` 继承父预设、不能单独换人格，因此 `agentPreset` 只挂在 `spawn` 行上。

### 一处修正：`modelSelection` 是误改

初版把 `modelSelectionSettings` 改成了 `modelSelection`，**这是错的**。

直接调用 DSH 0.2.1-rc.5 的 Config schema 实测：

```
modelSelectionSettings: true  =>  { modelSelectionSettings: true }              ← 生效
modelSelection: true          =>  { modelSelectionSettings: false,
                                    modelSelection: true }                     ← 被忽略
```

`apply()` 内部读的是 `config.modelSelectionSettings === true`，没有任何代码读新名。
由于 `apply` 只对 `persona` / `toolFilter` 显式抛错、其余未知键**静默接受**，
改错的后果是**不报错、但子 Agent 的模型选择能力被悄悄关掉**。

已回退为 `modelSelectionSettings: true`。等 0.2.2 真正移除旧名时会报错，届时再迁。


### 两处运行时失败修正（rc.5 实测）

**① `{{cwd}}` 触发整轮失败**

```
unknown prompt variable "{{cwd}}" in section "deployment:persona-prefix";
registered variables: provider, model
```

DSH 0.2.1-rc.5 的 system-prompt **只内置 `provider` / `model`**，旧变量已移除。
含 `{{cwd}}` 的 persona 会在**每轮**报错。

修法：新增 `lib/prompt-vars.js`（子路径 `@levilou/dsh-shiban/prompt-vars`），
用 `ctx.systemPrompt.variable('workdir', ...)` 自注册变量，排在 persona 之前挂载；
人格里 `{{cwd}}` 改为 `{{workdir}}`。变量名受 `[a-z][a-z0-9_]*` 限制，故不能直接叫 `cwd`。

**② `skill-filesystem` 解析不到包**

```
Cannot find module '@levilou/dsh-shiban/package.json'
Require stack: /home/levi/.dsh/profiles/web/noop.js
```

预设 group 子行的 `baseUrl` 指向 `noop.js`，`createRequire(baseUrl)` 解析不到本包。

修法改为两路并行、互不依赖时序：
- `lib/paths.js` 在**模块加载时**（`import.meta.url` 推导）设置 `DSH_BUNDLED_SKILL_DIR`
  —— 这是 skill-filesystem 原生读取的变量（源码：`config.bundledSkillDir ?? process.env.DSH_BUNDLED_SKILL_DIR`）；
- 配置里的 `!!js` 优先读该变量，为空时退回 baseUrl / cwd 解析。

已测四种场景全通，含 `baseUrl = noop.js`；中文路径、含空格路径、任意 cwd 均可解析到 6 个技能。

**③ executor 预设的 `tool-todo` 缺 config**

`allowParallelInProgress` 在 schema 中是 `.required()`，缺值会让整个预设挂载中断。已补。


### 完整适配核查（0.2.1-rc.5）

对照 0.2.0-rc.2 → 0.2.1-rc.5 的**真实源码差异**逐项核对，结论：

| 包 | 变化 | 对师伴的影响 |
|---|---|---|
| `dsh-tool-subagent` | `persona` 字段被拒；`backgroundMode` / `enableRunInBackground` 删除 | 已改用 `agentPreset`；后台能力由运行时托管，无需配置 |
| `dsh-subagent`（运行时） | **58 处 `continuable`**，区分 `one-shot` / `continuable` 两种 descriptor | **后台能力仍在**，只是从插件配置移到运行时 |
| `dsh-system-prompt` | 只注册 `provider` / `model`；新增 `interpolate: false` | 自注册 `workdir` |
| `dsh-skill-filesystem` | 内部实现改动（home 路径、watcher 错误处理） | schema 未变，`DSH_BUNDLED_SKILL_DIR` 仍有效 |
| `dsh-agent-preset-registry` | 挂载追踪内部重构，`generation.users` 引用计数 | 单个预设可被多个子 Agent 共用，**并发安全** |
| `dsh-persona` / `tool-todo` / `tool-ask-user` / `agent-preset` | **完全相同** | 无影响 |

**更正一条早期判断**：曾以为后台委派能力被删除、只能串行。
实际核查 `dsh-subagent` 运行时后发现 `Background subagent <id>`、
`createSettlementMessage(...)`、`withContinuableReturnGuidance(...)` 一应俱全
——能力保留，改由运行时统一托管。人格里"并行委派"的写法**不需要改**。

**验证**（隔离 DSH_HOME，真实启动）：
- 39 行插件配置逐条过真实 schema：**31 通过 / 0 失败**（其余为命令行类插件，无 Config）
- `dsh --profile web --no-open` 真实启动成功，无报错
- `runtime.log`：`init ok` + `doctor: 必需依赖齐全`
- 工作区默认数据根 `<workspace>/.shiban`，技能目录解析到 6 个技能
- 中文路径、含空格路径均可解析
- 冒烟 10/10


### 修复：`shiban-prompt-vars ... never started`

**现象**（真实会话）：预设激活失败，审计报
`shiban-prompt-vars (@levilou/dsh-shiban/prompt-vars): never started`。

**根因**：Loader 用**裸 specifier** `import()` 加载插件行，其解析基准取决于
进程环境而非 profile 目录。实测同一 specifier：

```
从 profile 目录导入  → 成功
从任意其它目录导入    → ERR_MODULE_NOT_FOUND
```

而 loader 的 `_init()` 对导入异常是 `catch { logger.error; return }` —— **fiber 从不创建**，
审计便报 `never started`。轮询式验证（`--dump-config`、构建、冒烟）都看不出来。

**修法：不再使用包内子路径，workdir 注册并入 Host 层主入口**

- `assemble()` 先合并 global 层变量、再合并 scope 层，所以 **Host 层注册的变量
  在预设 persona 里同样可见**，预设里不需要再挂一行插件；
- 两个预设中的 `shiban-prompt-vars` 行已删除；
- `lib/prompt-vars.js` 删除，`exports` 只保留根入口与 `./paths`。

同时修正 `inject`：Cordis 的 `Inject.resolve` 把数组元素一律映射为 `null`，
`isNullable(null)` 为真即**跳过硬性等待**——故数组型 `inject` 本身即可选依赖，
不挂 `systemPrompt` 的宿主（如 headless）不会因此卡住。

### 修复：数据根路径嵌套

`runCli` 曾把数据根当 `SHIBAN_ROOT` 传给 Python，而 Python 侧对它还会再拼
`versions/<slug>`，产生 `<root>/versions/vX/versions/vX`。
改传 `SHIBAN_DATA_DIR`（语义为「就是这个目录」，两侧一致），并清除继承的 `SHIBAN_ROOT`。

顺带修掉一个真实 bug：`runCli` 的解释器回落写在 `for` 循环里，`execFile` 异步回调中
的 `return` 只跳出同步循环，**第一个解释器失败就不会再试下一个**。改为串行递归尝试。

### 修复：Windows 启动器补齐

`vendor/bin/shiban-store.cmd` 补上与 bash 版一致的：
`%PKG%\.venv` → PATH 上的 `python`/`py` → DSH 自带运行时 的四段解析、
`Python >= 3.10` 版本门槛（明确报错而非稍后 SyntaxError）、UTF-8 环境变量。

### 跨系统与路径约束（本轮硬要求）

- **不写死任何绝对路径**：全部路径由 `import.meta.url` / `fileURLToPath` 推导，
  经 `node:path` 的 `join`/`resolve` 组装，Windows 与 POSIX 一致；
- 实测放在含中文与空格的目录（`/tmp/port2/中文 路径/pkg`）下仍能解析到 6 个技能；
- 平台差异走 `!!js process.platform` 条件：Windows 挂 `tool-pwsh`、其余挂 `tool-bash`。

### 已验证（DSH 0.2.1-rc.5）

配置层：

| 项 | 结果 |
|---|---|
| `--dump-config` 合成 | 两个预设 + 运行时行均正常 |
| 39 行插件配置过真实 schema | **31 通过 / 0 失败**（其余为命令行类插件，无 Config） |
| 委派四行（spawn / fork / codex / claude-code） | 全部通过 |
| `agentPreset` 的 `readDocument()` | 能导出含 `!!js` 的预设，可往返 |
| 提示词变量 | 只使用 `workdir`（自注册），无 `{{cwd}}` 残留 |

运行时（隔离 `DSH_HOME`，真实启动 `dsh --profile web --no-open`）：

| 项 | 结果 |
|---|---|
| 服务启动 | 正常，无报错 |
| `runtime.log` | `workdir 变量已注册` / `init ok` / `doctor: 必需依赖齐全` |
| 数据根 | 默认 `<workspace>/.shiban`；指定 `SHIBAN_DATA_DIR` 时无 `versions/` 嵌套 |
| 从成品 zip 解压后挂载 | 正常 |

跨系统与可移植：

| 项 | 结果 |
|---|---|
| 中文 + 空格路径（`/tmp/port2/中文 路径/pkg`） | 解析到 6 个技能 |
| 硬编码绝对路径 | 0 处（全部由 `import.meta.url` 推导） |
| Windows 启动器 | 四段 Python 解析 + 3.10 版本门槛已补齐（**未在 Windows 实机运行**） |
| 冒烟 `scripts/smoke.py` | 10/10 |

### 未验证

- **Windows 实机**：`.cmd` 启动器与 `tool-pwsh` 路径仅静态补齐，未在 Windows 上运行过；
- 真实会话内的**子 Agent 委派闭环**（六原子逐个委派、`skills_loaded` 回填）；
- 与 `fork` 模式的并发行为；
- `backgroundMode` 删除后的实际行为（运行时持有 `continuable`，但未实测并行/串行）。

### 已知限制

- `@deepseek-ai/dsh-tool-subagent-control/list-agents` 子路径在 **0.2.2** 中被移除；
  当前 rc.5 仍在，0.2.2 正式版发布时需一并处理。
- DSH 0.2.2 另有破坏性更新（cordis 4.0→4.1、`modelSelectionSettings` 移除、`tools.mode` 移除等），
  不在本版范围。

---

## v0.5.0 — 空壳版

### 数据根迁入工作区 + 首次使用需授权

**问题**：首次真实会话显示，数据根 `~/.shiban` 在工作区外，被 DSH 沙箱拦截——
`ask log`、`artifact put` 全部 `PermissionError`，提问与产物都没落盘。

**改动**

- 数据根默认改为 **`<工作区>/.shiban/`**：不出工作区，受沙箱保护，随工作区走。
  显式 `SHIBAN_ROOT` / `SHIBAN_DATA_DIR` 仍可覆盖。
- 新增 `shiban-store bootstrap`：`status` / `scan`（只读）/ `plan` / `run --accept`。
  **扫描不创建任何东西；无 `--accept` 直接 `need_consent` 拒绝。**
- 识别规则全部可在 `.shiban/bootstrap.json` 覆盖，不写死本机路径。
- 语料层不再自行解析 `SHIBAN_ROOT`，统一走 `shiban_core.root()`
  （此前两套解析器不一致，导致写错位置）。
- 运行时插件挂载时一次性建全所有子目录（`data/ask`、`data/indexes` 等），
  避免 Agent 首次写入时创建失败。


### 发布准备

- **包名定为 `@levilou/dsh-shiban`**，发布到 npm（`private: false`、`publishConfig.access: public`、`license: MIT`）。
  此前本地开发用的是 `@local/dsh-shiban-v0-5-0`；改为稳定的 npm 包名 + semver 版本，
  多版本并存的真正隔离点放在**预设 id（`ShiBan_V*`）与数据根（`versions/*`）**。
- `package.json` 增加 `files` 白名单，打包排除 `__pycache__`、`logs/`、`scripts/`、`tools/`。
  实测：270 文件 / 897 KB（压缩）/ 4.0 MB（解压）。

---

## v0.5.0 — 重构内容

一次彻底重构。目标不是加功能，而是把 v0.4.x "文档、PPT、代码三张皮"的问题从根上解决。

### 新增

- **契约层** `contracts/`：产物信封、回执、上下文配方三份 schema + 统一常量。
  代码与技能都从它派生，不再各自定义字段。
- **统一写入通路** `artifact put`：原子写 + 引用图 + 乐观锁 + 环检测，失败全回滚。
  解决了 v0.4.x 中"Agent 直接写文件、状态靠口头声明"的问题。
- **引用图** `graph.db`：强边（目标已存在）与弱边（悬空候选）分开，上游变更沿强边传播 `stale`。
- **读视图分级** `index / digest / section / full`：指挥默认只读索引（<2 KB），治信息过载。
- **上下文包** `ctx pack --for <原子>`：六份配方，返回"恰好够用"的输入，字段名即契约字段名。
- **教案模板与渲染**：十一章节体例，`template` / `competition` 两种风格，
  Markdown / 自包含 HTML / PDF（Prince 或 Chrome，缺失时明确报告而非报错）。
- **语料层** `corpus import/search/read/verify`：带页码锚点，中文 bigram 检索。
- **素材层** `asset triage/import/compose/suggest`：外来 HTML 先体检后入库，
  `iframe sandbox="allow-scripts" srcdoc` 隔离编排。
- **提问协议** `framework/ask-protocol.md`：三档推进（立即问 / 暂存推进 / 阈值暂停），
  默认阈值 5；每次暂存、暂停、回答写 `ask log`，可用 `ask stats` 复盘。
- **能力边界** `docs/capability.md`：已实现 / 未实现 / **未验证** 三态，未验证不算通过。
- **冒烟记录** `scripts/smoke.py`：每模块最小路径，结果写 JSONL 可追溯。

### 变更

- **命名带版本**：包名 `@local/dsh-shiban-v0-5-0`，预设 id `ShiBan_V0_5_0`，显示「师伴 v0.5.0」。
  多版本可并存，升级不必先卸载；旧版若同名 id 冲突也不会互相覆盖。
- **数据根按版本隔离**：`$SHIBAN_ROOT/versions/v<X_Y_Z>/`。升级不破坏旧版数据。
- **素材迁移**：新增 `shiban-store migrate`（sources / run），只迁积累物，
  默认干跑、不覆盖、写 `MIGRATION.json`。**开发阶段不自动迁移。**
- **安装位置动态化**：所有路径由 `import.meta.url` / `__file__` 推导，
  新增 `shiban-store info` 查看实际位置。

- 数据根统一到 `$SHIBAN_ROOT`，工作区不再持有运行数据。
- 技能随包（`bundledSkillDir`），不再依赖会话工作区的 `.dsh/skills`。
- 教案从"候选方案"变为"一份可交付文档"，章节可单独重做。

### 移除

- 序言式自检与大量一次性验证脚本（改为 `scripts/smoke.py` 一条通路 + 日志）。
- 工作区 `data/shiban/*.json` 作为共享内存的做法。

### 已知限制

见 `docs/capability.md` 的「未验证」表。当前最需要验证的是：
Windows 启动器、Chrome 打印分支、真实 `~/.dsh` 安装、大 PDF 导入耗时。
