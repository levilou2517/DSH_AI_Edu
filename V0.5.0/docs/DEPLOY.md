# 部署指南

## 一句话

```bash
dsh plugin --profile web add <包路径>
shiban-store migrate run --yes        # 仅当你要继承旧版本的素材时
```

装上之后：预设「师伴 v0.5.0」自动出现、数据根自动建好、六项技能随包加载。**不需要任何手工配置。**

## 命名与版本

| 项 | 格式 | 示例 |
|---|---|---|
| 包名 | `@local/dsh-shiban-v<X-Y-Z>` | `@local/dsh-shiban-v0-5-0` |
| 预设 id | `ShiBan_V<X>_<Y>_<Z>` | `ShiBan_V0_5_0` |
| 预设显示名 | `师伴 v<X.Y.Z>` | 师伴 v0.5.0 |
| 数据根 | `$SHIBAN_ROOT/versions/v<X_Y_Z>/` | `~/.shiban/versions/v0_5_0/` |

**为什么这样设计**

- 包名带版本 → 多个版本可**并存**，升级不必先卸载旧版，出问题可回退；
- 预设 id 带版本 → 两个版本的预设不会因 id 冲突而互相覆盖；
- 数据根按版本隔离 → 升级不会破坏旧版数据；**积累的素材通过显式 `migrate` 继承**。

## 安装位置是动态的

DSH 用 `pnpm link` 安装，`node_modules/@local/<包名>` 是指向真实目录的软链。
插件内的所有路径都从 `import.meta.url` / `__file__` 推导，**不写死任何位置**——
换 profile、换机器、升级 DSH 之后依然能找到自己。

查看实际位置：

```bash
shiban-store info
# package_dir   ← 插件装在哪
# legacy_root   ← 本系列根
# data_root     ← 本版本数据根
```

---

## 一、前置条件

| 项 | 要求 | 说明 |
|---|---|---|
| DSH | ≥ 0.2.0-rc.2 | 旧版用 `.agent-presets` 目录，不兼容 |
| Node | ≥ 20 | 插件的运行时装配用 |
| Python | ≥ 3.9（推荐 3.10+） | 找不到会明确报错并给提示 |
| pnpm | 10.x | `dsh plugin` 内部调用 |

**不需要额外 pip 安装**：CLI 只用标准库，且已随包携带依赖闭包（`vendor/python/lib`，3.2 MB）。

可选工具（缺了会降级，不会失败）：

| 工具 | 用途 | 缺失时 |
|---|---|---|
| `pdftotext` | 导入 PDF 教材 | 只能导入已转换的 `.md` |
| Chrome/Chromium | 教案导出 PDF | 只出 HTML |
| Prince | 更好的打印版式 | 用 Chrome 代替 |

`shiban-store doctor` 会逐项检查并告诉你缺什么。

---

## 二、安装（三种方式）

### 方式 A：本地路径（推荐用于测试与开发）

```bash
# 直接在源码目录安装（改动即时生效，适合开发）
dsh plugin --profile web add /path/to/DSH_AI_Edu/V0.5.0

# 或先打包再安装
cd /path/to/DSH_AI_Edu/V0.5.0
tar czf /tmp/shiban-0.5.0.tgz package.json cordis.patch.yml VERSION lib skills \
    framework contracts docs presets vendor scripts tools
dsh plugin --profile web add /tmp/shiban-0.5.0.tgz
```

### 方式 B：Web 界面

DSH Web → 侧边栏 **插件** → 安装 → 填入本地路径或包地址。

### 方式 C：npm 源（若已发布到 registry）

```bash
dsh plugin --profile web add @local/dsh-shiban@0.5.0
```

---

## 三、⚠️ 从 v0.4.x 升级：必须先卸载旧包

v0.4.x 的包名是 `@local/dsh-shiban-preset`，preset id 也是 `shiban`。
**两个包同时启用会因 preset id 重复而加载失败。**

新版包名带版本（`@local/dsh-shiban-v0-5-0`），**原则上可与旧版并存**。
但旧版的数据根是扁平的（`~/.shiban/data`），且旧版的 preset id 也是 `shiban`，
若两者同时启用，界面上会出现两个不同的预设，容易混淆。

推荐做法：

```bash
# 1. 卸载旧版
dsh plugin --profile web remove @local/dsh-shiban-preset

# 2. 安装新版
dsh plugin --profile web add /path/to/V0.5.0

# 3. 旧版素材不迁（v0.4.x 数据模型不同）
#    只确认新版本数据根已就绪即可
shiban-store migrate sources                  # 会看到 legacy 被标为不可迁移
shiban-store info                             # 确认 data_root 指向 versions/v0_5_0
```

---

## 四、常见问题

### pnpm 报 `ERR_PNPM_UNEXPECTED_STORE`

profile 的 `node_modules` 与 pnpm 全局 store 位置不一致。二选一：

```bash
# 方案 1（推荐）：在 profile 目录指定本地 store
cd ~/.dsh/profiles/web
echo 'store-dir=~/.dsh/pnpm-store' > .npmrc
rm -rf node_modules
dsh plugin --profile web add /path/to/V0.5.0

# 方案 2：统一全局 store
pnpm config set store-dir ~/.dsh/pnpm-store --global
```

