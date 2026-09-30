# dbgpt 镜像:基于官方 eosphorosai/dbgpt-openai,叠加可配置 traffic_guard
# 配置 toml 原样保留(它全用环境变量,无需改文件)
# 通过环境变量指向:内网 LLM(OpenAI 兼容)+ ollama embedding(bge-m3)
FROM eosphorosai/dbgpt-openai:latest

# traffic_guard 改造版:可配置开关(TRAFFIC_GUARD_ENABLED),覆盖原 .pth 自动加载的那个
COPY traffic_guard.py /opt/.uv.venv/lib/python3.11/site-packages/traffic_guard.py

# 持久化挂载点:pilot 整个目录(data/chromadb 向量库 + meta_data/dbgpt.db 元数据)
VOLUME ["/app/pilot", "/data/db_knowledge"]

# 显式指定 CMD:用 proxy-openai 配置(全环境变量,适配内网任意 OpenAI 兼容 LLM)
CMD ["dbgpt", "start", "webserver", "--config", "/app/configs/dbgpt-proxy-openai.toml"]
