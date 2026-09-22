# 师伴（shiban）Agent · 部署指南

> **本文件是一份部署指导**：它告诉你（人）和/或 AI 助手——**师伴分发包在哪、如何把它部署到一个全新的 DSH 环境中**。
> 全程只安装**空 Agent 框架**，**不包含任何真实教学数据**。数据在首次使用后由使用者自己累积。
>
> 适用版本：师伴 v0.3.0 及以后。

---

## 1. 分发包在哪（获取源）

师伴的完整分发包托管在下面的独立分发仓库（对外**唯一**获取源）：

| 项 | 值 |
|---|---|
| 仓库地址 | **`https://github.com/levilou2517/shiban-dist`**（Public，随时可 clone） |
| 仓库可见性 | Public（公开，任何人可 clone） |
| 内容 | 预设、四技能、数据层脚本、本部署指南 |

（仓库已公开就绪，直接 clone 或取 release 即可）

**分发包目录结构**（clone 或解压后）：
```
shiban-dist/
├── README.md              ← 本部署指南
├── agent-presets/shiban/  ← Agent 预设本体（agent.cordis.yml + preset.yml）
├── skills/*.md           ← 四模块技能（lesson-plan/quiz/class-eval/class-profile）
├── services/*.py         ← 持久数据层（shiban_store / shiban_cli / shiban_report）
├── bin/shiban-store      ← 数据层入口
└── install.sh            ← 可选：一键部署脚本（见 §4）
```

---

## 2. 部署目标位置

| 组件 | 部署到 | 说明 |
|---|---|---|
| Agent 预设 → | `~/.dsh/.agent-presets/shiban/` | DSH 启动时自动扫描此目录，师伴即成为可选 Agent |
| 技能 → | 你的 DSH 工作区 `.dsh/skills/` | dsh 技能扫描根 |
| 数据层 → | 你的 DSH 工作区 `services/` + `bin/` | Python 标准库脚本（零依赖） |
| 持久数据 → | `~/.shiban/data/` | 由 `bin/shiban-store init` 首次初始化（空） |

---

## 3. 部署步骤（给人：手动）

### 3.1 前置
- 已安装 dsh，能启动会话。
- 打开终端，进入你的 DSH 工作区。

### 3.2 获取分发包
```bash
git clone https://github.com/levilou2517/shiban-dist.git
cd shiban-dist
```

### 3.3 装预设（关键：这是 DSH 识别师伴的唯一步骤）
```bash
mkdir -p ~/.dsh/.agent-presets
cp -r agent-presets/shiban ~/.dsh/.agent-presets/shiban
# 确认
ls ~/.dsh/.agent-presets/shiban/   # 应看到 agent.cordis.yml + preset.yml
```

### 3.4 装技能
```bash
mkdir -p .dsh/skills
cp skills/*.md .dsh/skills/
```

### 3.5 装数据层并初始化（空）
```bash
mkdir -p services bin
cp services/*.py services/ && cp bin/shiban-store bin/ && chmod +x bin/shiban-store
bash bin/shiban-store init        # 建空的 ~/.shiban/data（无任何数据）
```

### 3.6 启用
1. 用你的工作区启动 dsh。
2. 会话中选择 Agent 预设 → **师伴**。
3. 发送：`你是谁？能做什么？` 确认生效。

---

## 4. 部署步骤（给 AI：脚本化 / Agent 自举）

下列指令供**具备文件系统与命令执行能力的 AI Agent** 执行，效果等同手动部署：

```
你是部署助手。目标：把 shiban-dist 分发包部署成一个新的师伴 Agent。只装空框架，不写入任何真实数据。
步骤：
1. 确认分发包已在本地（clone 或解压到 <DIST>）。
2. 预设：mkdir -p ~/.dsh/.agent-presets && cp -r <DIST>/agent-presets/shiban ~/.dsh/.agent-presets/shiban
3. 技能：在目标工作区建 .dsh/skills/，把 <DIST>/skills/*.md 复制进去。
4. 数据层：在工作区建 services/ 和 bin/，复制对应文件，chmod +x bin/shiban-store。
5. 初始化空库：运行 bash bin/shiban-store init（确保 ~/.shiban/data 存在且为空的表结构，无任何教师/班级/学生记录）。
6. 校验：
   - 检查 ~/.dsh/.agent-presets/shiban/preset.yml 存在且 name=师伴
   - 检查工作区 .dsh/skills/ 有 4 个技能 md
   - 检查 bin/shiban-store init 后 ~/.shiban/data 有 meta.db / reference.db 且无业务数据
7. 提示用户重启 dsh / 新开会话，选择「师伴」预设即可。
注意：写入 ~/.dsh/.agent-presets 和 ~/.shiban 在 workspace-write 沙箱下会被拒绝——如遇沙箱拒绝，需按沙箱规则请求升级权限（danger-full-access），并说明仅用于部署师伴框架。
```

---

## 5. 仅部署空框架——数据安全边界

- 分发包 **不包含** `~/.shiban/data`、任何班级、学生、教师记录。
- `bin/shiban-store init` 只建表结构，**不播种**任何数据。
- 首次使用后数据才由使用者经 `bin/shiban-store` 逐条录入，跨会话累积。
- 若从别处带来了旧数据，属于使用者自己的导出/导入行为，不在本分发包范围内。

---

## 6. 验证清单

| 检查 | 期望 |
|---|---|
| `~/.dsh/.agent-presets/shiban/preset.yml` | 存在，`name: 师伴` |
| 工作区 `.dsh/skills/` | lesson-plan.md / quiz.md / class-eval.md / class-profile.md |
| `bash bin/shiban-store init` | 提示已初始化 |
| `~/.shiban/data/` | 有 meta.db / reference.db，无业务数据 |
| dsh 会话预设列表 | 出现「师伴」 |

---

## 7. 常见问题

| 问题 | 处理 |
|---|---|
| 预设列表没有师伴 | 确认 `shiban/` 在 `~/.dsh/.agent-presets/`，preset.yml 完整 |
| 技能不出现 | 确认在工作区 `.dsh/skills/` 且含 frontmatter |
| 沙箱拒绝写 `~/.dsh` | 部署脚本需危险权限（仅部署框架用），按 dsh 沙箱规则升级 |
| 想完全重置 | `rm -rf ~/.shiban/data` 后重新 `bash bin/shiban-store init` |

---

*本指南只安装师伴全集空框架，不含任何真实教学数据。数据由使用者首次使用后自行累积。*