### pnpm 报 `EACCES: permission denied, symlink .../.local/share/pnpm/store`

同样是指到无法写入的位置。用上面的 `.npmrc` 方案即可。

### 装好后看不到「师伴」预设

```bash
# 1. 配置里到底有没有
dsh --profile web --dump-config | grep -A3 'preset-shiban'

# 2. bundle 是否真在列表
python3 -c "import json;print(json.load(open('$HOME/.dsh/profiles/web/package.json'))['dsh']['profile']['bundles'])"
```

最后一条里必须出现 `@local/dsh-shiban`。没有就说明安装没成功。

### 会话里没有六项技能

先看技能根有没有解析到本包：

```bash
dsh --profile web --dump-config | grep -A8 bundledSkillDir
```

输出里应能看到指向 `<安装路径>/skills`。若确实解析了但技能仍缺席，
检查 `skills/*.md` 的 frontmatter（`name` 必填、必须 kebab-case）。

### CLI 报「找不到 Python 3」

```bash
# 指定解释器
export SHIBAN_PY=/usr/bin/python3
shiban-store doctor
```

Windows 上若只装了 Microsoft Store 版 Python，用 `py -3` 的路径赋值给 `SHIBAN_PY`。

---

## 五、安装后自检清单

```bash
# 1. 环境
shiban-store doctor            # 必需项应全绿
shiban-store version           # 0.5.0

# 2. 运行时日志（插件挂载后自动写入）
cat ~/.shiban/data/logs/runtime.log
# 期望看到： init ok: /home/.../.shiban
#           doctor: 必需依赖齐全

# 3. 预设与技能
dsh --profile web --dump-config | grep -c preset-shiban   # ≥1
dsh --profile web --dump-config | grep -c bundledSkillDir # =1
```

三行都符合后再开会话：

```
新会话 → 选「师伴」→ 说「帮我备一节《DNA的复制》」
```

预期：师伴开始**提问**（不是直接给教案），至少 3 轮，每轮不超过 3 题。

---

## 六、迁移旧版本的素材

**只迁移 v0.5.0 及以后版本**积累的素材。v0.4.x 及更早的材料**不迁**——
这是有意为之：数据模型不同，强行迁移只会带来脏数据。

```bash
shiban-store migrate sources        # 发现历史数据根（低于 v0.5.0 会标 migratable:false）
shiban-store migrate run            # 干跑（默认），只报告不动手
shiban-store migrate run --yes      # 执行
shiban-store migrate run --yes --force   # 覆盖同名文件（默认不覆盖）
```

`migrate sources` 的输出长这样：

```
v0_5_1     files=2   可迁移=true
v0_4_3     files=1   可迁移=false   ← v0.5.0 之前的素材不迁移
legacy     files=0   可迁移=false
```

确有需要从更早版本取某个文件，用 `--from` 显式指定路径：

```bash
shiban-store migrate run --from /path/to/某个旧目录      # 干跑
```

**迁移什么**

| 迁 | 不迁 |
|---|---|
| `corpus/` 教材、课标、论文 | 代码、技能、模板 |
| `data/assets/` 素材库 | 配置、日志 |
| `theory/derived/` 你的补充文献 | 临时文件 |
| `data/evidence/` 原始证据 | |
| `data/artifacts/` 教案等产物 | |

**规则**：不覆盖已存在文件（内容相同的直接跳过）；执行后写 `MIGRATION.json` 留痕；可重复执行。

> **开发阶段不迁移。** 只有部署到真实环境、且你显式运行 `migrate` 时才会动数据。
> 开发时数据根永远是空的。

## 七、数据在哪、怎么带走

```
$SHIBAN_ROOT/                默认 ~/.shiban（本系列根）
├── versions/
│   ├── v0_5_0/              ← 本版本数据根
│   │   ├── data/
│   │   ├── corpus/
│   │   └── theory/derived/
│   └── v0_6_0/              ← 将来升级后，各自独立
│
└── （旧版扁平结构 data/ corpus/ 属 v0.4.x，不在迁移范围）
```

单版本内部：

```
<数据根>/
├── data/
│   ├── artifacts/           教案、随堂测、评价等产物（JSON，可 diff）
│   ├── evidence/            课堂记录、转写（只追加）
│   ├── graph.db             引用图与状态
│   └── logs/runtime.log     插件运行时日志
├── corpus/                  你自己导入的教材、课标、论文
└── theory/derived/          你自己补充的理论文献
```

- 换机器：拷走整个 `$SHIBAN_ROOT` 即可。
- 换工作区：无影响，产物与工作目录无关。
- 卸载插件**不会删除** `$SHIBAN_ROOT`。

---

## 八、卸载

```bash
dsh plugin --profile web remove @local/dsh-shiban
```

数据仍在 `~/.shiban`。彻底清除：`rm -rf ~/.shiban`（**先备份**）。

---

## 九、不想动现有 profile？

用独立 profile 试，不影响日常使用：

```bash
DSH_HOME=/tmp/shiban-test dsh --from-default-profile web test
DSH_HOME=/tmp/shiban-test dsh plugin --profile test add /path/to/V0.5.0
DSH_HOME=/tmp/shiban-test SHIBAN_ROOT=/tmp/shiban-test-data dsh --profile test web
```
