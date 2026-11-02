# 师伴 ShiBan · 开发仓库

面向**师范生与新手教师**的循证教学辅助 Agent 的开发主仓。

> 当前开发版本：**v0.5.0**（空壳重构版），位于 [`V0.5.0/`](V0.5.0/)
> 发布仓（面向使用者）：`shiban-dist`
> 旧版预设仓（已归档）：`dsh-shiban-presets`

---

## 仓库分工

| 仓库 | 面向 | 内容 |
|---|---|---|
| **本仓库**（`DSH_AI_Edu`，私有） | 团队内部 | 源码、开发计划、设计文档、历史版本 |
| `shiban-dist` | 使用者 | 可直接安装的 v0.5.0 包与部署文档 |
| `dsh-shiban-presets` | — | v0.4.x 的预设，已被 v0.5.0 取代 |

---

## 当前版本：v0.5.0

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
V0.5.0/
├── package.json          @local/dsh-shiban-v0-5-0
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
│   ├── bin/              跨平台启动器
│   └── python/lib/       自带标准库闭包
├── docs/                 部署、架构、教案、导入、能力边界
├── scripts/              打包与冒烟
└── tools/                理论库登记
```

### 快速开始（开发）

```bash
cd V0.5.0
python3 scripts/smoke.py               # 六模块冒烟
bash scripts/build-package.sh          # 产出 dist/shiban-0.5.0.tgz
python3 vendor/services/shiban_lesson.py   # 单模块自检
```

### 安装到 DSH

```bash
dsh plugin --profile web add V0.5.0/dist/shiban-0.5.0.tgz
```

详见 [V0.5.0/docs/DEPLOY.md](V0.5.0/docs/DEPLOY.md)。

---

## 开发计划与日志

| 文件 | 内容 |
|---|---|
| [V0.5.0/BUILD_PLAN.md](V0.5.0/BUILD_PLAN.md) | 构建计划（P0–P7 阶段、验收门、风险） |
| [V0.5.0/logs/PROJECT_LOG.md](V0.5.0/logs/PROJECT_LOG.md) | 逐次推进记录：做了什么、依据、踩坑、遗留 |
| [V0.5.0/CHANGELOG.md](V0.5.0/CHANGELOG.md) | 版本变更 |
| [V0.5.0/docs/capability.md](V0.5.0/docs/capability.md) | **已实现 / 未实现 / 未验证** |

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
