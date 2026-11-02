# 预设：师伴（shiban）

本预设由插件包内的 `cordis.patch.yml` 声明，**随 `dsh plugin add` 自动注册**，
无需手工创建目录或编辑配置。

## 身份

| 项 | 值 |
|---|---|
| preset id | `shiban` |
| 显示名 | 师伴 |
| 排序 | 10 |
| 所有者 | 本 bundle（`@levilou/dsh-shiban`） |
| 声明位置 | `cordis.patch.yml` → `- id: preset-shiban` |

## 组成

| 行 | 作用 |
|---|---|
| `shiban-runtime` | 挂载时建数据根、跑 init + doctor，日志写 `$SHIBAN_ROOT/data/logs/runtime.log` |
| `persona` | 指挥人格：引导式提问三档协议（A 立即问 / B 暂存推进 / C 阈值暂停） |
| `skill-filesystem` | 随包技能根 `bundledSkillDir` → 本包 `skills/`（6 个原子）+ 教师自有技能 |
| `tool-subagent` / `tool-subagent-fork` | 委派；子 Agent 人格规定"必须先 skill 加载、必须回执" |
| `tool-ask-user` | `mode: timed`, `timeout: 300`（A/C 档单次传 `timeout: -1` 强制等待） |
| `tool-bash` / `tool-fs` / `tool-fs-search` | 执行与文件访问 |
| `tool-todo` / `tool-goal` / `plan-mode` / `compaction` | 任务、目标、计划模式、上下文压缩 |

## 六个原子技能

`lesson-plan` · `quiz` · `class-eval` · `class-profile` · `teacher-growth` · `html-material`

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
