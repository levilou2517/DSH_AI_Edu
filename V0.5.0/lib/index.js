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

/** 不依赖任何宿主服务的行：只做本地准备。 */
export const inject = [];

const here = dirname(fileURLToPath(import.meta.url));
const require_ = createRequire(import.meta.url);

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

/** 本系列根：$SHIBAN_ROOT 优先，否则 ~/.shiban。 */
function shibanLegacyRoot() {
  const raw = process.env.SHIBAN_ROOT || join(homedir(), '.shiban');
  return resolve(raw.replace(/^~(?=$|\/|\\)/, homedir()));
}

/** 本版本数据根：<legacy>/versions/<vX_Y_Z>。与 Python 侧 shiban_core.root() 一致。
 *  按版本隔离使升级/回退互不破坏；积累的素材用 `shiban-store migrate` 显式继承。 */
function shibanRoot() {
  if (process.env.SHIBAN_DATA_DIR) {
    return resolve(process.env.SHIBAN_DATA_DIR.replace(/^~(?=$|\/|\\)/, homedir()));
  }
  return join(shibanLegacyRoot(), 'versions', VERSION_SLUG);
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

function runCli(root, args, timeout = 20000) {
  const cli = cliPath();
  if (!cli) return Promise.resolve({ ok: false, reason: 'CLI 未找到（包不完整）' });
  const env = { ...process.env, SHIBAN_ROOT: root, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' };
  return new Promise((done) => {
    for (const py of pythonCandidates()) {
      try {
        execFile(py, [cli, ...args], { env, timeout, windowsHide: true }, (err, stdout, stderr) => {
          if (err) {
            // 换下一个解释器；只有全部失败才报
            done({ ok: false, reason: `${py}: ${(stderr || err.message).slice(0, 300)}`, retry: true });
            return;
          }
          try {
            done({ ok: true, data: JSON.parse(stdout) });
          } catch {
            done({ ok: true, data: { raw: stdout.slice(0, 500) } });
          }
        });
        return;
      } catch {
        /* 试下一个 */
      }
    }
    done({ ok: false, reason: '找不到可用的 Python 解释器' });
  });
}

/**
 * 挂载时做一次幂等准备。
 *
 * 使用 `ctx.on('ready')` 之外的时机也可以，但这里只需要「尽早、且不阻塞挂载」。
 */
export function apply(ctx) {
  const root = shibanRoot();
  try {
    // 目录骨架先建，保证 Python 侧与日志都能落盘
    for (const sub of ['data', 'data/artifacts', 'data/evidence', 'data/logs', 'corpus']) {
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

export { shibanRoot, shibanLegacyRoot, cliPath, PKG as packageMeta };
