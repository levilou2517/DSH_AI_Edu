---
name: html-material
description: 教学素材原子/页面编排技能。管理可复用、可组合的 HTML 教学素材（碱基结构、细胞周期、交互练习件等）。素材是使用中积累的教师个性化外部库，与师伴本体分离，可查可复用。原子是带契约数据接口的组件片段，页面是若干原子的编排组合，层级自由（同一素材可被更上层复用）。产物自包含离线单文件 HTML；引擎以完整文档 iframe/srcdoc + sandbox allow-scripts 隔离各节，外部库固定版本并内化到外部素材库。先查后建：能复用不新建；只有交互目标未知时才询问教师。
whenToUse: 教师需要生成、查找、复用、编排或验收可打开的 HTML 教具/交互素材时。先查外部素材库；无命中再新建原子；已有明确布局和数据时直接执行，不增加不必要确认。
---

## 组合契约

| 项 | 说明 |
|---|---|
| 输入契约 | `必须`：知识点或素材目标；新建时提供可观察的教学目的。`可选`：素材库筛选（`knowledge_point`/`kind`/`subject`）、已命中的 asset id、原子输入数据、页面布局与 sections。交互目标未知时才向教师询问；已明确输入可直接 add/compose。缺少知识点时可按对话中的明确主题生成并标注范围。 |
| 产出契约 | 原子或编排页登记到 `SHIBAN_ROOT/data/assets/<id>/`，主文件为 `main.html`，数据库含 `interface`、`assembly`、哈希和复用计数；同时给出可打开的 `file_path` 和 `compose spec`。开发演示脚本只写指定隔离目录，不预置个人教师库。 |
| 独立可用性 | 可只查库、只复用单原子或从零生成原子；缺少命中时不伪称已有素材。页面可嵌套已有编排页，失败的契约校验不得产生页面或修改复用计数。 |

## 素材归属与边界

素材是**使用中积累的教师个性化外部库**，不是师伴本体：

- 正式素材只存于显式配置的 `SHIBAN_ROOT/data/assets/`，跨会话、跨工作区共享同一 `SHIBAN_ROOT`；不写入 `DSH_AI_Edu`、预设、技能目录或发布包。
- 示例脚本和测试规格可以属于开发验证工具，但必须显式指定隔离数据根；禁止默认写入 `~/.shiban` 或已有真实库。
- 本体交付的是技能契约、脚本和验收文档，不包含教师个人素材。发布师伴时不捆绑 `data/assets` 或 `vendor`。
- `vendor` 是外部素材库的一部分：库名与版本必须固定，内容内化、相对引用；不得运行时联网或依赖未声明版本。
- 文件即可交付与验收：无需 GUI 原生预览。可以直接用浏览器打开 `main.html`；离线编排页中的组件由完整文档 `iframe srcdoc` 承载，并以 `sandbox="allow-scripts"` 隔离每一节。当前引擎允许嵌套编排页，验收以文件、数据隔离和安全边界为准。

## 先查后建与数据路径

生成前先只读查询，不增加复用计数，也不修改真实库：

```text
shiban_asset_list(knowledge_point=?, kind="html", subject=? )
# 或：bin/shiban-store asset suggest --kp <知识点> --kind html
```

命中用途相符的原子/页面：调用 `shiban_asset_get` 读取接口和 assembly，确认需要时调用 `shiban_asset_reuse` 记账后再使用。没有命中：生成自包含 HTML，再调用 `shiban_asset_add` 登记。`shiban_asset_list` 本身只读，不得把查询结果复制进本体源码。

工具等价关系：

```text
shiban_asset_list / get / add / reuse / scan / suggest / compose
shiban_asset_compose_schema  # 从 store 读取当前完整编排规格
shiban_raw_list / raw_read / raw_save
```

CLI 等价入口：

```text
bin/shiban-store asset list [--kind html] [--kp <点>] [--subject <学科>]
bin/shiban-store asset get --id <aid>
bin/shiban-store asset add --id <aid> --kind html --title <t> --file <html> --kp <点> \
  [--params '<json>'] [--parent <宿主页>] [--assembly '<json>']
bin/shiban-store asset reuse --id <aid>
bin/shiban-store asset suggest --kp <点> --kind html
bin/shiban-store asset compose --spec '<json>'
bin/shiban-store asset compose --spec-file <规格.json>
bin/shiban-store asset compose --spec-stdin
bin/shiban-store asset compose --spec-schema
```

