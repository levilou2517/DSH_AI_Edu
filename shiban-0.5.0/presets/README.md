# 预设说明

DSH 的预设已经是**声明式**的：一条 `@deepseek-ai/dsh-agent-preset` 行就是一个预设，
不需要在 `~/.dsh/.agent-presets/` 下建目录，也不需要手工复制文件。

本包的预设声明在 `cordis.patch.yml` 里：

```yaml
- id: preset-shiban
  name: '@deepseek-ai/dsh-agent-preset'
  config:
    id: shiban
    name: 师伴
    plugins: [ ...]
```

因此：

```bash
dsh plugin --profile web add /path/to/V0.5.0
```

之后预设列表里就会出现「师伴」，**无需任何额外配置**。

## 本目录的作用

`shiban.preset.md` 是**给人看的装配说明**（有哪些行、各自做什么、怎么验证），
不是给 DSH 读的配置——真正的配置只有 `cordis.patch.yml` 一处。

## 想改成默认预设？

默认预设由宿主 profile 的 `agent-preset-registry` 决定，不在本包管辖范围内：

```yaml
# profile 的 cordis.patch.yml
- id: agent-preset-registry
  config:
    default: shiban
```

这是**个人选择**，所以不放进插件包——否则安装插件会改掉所有人的默认。
