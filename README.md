# 师伴 ShiBan · 开发仓库

面向**师范生与新手教师**的循证教学辅助 Agent 的开发主仓。

> 当前开发版本：**v0.5.1**（DSH 0.2.1-rc.5 兼容适配），位于 [`V0.5.1/`](V0.5.1/)
> 上一版：**v0.5.0**（空壳重构版），位于 [`V0.5.0/`](V0.5.0/)
> 发布仓（面向使用者）：`shiban-dist`
> 旧版预设仓（已归档）：`dsh-shiban-presets`

---

## 仓库分工

| 仓库 | 面向 | 内容 | 含开发计划/日志 |
|---|---|---|---|
| **本仓库**（`DSH_AI_Edu`，私有） | 团队内部 | 源码、**开发计划**、**开发日志**、设计文档、历史版本 | ✅ **有**（见[下文](#本仓保留开发计划与日志)） |
| `shiban-dist` | 使用者 | 可直接安装的包与部署文档，**不含**计划与日志 | ❌ |
| `dsh-shiban-presets` | — | v0.4.x 的预设，已被 v0.5.0 取代 | ❌ |

---

## 当前版本：v0.5.1

### 这一版更新了什么

v0.5.1 是**兼容性适配**，不改教学逻辑：人格文本、六项技能契约、数据层与产物格式与 v0.5.0 一致。
配套 **DSH 0.2.1-rc.5**。

#### 1. 子 Agent 人格改为独立预设（必须改）

DSH 0.2.1 拒绝 `tool-subagent.persona`，报
`persona is no longer supported ... select it with agentPreset`。

改为：独立预设 `ShiBan_Executor_V0_5_1` + 委派行 `agentPreset` 绑定。
子 Agent 人格文本与 v0.5.0 **逐字一致**（仅 `{{cwd}}` → `{{workdir}}`），工具面刻意窄：
有 `bash` / `fs` / `skill` / `todo`，**无** `subagent`（禁止再委派）、**无** `ask_user`
（子 Agent 存活时调用会被 `DELEGATED_CALLER` 拒绝，问题走回执 `needs_teacher[]`）。

#### 2. 删除 `backgroundMode`

该字段在 0.2.1 的 schema 中已不存在。后台能力**没有消失**——`dsh-subagent` 运行时
里有 58 处 `continuable`，区分 `one-shot` / `continuable` 两种描述符，只是从
"插件配置"移到"运行时托管"。因此人格里并行委派的写法不需要改。

#### 3. `{{cwd}}` 变量改为自注册 `workdir`

DSH 的 system-prompt 只内置 `provider` / `model`。含 `{{cwd}}` 的人格会**每轮报错**
`unknown prompt variable`。这与 0.2.1 无关——0.2.0-rc.2 的检查代码完全相同，
属于**一直存在的隐患**，本版一并修掉。

注册放在 **Host 层主入口**：`assemble()` 先合并 global 层变量再合并 scope 层，
所以预设内的 persona 同样可见，预设里不需要再挂一行插件。

> 曾用包内子路径 `@levilou/dsh-shiban/prompt-vars` 做这件事，实测失败：
> Loader 用裸 specifier `import()`，解析基准取决于进程环境而非 profile，
> 从非 profile 目录解析即 `ERR_MODULE_NOT_FOUND`，而 Loader 对此只
> `catch { logger.error; return }` —— **fiber 从不创建**，审计报 `never started`。
> 已彻底移除该子路径。

#### 4. 修掉三个真 bug

| bug | 现象 | 修法 |
|---|---|---|
| 数据根路径嵌套 | `<root>/versions/vX/versions/vX` | 改传 `SHIBAN_DATA_DIR`（语义为"就是这个目录"），不再传 `SHIBAN_ROOT` |
| 解释器回落失效 | 第一个 Python 失败后不再试下一个 | `execFile` 异步，改为在回调里串行递归尝试 |
| `.cmd` 缺版本门槛 | Windows 上要到运行期才报 SyntaxError | 补齐四段解析 + `Python >= 3.10` 明确报错 |

#### 5. 多系统适配

- **不写死任何绝对路径**：全部由 `import.meta.url` → `fileURLToPath` 推导，经 `node:path` 组装；
- 实测放在含中文与空格的目录下仍能解析到 6 个技能；
- 平台差异走 `!!js process.platform`：Windows 挂 `tool-pwsh`、其余挂 `tool-bash`。

#### 已验证 / 未验证

**已验证**（DSH 0.2.1-rc.5）：39 行配置过真实 schema 31 通过 0 失败；
隔离 `DSH_HOME` 真实启动成功；`runtime.log` 记录 `workdir 变量已注册` / `init ok` /
`doctor: 必需依赖齐全`；从成品 zip 解压后挂载正常；冒烟 10/10。

**未验证**：Windows 实机（`.cmd` 与 `tool-pwsh` 仅静态补齐）；
真实会话内的六原子委派闭环；`fork` 并发行为。

详见 [V0.5.1/CHANGELOG.md](V0.5.1/CHANGELOG.md)。

---

## 上一版：v0.5.0

### 它是什么

一个 DSH 插件。装完是**空壳**——人格、六项原子技能、数据层就位，
教材/素材/证据由教师自行导入或在使用中积累。

### 核心理念

**不代做，引导。** 师伴以提问推动教师把课想清楚，产物里"教师做的决定"与
"它替教师做的判断"必须分得开。

提问分三档：关键决策立即问 / 重要但不阻塞的先记下继续推进 /
待答累计到 **5** 个时强制暂停一次性问完。全程 `ask log` 留痕。

### 目录

```
V0.5.1/
├── package.json          @levilou/dsh-shiban  v0.5.1
├── cordis.patch.yml      预设声明 + 运行时装配 + 工具行
├── lib/index.js          挂载时建数据根、跑 doctor
├── skills/               六项原子技能契约
├── framework/
│   ├── ctx-recipes/      六个原子的上下文配方
│   ├── lesson-template/  教案十一章节体例
│   ├── theory/           理论库（登记 + 提炼框架 + 补充区）
│   └── ask-protocol.md   提问三档协议
├── contracts/            产物信封、回执、配方 schema
├── vendor/
│   ├── services/         Python 数据层（零第三方依赖）
│   └── bin/              跨平台启动器
├── docs/                 部署、架构、教案、导入、能力边界
├── scripts/              打包与冒烟
└── tools/                理论库登记
```


### 快速开始（开发）

```bash
cd V0.5.1
python3 scripts/smoke.py               # 冒烟（10 步）
bash scripts/build-package.sh          # 产出 dist/shiban-0.5.1.{tgz,zip}
python3 vendor/services/shiban_lesson.py   # 单模块自检
```

### 安装到 DSH

在 DSH Web 的**插件**页 → 添加插件 → 填入包目录的绝对路径 →

```bash
dsh plugin --profile web add V0.5.1/dist/shiban-0.5.1.tgz
```

详见 [V0.5.1/docs/DEPLOY.md](V0.5.1/docs/DEPLOY.md)。

---

## 本仓保留开发计划与日志

> **这是本仓库与发布仓（`shiban-dist`）最重要的区别。**
>
> 发布仓只放"能装、能跑"的东西，**不含**任何计划与日志；
> 而开发过程本身是可复用的资产，所以**计划与日志只保留在本仓**。
> 它们不进 npm 包（`package.json` 的 `files` 白名单已排除），也不会出现在使用者拿到的包里。

### 计划

| 文件 | 内容 |
|---|---|
| [V0.5.0/BUILD_PLAN.md](V0.5.0/BUILD_PLAN.md) | 构建计划：P0–P7 阶段划分、每阶段的验收门、风险与对策、修改清单、需要拍板的决策 |
| [V0.5.0/docs/capability.md](V0.5.0/docs/capability.md) | 能力边界：**已实现 / 未实现 / 未验证** 三态（未验证 ≠ 通过） |

`BUILD_PLAN.md` 记录的是**为什么这样设计**——比如为什么放弃向量检索、
为什么提问放指挥层而不是子 Agent、为什么数据根要按版本隔离。
这些决策的理由比结论更有复用价值。

### 日志

| 文件 | 内容 |
|---|---|
| [V0.5.0/logs/PROJECT_LOG.md](V0.5.0/logs/PROJECT_LOG.md) | 逐次推进记录，按时间倒序。每条含：做了什么、**依据是什么**、踩过的坑、遗留事项 |
| [V0.5.0/CHANGELOG.md](V0.5.0/CHANGELOG.md) | 面向版本的变更说明 |

`PROJECT_LOG.md` 的写法约定：

- **记依据，不只记结果**。例如"数据根改按版本隔离"要写清是为了升级不破坏旧版数据。
- **记录踩过的坑**。比如 SQLite 连接未提交就 `close()` 会静默丢数据、pnpm store 位置冲突导致安装失败。
- **历史不改写**。包名变更之类的调整，在日志里加注当时状态，而不是回头把旧记录改掉。
- **遗留事项要留着**。哪些没验证、哪些是推断，比"已完成"更值得记录。

### 运行时不产生日志

使用者机器上的运行时日志在 `$SHIBAN_ROOT/data/logs/runtime.log`（插件挂载时自动写），
那是**运行状态**，与本仓的开发日志是两回事，也不入库。

---

## 历史版本

| 标签 | 说明 |
|---|---|
| `v0.4.3` | 素材闭环：独立素材库、检索复用、隔离编排 |
| `v0.4.0` | 原子组合编排 + 微格内省双线 |
| `v0.3.0` | 持久数据层 + 跨会话继承 |
| `v0.2.0` | 消除技能契约漂移 |
| `v0.1.0` | 基线 |

> `v0.4.3` 的提交与 tag 存在历史遗留（合并提交落在 tag 下游），
> v0.5.0 起改为独立演进。

---

## 数据与隐私边界

| 层 | 内容 | 是否入库 |
|---|---|---|
| 代码 / 技能 / 模板 / 标准 | 骨架 | ✅ 入库 |
| 教材、论文全文 | 语料（版权受限） | ❌ 忽略 |
| 教师课堂记录、学生数据 | 证据 | ❌ 忽略 |
| 个人偏好、画像 | 个人数据 | ❌ 忽略 |

`理论库/`（29 篇论文全文）与 `材料.zip`（99 MB）均不入库。

---

## 贡献与约定

- 提交前跑 `python3 scripts/smoke.py`，红则停。
- 改数据结构时同步更新 `contracts/` 与 `docs/capability.md`。
- **未验证的功能必须在 `capability.md` 标注 `unverified`，不得写成"已支持"**。
