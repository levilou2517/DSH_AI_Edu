/**
 * @local/dsh-shiban — 运行时装配
 *
 * 这个插件不做业务：它只保证「装好就能用」。
 *   1. 启动时把 $SHIBAN_ROOT 的目录骨架建好（幂等）；
 *   2. 跑一次 doctor，把缺工具的情况写进日志，而不是让用户自己发现；
 *   3. 向模型暴露实际数据根，避免 Agent 猜路径。
 *
 * 业务逻辑全在 Python CLI（vendor/），这里不重复实现。
 *
 * @module @local/dsh-shiban
 */
import { execFile } from 'node:child_process';
import { existsSync, mkdirSync, appendFileSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

export const name = 'shiban-runtime';

/**
 * `systemPrompt` 由数组形式声明。Cordis 的 `Inject.resolve` 把数组元素
 * 一律映射为 `null`，而 `null` 会被 `isNullable` 跳过硬性等待 ——
 * 也就是说数组型 inject **本身就是可选依赖**：拿不到服务不会阻塞启动。
 * 因此 headless 之类不挂提示词注册表的宿主也能正常起，apply 里自行判断。
 */
export const inject = ['systemPrompt'];

const here = dirname(fileURLToPath(import.meta.url));
const require_ = createRequire(import.meta.url);

// 这一行同时完成两件事：给出本包绝对路径，并在模块加载时设置
// SHIBAN_PKG_DIR / DSH_BUNDLED_SKILL_DIR。副作用即时机保证。
import { PACKAGE_DIR, SKILLS_DIR, installPathEnv } from './paths.js';

/** 本包元信息。所有路径都从 here 推导——DSH 用 pnpm link 安装，
 *  node_modules/@local/<pkg> 指向真实目录，升级/换 profile 后位置会变。 */
function pkgMeta() {
  for (const candidate of [join(here, '..', 'package.json'), join(here, 'package.json')]) {
    if (existsSync(candidate)) {
      try {
        return JSON.parse(readFileSync(candidate, 'utf8'));
      } catch {
        /* 继续找 */
      }
    }
  }
  return { name: '@local/dsh-shiban', version: '0.0.0', shiban: {} };
}

const PKG = pkgMeta();
const VERSION_SLUG = 'v' + String(PKG.version || '0.0.0').replace(/[^0-9]/g, '_');

/** 当前工作区根：有 .git 的最近祖先，否则 cwd。与 Python 侧 workspace_root() 一致。 */
function workspaceRoot() {
  let cur = process.cwd();
  for (;;) {
    if (existsSync(join(cur, '.git'))) return cur;
    const parent = dirname(cur);
    if (parent === cur) return process.cwd();
    cur = parent;
  }
}

/** 本系列根（仅当显式设置 SHIBAN_ROOT 时使用，跨工作区共享）。 */
function shibanLegacyRoot() {
  const raw = process.env.SHIBAN_ROOT || join(homedir(), '.shiban');
  return resolve(raw.replace(/^~(?=$|\/|\\)/, homedir()));
}

/** 本版本数据根。默认在工作区内：<工作区>/.shiban
 *  工作区外写入会被 DSH 沙箱拒绝，因此默认不出边界。 */
function shibanRoot() {
  if (process.env.SHIBAN_DATA_DIR) {
    return resolve(process.env.SHIBAN_DATA_DIR.replace(/^~(?=$|\/|\\)/, homedir()));
  }
  if (process.env.SHIBAN_ROOT) {
    return join(shibanLegacyRoot(), 'versions', VERSION_SLUG);
  }
  return join(workspaceRoot(), '.shiban');
}

/** 找到 Python 解释器：$SHIBAN_PY > python3 > python。 */
function pythonCandidates() {
  const out = [];
  if (process.env.SHIBAN_PY) out.push(process.env.SHIBAN_PY);
  if (process.platform === 'win32') {
    out.push('python', 'py');
  } else {
    out.push('python3', 'python');
  }
  return out;
}

/** 定位 CLI：包内 vendor/services/shiban_cli.py。 */
function cliPath() {
  const local = join(here, '..', 'vendor', 'services', 'shiban_cli.py');
  if (existsSync(local)) return local;
  try {
    const pkg = require_.resolve(`${PKG.name}/package.json`);
    return join(dirname(pkg), 'vendor', 'services', 'shiban_cli.py');
  } catch {
    return null;
  }
}

function logLine(root, text) {
  try {
    const dir = join(root, 'data', 'logs');
    mkdirSync(dir, { recursive: true });
    appendFileSync(join(dir, 'runtime.log'), `${new Date().toISOString()} ${text}\n`);
  } catch {
    /* 日志失败不影响启动 */
  }
}

/**
 * 让 CLI 用**与 JS 侧同一个**数据根。
 *
 * 不能直接传 SHIBAN_ROOT：Python 侧把它当「共享根」，还会再拼一层
 * `versions/<slug>`，于是出现 `<root>/versions/vX/versions/vX` 的嵌套。
 * SHIBAN_DATA_DIR 才是「就是这个目录」的原义，两边语义一致。
 * 同时清掉外层可能继承的 SHIBAN_ROOT，避免两套解析打架。
 */
function cliEnv(root) {
  const env = { ...process.env, SHIBAN_DATA_DIR: root, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' };
  delete env.SHIBAN_ROOT;
  return env;
}

function runCli(root, args, timeout = 20000) {
  const cli = cliPath();
  if (!cli) return Promise.resolve({ ok: false, reason: 'CLI 未找到（包不完整）' });
  const env = cliEnv(root);
  const candidates = pythonCandidates();

  // 逐个解释器串行尝试：execFile 是异步的，必须等回调里再试下一个。
  // 在 for 里 return 只跳出同步循环，首个失败就断了。
  return new Promise((done) => {
    let i = 0;
    let lastErr = '';
    const attempt = () => {
      if (i >= candidates.length) {
        done({ ok: false, reason: lastErr || '找不到可用的 Python 解释器' });
        return;
      }
      const py = candidates[i++];
      try {
        execFile(py, [cli, ...args], { env, timeout, windowsHide: true }, (err, stdout, stderr) => {
          if (err) {
            lastErr = `${py}: ${(stderr || err.message).slice(0, 300)}`;
            attempt();
            return;
          }
          try {
            done({ ok: true, data: JSON.parse(stdout) });
          } catch {
            done({ ok: true, data: { raw: stdout.slice(0, 500) } });
          }
        });
      } catch (err) {
        lastErr = `${py}: ${err?.message || err}`;
        attempt();
      }
    };
    attempt();
  });
}

/**
 * 挂载时做一次幂等准备。
 *
 * 使用 `ctx.on('ready')` 之外的时机也可以，但这里只需要「尽早、且不阻塞挂载」。
 */
/**
 * 注册提示词变量 `workdir`（当前工作目录）。
 *
 * 必须在 Host 层做：DSH 0.2.1 的 system-prompt 只内置 provider / model，
 * 旧 `{{cwd}}` 已移除，人格里含它会导致整轮失败。`assemble()` 先合并
 * global 层变量、再合并 scope 层，所以 Host 层注册的变量在预设的 persona
 * 里同样可见，不需要在预设里再挂一行插件。
 *
 * 取值优先 agent 的 cwd，退回进程 cwd —— 不写死任何绝对路径。
 *
 * @param ctx - Host 上下文。
 * @param root - 数据根，仅用于失败日志。
 */
function registerWorkdirVar(ctx, root) {
  const systemPrompt = typeof ctx.get === 'function' ? ctx.get('systemPrompt') : undefined;
  if (systemPrompt === undefined) {
    logLine(root, 'workdir 变量未注册：本宿主没有 systemPrompt 服务（人格请勿使用 {{workdir}}）');
    return;
  }
  try {
    ctx.effect(
      () => systemPrompt.variable('workdir', (context) => {
        const fromAgent = context?.agent?.options?.cwd;
        return typeof fromAgent === 'string' && fromAgent.length > 0 ? fromAgent : process.cwd();
      }),
      'shiban.workdir()',
    );
    logLine(root, 'workdir 变量已注册');
  } catch (err) {
    logLine(root, `WARN workdir 变量注册失败: ${err?.message || err}`);
  }
}

export function apply(ctx) {
  // 关键：把包目录写进进程环境变量。
  // 预设里的 skill-filesystem 需要 bundledSkillDir，而预设 group 子行的
  // baseUrl 可能指向 noop.js，createRequire 解析不到本包。本插件先于预设挂载，
  // 在这里给出绝对路径，配置侧的 !!js 表达式优先读它，不再依赖 baseUrl。
  try {
    installPathEnv();  // 幂等；paths.js 加载时已执行过一次
  } catch (err) {
    logLine(shibanRoot(), `WARN 无法设置包路径环境变量: ${err?.message || err}`);
  }

  const root = shibanRoot();

  registerWorkdirVar(ctx, root);

  try {
    // 目录骨架先建，保证 Python 侧与日志都能落盘
    // 目录骨架：一次性建全，避免 Agent 首次写入时再去创建（沙箱下会失败）
    for (const sub of ['data', 'data/artifacts', 'data/evidence', 'data/logs',
                       'data/indexes', 'data/ask', 'data/assets', 'corpus', 'theory/derived']) {
      mkdirSync(join(root, sub), { recursive: true });
    }
  } catch (err) {
    logLine(root, `FATAL 无法创建数据根 ${root}: ${err?.message || err}`);
    return;
  }

  ctx.on('dispose', () => {
    logLine(root, 'shiban-runtime disposed');
  });

  // 异步自检：失败只记日志，不影响宿主启动
  runCli(root, ['init'])
    .then((init) => {
      logLine(root, init.ok ? `init ok: ${root}` : `init failed: ${init.reason}`);
      return runCli(root, ['doctor']);
    })
    .then((doc) => {
      if (!doc.ok) {
        logLine(root, `doctor failed: ${doc.reason}`);
        return;
      }
      const checks = (doc.data && doc.data.checks) || [];
      const bad = checks.filter((c) => c.ok === false && ['数据根可写', 'python', 'sqlite', 'FTS5'].includes(c.check));
      const optional = checks.filter((c) => c.ok === false && !['数据根可写', 'python', 'sqlite', 'FTS5', '已导入语料'].includes(c.check));
      logLine(root, bad.length
        ? `doctor: ${bad.length} 项必需依赖缺失 -> ${bad.map((c) => c.check).join(', ')}`
        : 'doctor: 必需依赖齐全');
      if (optional.length) {
        logLine(root, `doctor: 可选工具缺失 -> ${optional.map((c) => c.check).join(', ')}（相关功能会降级）`);
      }
    })
    .catch((err) => logLine(root, `runtime error: ${err?.message || err}`));
}

export { shibanRoot, shibanLegacyRoot, workspaceRoot, cliPath, PKG as packageMeta, PACKAGE_DIR, SKILLS_DIR };
