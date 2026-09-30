#!/bin/sh
# ollama CPU-only 启动脚本:模型已在镜像内(COPY 进来),直接启动
# 提供 bge-m3(embedding)+ minicpm-v(vision OCR)两个国产模型
set -e
export PATH=/usr/bin:$PATH

# 必须监听 0.0.0.0,否则只监听 127.0.0.1,dbgpt 容器(同 compose 网络)连不上
export OLLAMA_HOST="${OLLAMA_HOST:-0.0.0.0:11434}"

# 检查模型是否就绪(模型在镜像内,内网不联网,缺失只警告不 pull)
for m in bge-m3 minicpm-v; do
  if ollama list 2>/dev/null | grep -q "^$m"; then
    echo "[ollama-init] $m 已就绪"
  else
    echo "[ollama-init] 警告:未找到 $m(模型应在构建期烤进镜像)"
  fi
done

echo "[ollama-init] 启动 ollama serve"
exec ollama serve
