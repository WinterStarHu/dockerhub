#!/bin/bash
# build-and-export.sh — 外网机器(hdx)构建两镜像 + 导出 tar
# 前提:本机已有运行中的 ollama 容器(含 bge-m3 模型),用于提取二进制/库/模型
# 用法: bash build-and-export.sh
set -e
cd "$(dirname "$0")"

# 找到现有的 ollama 容器(用于提取 ollama 二进制、CPU 推理库、bge-m3 模型)
OLLAMA_CTR=$(docker ps --filter "ancestor=ollama/ollama" --format "{{.Names}}" | head -1)
if [ -z "$OLLAMA_CTR" ]; then
  OLLAMA_CTR=$(docker ps --format "{{.Names}}" | grep -i ollama | head -1)
fi
if [ -z "$OLLAMA_CTR" ]; then
  echo "错误:找不到运行中的 ollama 容器(需要它来提取 ollama 二进制/库/bge-m3 模型)"
  echo "请先启动一个官方 ollama 容器并 pull bge-m3:"
  echo "  docker run -d --name ollama -p 11434:11434 ollama/ollama"
  echo "  docker exec ollama ollama pull bge-m3"
  exit 1
fi
echo "使用 ollama 容器: $OLLAMA_CTR (提取二进制/库/模型)"

# 确保源容器里有 bge-m3 和 minicpm-v 两个模型(外网机器,可联网 pull)
echo "===== 确保源容器有 bge-m3 + minicpm-v 模型 ====="
for m in bge-m3 minicpm-v; do
  if ! docker exec "$OLLAMA_CTR" ollama list 2>/dev/null | grep -q "^$m"; then
    echo "  源容器缺 $m,正在 pull(外网)... "
    docker exec -d "$OLLAMA_CTR" ollama serve 2>/dev/null || true
    sleep 3
    docker exec "$OLLAMA_CTR" ollama pull "$m"
  else
    echo "  $m 已就绪"
  fi
done

# 准备 ollama 构建上下文(从现有容器提取,不进 git 仓库)
echo "===== 准备 ollama 构建上下文 ====="
mkdir -p ollama/ollama-lib
# ollama 主二进制
docker cp "$OLLAMA_CTR:/usr/bin/ollama" ollama/ollama-bin
chmod +x ollama/ollama-bin
# ollama CPU 推理库(排除 CUDA/vulkan/mlx/include)
# 用 tar -chf -(跟随符号链接 -h)从源容器导出 /usr/lib/ollama 整个目录,
# 确保符号链接 .so -> .so.0 -> .so.0.4.1 的真实文件都拷出来
# (docker cp 单文件不跟随符号链接,会漏 .so.0 真实文件 → llama-server 找不到 libllama-common.so.0)
# 注意:先 cd /usr/lib 再 tar,exclude 用 basename(GNU tar 匹配存储路径的 path component)
rm -rf ollama/ollama-lib-tmp && mkdir -p ollama/ollama-lib-tmp
docker exec -w /usr/lib "$OLLAMA_CTR" tar -chf - \
  --exclude=cuda_v* --exclude=vulkan* --exclude=mlx* --exclude=include* \
  ollama 2>/dev/null | tar -xf - -C ollama/ollama-lib-tmp
# 解压后在 ollama/ollama-lib-tmp/ollama/,挪到 ollama/ollama-lib/
rm -rf ollama/ollama-lib && mkdir -p ollama/ollama-lib
cp -a ollama/ollama-lib-tmp/ollama/. ollama/ollama-lib/ 2>/dev/null || true
rm -rf ollama/ollama-lib-tmp
# bge-m3 + minicpm-v 模型不进构建上下文(改用 docker cp 灌进容器后 commit,见下)
# 此处仅确认源容器有两个模型
echo "  源容器模型: $(docker exec "$OLLAMA_CTR" ollama list 2>/dev/null | grep -E 'bge-m3|minicpm-v' | tr '\n' ' ')"
for m in bge-m3 minicpm-v; do
  if ! docker exec "$OLLAMA_CTR" ollama list 2>/dev/null | grep -q "^$m"; then
    echo "错误:源容器缺 $m,无法打包"; exit 1
  fi
done

echo "===== 1. 构建 dbgpt 镜像(基于 eosphorosai/dbgpt-openai,叠加可配置 traffic_guard)====="
DOCKER_BUILDKIT=0 docker build -t dbgpt-intranet:latest -f dbgpt/Dockerfile dbgpt/

echo "===== 2. 构建 ollama CPU 镜像(不含模型,小镜像)====="
# 镜像只含二进制 + CPU 库,不含模型。模型用 bind-mount 挂载(见 docker-compose.yml),
# 换/加模型只需替换宿主机 /data/ollama-models 里的文件 + restart,不用重建镜像。
DOCKER_BUILDKIT=0 docker build -t dbgpt-ollama-cpu:intranet -f ollama/Dockerfile ollama/

echo "===== 2b. 导出模型文件(bge-m3 + minicpm-v,纯文件 tar)====="
# 模型不烤进镜像,改成单独 tar 一份(内网解压到 /data/ollama-models,compose bind-mount 进 /root/.ollama)
# 这样换/加模型不用重建镜像、不用 docker commit,只换文件 + restart。
docker exec "$OLLAMA_CTR" tar -C /root -cf - .ollama -o /tmp/ollama-models-export.tar 2>/dev/null \
  || docker exec "$OLLAMA_CTR" tar -C /root -cf - .ollama > /tmp/ollama-models-export.tar
docker cp "$OLLAMA_CTR:/tmp/ollama-models-export.tar" ollama-models.tar
docker exec "$OLLAMA_CTR" rm -f /tmp/ollama-models-export.tar 2>/dev/null || true

echo "===== 3. 导出 tar(内网用)====="
docker save dbgpt-intranet:latest -o dbgpt-intranet.tar
docker save dbgpt-ollama-cpu:intranet -o dbgpt-ollama-cpu.tar

echo "===== 导出完成 ====="
ls -lh dbgpt-intranet.tar dbgpt-ollama-cpu.tar ollama-models.tar
echo ""
echo "拷贝以下文件到内网机器:"
echo "  - dbgpt-intranet.tar          (dbgpt 镜像)"
echo "  - dbgpt-ollama-cpu.tar        (ollama 小镜像,含二进制+库,不含模型)"
echo "  - ollama-models.tar           (bge-m3 + minicpm-v 模型文件)"
echo "  - docker-compose.yml"
echo "  - .env.example"
echo ""
echo "内网部署步骤:"
echo "  docker load -i dbgpt-intranet.tar"
echo "  docker load -i dbgpt-ollama-cpu.tar"
echo "  mkdir -p /data/ollama-models && tar -xf ollama-models.tar -C /data/ollama-models --strip-components=1"
echo "  # compose 已配置 /data/ollama-models 挂载进 ollama 容器的 /root/.ollama"
echo "  docker compose up -d"

# 清理构建上下文的大文件(它们是从容器提取的,不进 git)
rm -rf ollama/ollama-lib ollama/ollama-bin
echo "(已清理构建上下文的大文件)"
