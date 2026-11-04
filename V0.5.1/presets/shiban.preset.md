# 预设：师伴（shiban）

本预设由插件包内的 `cordis.patch.yml` 声明，**随 `dsh plugin add` 自动注册**，
无需手工创建目录或编辑配置。

## 身份

| 项 | 值 |
|---|---|
| preset id | `ShiBan_V0_5_1`（+ 子 Agent `ShiBan_Executor_V0_5_1`） |
| 显示名 | 师伴 |
| 排序 | 10 |
| 所有者 | 本 bundle（`@levilou/dsh-shiban`） |
| 声明位置 | `cordis.patch.yml` → `- id: preset-shiban-v0-5-1` / `- id: preset-shiban-executor-v0-5-1` |

## 组成

| 行 | 作用 |
|---|---|
| `shiban-runtime` | 挂载时建数据根、跑 init + doctor，日志写 `$SHIBAN_ROOT/data/logs/runtime.log` |
| `persona` | 指挥人格：引导式提问三档协议（A 立即问 / B 暂存推进 / C 阈值暂停） |
| `skill-filesystem` | 随包技能根 `bundledSkillDir` → 本包 `skills/`（6 个原子）+ 教师自有技能 |
| `tool-subagent` / `tool-subagent-fork` | 委派。**v0.5.1 起**子 Agent 人格不再写在委派行上，而是由 `agentPreset: ShiBan_Executor_V0_5_1` 绑定到独立子 Agent 预设 |
| `tool-ask-user` | `mode: timed`, `timeout: 300`（A/C 档单次传 `timeout: -1` 强制等待） |
| `tool-bash` / `tool-fs` / `tool-fs-search` | 执行与文件访问 |
| `tool-todo` / `tool-goal` / `plan-mode` / `compaction` | 任务、目标、计划模式、上下文压缩 |

## 六个原子技能

`lesson-plan` · `quiz` · `class-eval` · `class-profile` · `teacher-growth` · `html-material`

## 子 Agent 预设（`ShiBan_Executor_V0_5_1`）

DSH 0.2.1-rc.3 起，`dsh-tool-subagent` 的 `persona` / `toolFilter` 字段直接抛错：

```
tool-subagent: persona is no longer supported; configure persona and tool plugins
in an Agent Preset and select it with agentPreset (spawn only)
```

因此子 Agent 的人格与工具面改在独立预设里声明，由 `tool-subagent` 行用 `agentPreset` 绑定。
工具面刻意窄——不挂 `ask_user`（子 Agent 存活时调用会被 `DELEGATED_CALLER` 拒绝，
问题必须写进回执 `needs_teacher[]`）、不挂委派工具（禁止再委派）、不挂 ralph / workflow。

`fork` 会继承父预设，不能单独换人格，所以只对 `spawn` 生效；需要不同人格时一律用 `spawn`。

## 装配后验证

```bash
shiban-store doctor
shiban-store version
# 会话内：技能目录应出现上述 6 个名字
```

若技能缺席，检查 `bundledSkillDir` 是否解析到了本包 `skills/`：

```bash
dsh --dump-config --profile <profile> | grep -A6 bundledSkillDir
```
