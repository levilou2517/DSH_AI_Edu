#!/usr/bin/env bash
# 打包为可分发的 tgz（含自带 Python 闭包）
set -euo pipefail
cd "$(dirname "$0")/.."
VER="$(cat VERSION)"
OUT="dist/shiban-${VER}.tgz"
mkdir -p dist
tar czf "$OUT" --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
  package.json cordis.patch.yml VERSION lib skills framework contracts \
  docs presets vendor scripts tools CHANGELOG.md
sha256sum "$OUT" | tee "${OUT}.sha256"
echo "大小: $(du -h "$OUT" | cut -f1)  文件数: $(tar tzf "$OUT" | wc -l)"
