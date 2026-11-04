# 教案：十一章节体例

## 两种风格，一份内容

同一份 `lesson.json` 可渲染两种体例：

| 风格 | 用途 | 差异 |
|---|---|---|
| `template` | 备课、校内评比 | 完整十一节，含「〇、基本信息」 |
| `competition` | 师范生技能竞赛 | 无〇节，开篇为教材行 + 章节行 + 标题 + 副标题 + 四列信息表 |

```bash
shiban-store lesson render --file lesson.json --style competition --out-dir out/
```

## 章节与槽位

| 章节 | payload 键 | 必填 |
|---|---|---|
| 〇、基本信息 | `meta` | template 风格 |
| 一、课标及教材分析 | `S1.curriculum` / `S1.textbook` | ✅ |
| 二、学情分析（三稿） | `S2.general` / `S2.style` / `S2.starting` | ✅ |
| 三、教学重难点 | `S3`（含可选的难点成因 / 突破策略） | ✅ |
| 四、教学目标 | `S4`（3–4 条，每条一个素养维度） | ✅ |
| 五、教学方法 | `S5` | ✅ |
| 六、教学准备 | `S6` | ✅ |
| 七、教学设计思路 | `S7` | ✅ |
| 八、教学过程（四列表） | `S8` | ✅ |
| 九、教学评价 | `S9.formative` / `S9.summative` | ✅ |
| 十、板书设计 | `S10` | ✅ |
| 十一、教学创新点 | `S11` | ✅ |

## 三条硬约束（`lesson validate` 会查）

1. **一个目标 = 一行**：`S4` 的 id 必须被 `S9.formative.objective_attainment.rows[].objective_id`
   与 `S9.summative.mapping` 同时引用。
2. **时长守恒**：`S8[].minutes` 之和 == `meta.duration_min`。
3. **引用可复现**：`citations[]` 每条都要能被 `corpus read` 找到；没教材就写 `degrade`，**不编页码**。

## 章节重做

只改一节，其余不动：

```bash
shiban-store artifact section --id les-... --name S3 --value '{"key_points":[...]}'
```

## 常见失分点（模板里也标了）

- 教学目标写成"了解/掌握"，不可观测 → 用 `assessable_sign` 补一句可观察的表现。
- 难点来自教材目录而不是学情 → `S2.starting.preconceptions` 必须给出证据。
- 设计意图写"培养学生的 X 素养"就结束 → 要写清"这一步具体怎么培养、突破哪个难点"。
- 情境只在导入出现 → `S7.lines.situation` 与 `S8` 最后一环节必须回扣。
