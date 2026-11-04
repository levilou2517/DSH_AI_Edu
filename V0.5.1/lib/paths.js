/**
 * 包路径解析——被 index.js 与可能的预加载入口共用。
 *
 * 为什么要单独一个文件：skill-filesystem 读取 DSH_BUNDLED_SKILL_DIR 的时机
 * 可能早于任何插件 apply()。这个模块在**被 import 的那一刻**就把环境变量设好，
 * 因此谁先 import 它，谁就能保证后续读到正确的值。
 *
 * 路径来源是 import.meta.url——它永远指向本文件，不受 baseUrl 影响，
 * 因此跨机器、跨系统（Windows/Linux/macOS）都成立。
 */
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

/** 本包根目录的绝对路径。 */
export const PACKAGE_DIR = resolve(join(here, '..'));

/** 随包技能目录的绝对路径。 */
export const SKILLS_DIR = join(PACKAGE_DIR, 'skills');

/**
 * 把包路径写进进程环境变量（幂等）。
 *  - SHIBAN_PKG_DIR        本包根目录，供 CLI/脚本定位
 *  - DSH_BUNDLED_SKILL_DIR skill-filesystem 原生读取的相对技能根
 */
export function installPathEnv() {
  process.env.SHIBAN_PKG_DIR = PACKAGE_DIR;
  process.env.DSH_BUNDLED_SKILL_DIR = SKILLS_DIR;
  return { PACKAGE_DIR, SKILLS_DIR };
}

// 模块被加载即生效——不依赖任何插件生命周期
installPathEnv();
