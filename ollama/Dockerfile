# ollama CPU-only 镜像:基于 ubuntu:24.04 + ollama 二进制 + CPU 推理库
# 不含模型(模型用 bind-mount 挂载)、不含 CUDA,体积小(约 200MB),适合内网 CPU 机器
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ollama 运行需要的最小依赖(ca-certificates 用于 HTTPS;apt 源签名问题时不阻塞构建)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/* \
    || (echo "apt-get 失败(可能是内网/签名问题),跳过 ca-certificates" && true)

# ollama 主二进制(版本 0.34.4)
COPY ollama-bin /usr/bin/ollama
RUN chmod +x /usr/bin/ollama

# ollama CPU 推理库(llama-server + libggml/libllama 等,从官方镜像拷出,排除 CUDA/vulkan)
COPY ollama-lib/ /usr/lib/ollama/
# 注册 ollama 库路径,否则 llama-server 找不到 libllama-common.so.0
RUN echo "/usr/lib/ollama" > /etc/ld.so.conf.d/ollama.conf && ldconfig
ENV LD_LIBRARY_PATH=/usr/lib/ollama

# bge-m3 + minicpm-v 模型不进镜像——用 bind-mount 挂载(compose 里 /data/ollama-models:/root/.ollama)。
# 这样换/加模型只需替换宿主机文件 + restart,不用重建镜像、不用 docker commit。
# 模型文件由 build-and-export.sh 单独导出成 ollama-models.tar,内网解压到 /data/ollama-models。

# 启动脚本
COPY ollama-init.sh /ollama-init.sh
RUN chmod +x /ollama-init.sh

# 注:不声明 VOLUME ["/root/.ollama"]——模型由 compose bind-mount 提供(见 docker-compose.yml)。
# 挂载点 /root/.ollama 在容器内由宿主机 /data/ollama-models 提供。

ENTRYPOINT ["/bin/sh", "/ollama-init.sh"]
