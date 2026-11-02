#!/usr/bin/env bash
# 构建发布包：tgz（npm/本地安装）+ zip（解压后按目录安装）
set -euo pipefail
cd "$(dirname "$0")/.."

VER="$(python3 -c 'import json;print(json.load(open("package.json"))["version"])')"
NAME="shiban-${VER}"
mkdir -p dist
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# 只发运行必需的内容
INCLUDE=(package.json cordis.patch.yml VERSION lib skills framework contracts docs presets vendor README.md CHANGELOG.md 使用说明.txt)

echo "→ 打包 $NAME.tgz"
tar czf "dist/${NAME}.tgz" --exclude='__pycache__' --exclude='*.pyc' "${INCLUDE[@]}"

echo "→ 打包 $NAME.zip"
rm -rf "dist/${NAME}"
mkdir -p "dist/${NAME}"
for item in "${INCLUDE[@]}"; do
  cp -a "$item" "dist/${NAME}/"
done
find "dist/${NAME}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
(cd dist && zip -qr "${NAME}.zip" "${NAME}" -x '*__pycache__*' '*.pyc')
rm -rf "dist/${NAME}"

echo
(cd dist && sha256sum "${NAME}.tgz" "${NAME}.zip") | tee "dist/${NAME}.sha256"
echo
ls -lh dist/ | tail -5