## 原子与页面契约

- 原子：`data/assets/<atom>/main.html`，自包含、离线可开，`params.interface` 声明输入字段。
- 页面：`data/assets/<page>/main.html`，`assembly.sections` 记录引用和每处喂数；页面也可作为更上层页面的组件。
- `window.__MATERIAL_DATA` 是每个 iframe/srcdoc 节的输入边界；同一原子多次出现必须使用各自数据，不依赖全局共享状态。
- 旧字段兼容：历史数据若在 `params.interface` 中声明契约，继续有效；`interface_schema` 是宿主 Tool 对 `params.interface` 的友好别名。若要发现当前完整页面输入契约，使用 `asset compose --spec-schema`；不要假定旧字段已迁移或要求重写旧素材。
- 当前 interface 校验是零依赖子集（required/type/enum），不是完整 JSON Schema；原子应对缺省值负责，契约说明不可校验的边界。

## 编排工作流

1. **查询**：先 `shiban_asset_list` 或 `asset suggest`。查询不递增 `reuse_count`，不落新文件。
2. **选择**：命中则读取 `get` 的 interface/assembly；用途明确时直接复用，不额外确认。只有交互目标、布局或喂数不明确才询问教师。
3. **生成/登记**：未命中才生成原子；使用 `asset add`，kind=`html`，用旧兼容字段 `--params '{"interface": ...}'` 或 Tool 的 `interface_schema` 声明契约。
4. **编排**：用 `compose --spec-schema` 发现页面契约，再调用 compose。页面可引用原子或已有页面；每个节在独立 iframe/srcdoc 中运行，脚本只允许 `allow-scripts`。
5. **复用记账**：成功编排会记录 assembly 并递增原子/子页面 `reuse_count`；内容哈希相同则去重返回已有 asset。失败必须无页面、无半成品、无计数副作用。
6. **交付**：返回外部 `file_path`、asset id、数据根和可复制的 spec；提醒教师直接打开文件验收。不要声称 GUI 原生预览或把个人素材放入源码。

示例目标（由开发脚本生成到隔离目录，不是教师库种子）：

```json
{"page_id":"cycle-demo-page","title":"细胞周期：动画与大纲时间表","sections":[{"asset":"cycle-animation","data":{"interval_ms":800}},{"asset":"cycle-timeline","data":{"items":[{"name":"S","summary":"DNA复制","share":30}]}}]}
```

```json
{"page_id":"base-demo-page","title":"碱基：配对图示与结构式示意","sections":[{"asset":"base-pairing","data":{"left":"A","right":"T"}},{"asset":"base-structure-schematic","data":{"base":"A"}}]}
```

## 科学性与内容边界

- 结构式只有在有可靠来源、键级/价态/立体化学可核验时才称为结构式。无法达到该标准时必须标为“结构骨架示意/教学示意”，说明未覆盖范围；交付验收由教师核对科学性。
- 本版合成示例中的碱基图是几何骨架示意，不是完整化学结构式，不得据此宣称键级、原子坐标或立体化学准确。教学使用前由教师确认并替换为可靠素材。
- 细胞周期示例展示阶段顺序和可配置时间表，不把演示比例解释为真实生物学时长；教师需核对课程口径。

## 产物约束与安全验收

- 编排产物为单个 `main.html`，离线可打开；**"自包含"仅对不引用外部资源的原子成立**。引用 `vendor/` 的原子依赖素材根目录结构，交付时必须连同 `data/assets/vendor/` 保留，且其在沙箱 `srcdoc` 中能否加载相对 `file://` 资源**未经浏览器验证**——不得向教师断言已可用。
- vendor 固定版本、内化在外部素材区，不进入本体发布包。
- 每节数据不同的同一组件互不干扰；不得通过父页全局变量、跨 iframe DOM 或未授权网络资源共享状态。
- 编排可嵌套；复用计数与内容哈希可追溯；旧库仍可读。
- 失败输入（缺必填、错误 enum/type、缺少原子、重复 id）应停止，不留下脏页面、临时文件或错误计数。

## 与其它技能的组合

`lesson-plan`/`quiz` 需要教具时，先查本技能外部库；命中则复用，未命中才新建。`class-profile` 可读取使用记录，但不得把教师个人资产回流本体仓库。
