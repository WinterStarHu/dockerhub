# dockerhub — DB-GPT 离线部署

离线部署 DB-GPT(数据库专家 agent):`docker load` + `docker compose up`,无需联网。

## 架构

```
┌─ 目标机器(离线)─────────────────────────────────┐
│  ┌──────────────┐      ┌──────────────────┐      │
│  │ dbgpt 容器    │─────→│ ollama 容器        │      │
│  │ :5670         │      │ (bge-m3+minicpm-v) │      │
│  │ 程序+配置      │      │ :11434(内部网络)   │      │
│  └──────┬───────┘      └──────────────────┘      │
│         │ 挂载                                     │
│  ┌──────▼─────────────────────────────────────┐   │
│  │ /app/pilot      (ChromaDB 向量库 + 元数据)  │   │
│  │ /data/db_knowledge (知识库,git clone 进来)  │   │
│  └────────────────────────────────────────────┘   │
│         ↑ LLM 调用(出容器,指向自建 LLM)          │
│  ┌──────┴─────────────────────────────────────┐   │
│  │ 自建 LLM(OpenAI 兼容接口)                   │   │
│  └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

## 两个镜像(独立更新,适合离线环境慢更新)

| 镜像 / 文件 | 内容 | 大小(tar) |
|---|---|---|
| `dbgpt-intranet:latest` | DB-GPT 程序 + 可配置 traffic_guard | ~570MB |
| `dbgpt-ollama-cpu:intranet` | Ollama(CPU-only,ubuntu + 二进制 + CPU 库,**不含模型**) | ~200MB |
| `ollama-models.tar` | bge-m3 + minicpm-v 模型文件(部署时解压到宿主机,bind-mount 进容器) | ~6.7GB |

> ollama 镜像是 **CPU-only** 小镜像(不含 CUDA、不含模型),只含二进制 + CPU 推理库。
> 模型(bge-m3 + minicpm-v)单独打成 `ollama-models.tar`,部署时解压到宿主机 `/data/ollama-models`,compose bind-mount 进容器的 `/root/.ollama`。
> **换/加模型只需替换宿主机文件 + `docker compose restart ollama`,不用重建镜像。**
> 构建脚本会从本机现有 ollama 容器提取二进制/库,并单独导出模型文件(均不进 git 仓库)。

## 外网机器(hdx):构建 + 导出

```bash
git clone git@github.com:WinterStarHu/dockerhub.git
cd dockerhub
bash build-and-export.sh
# 产出:dbgpt-intranet.tar + dbgpt-ollama-cpu.tar(小镜像)+ ollama-models.tar(模型文件)
```

> `build-and-export.sh` 前提:本机已有运行中的 ollama 容器(官方 `ollama/ollama` 镜像,含 bge-m3 + minicpm-v 模型),脚本会从中提取二进制/库,并单独导出模型文件。
> 若没有,先:`docker run -d --name ollama -p 11434:11434 ollama/ollama && docker exec ollama ollama pull bge-m3 && docker exec ollama ollama pull minicpm-v`

## 离线机器:部署

### 1. 导入镜像 + 模型
```bash
docker load -i dbgpt-intranet.tar
docker load -i dbgpt-ollama-cpu.tar
# 模型解压到宿主机(compose 已配置 bind-mount /data/ollama-models:/root/.ollama)
mkdir -p /data/ollama-models && tar -xf ollama-models.tar -C /data/ollama-models --strip-components=1
```

### 2. 准备知识库数据卷(离线 git clone,慢但能拉)
```bash
mkdir -p /data/db_knowledge && cd /data/db_knowledge
# 逐个 clone 需要的分支(浅克隆,只拉一个分支,不全量 fetch)
git clone --depth 1 -b oracle-19c git@github.com:WinterStarHu/db_knowledge.git oracle-19c
git clone --depth 1 -b postgresql-18 git@github.com:WinterStarHu/db_knowledge.git postgresql-18
# ... 更多分支见 db_knowledge 仓库的 INDEX.md
```

### 3. 配置环境变量
```bash
cp .env.example .env
vi .env   # 填自建 LLM 的 API base / 模型名 / key
```

### 4. 准备 DB-GPT 源码 + 可配置补丁(compose bind-mount,必做)
```bash
# clone 你的 DB-GPT fork(compose 挂载 /data/dbgpt-source/packages 进容器,不 clone 会空挂载导致启动失败)
git clone -b main git@github.com:WinterStarHu/DB-GPT.git /data/dbgpt-source

# 可配置补丁目录(compose 挂载这两个文件进 site-packages)
mkdir -p /data/dbgpt-patches
cp dbgpt/traffic_guard.py /data/dbgpt-patches/
cp dbgpt/vision_ocr.py    /data/dbgpt-patches/
```
> `traffic_guard.py`(流量拦截)、`vision_ocr.py`(OCR 识图)都是 bind-mount,改完 `docker compose restart dbgpt` 生效,不重建镜像。
> 详情见下文"DB-GPT 源码 git 管理"和"本地多模态"章节。

### 5. 启动
```bash
docker compose up -d
```

### 6. 访问 + 建知识库
浏览器打开 `http://<目标机器IP>:5670`
- 新建知识库 → 文档来源选 **File** → 路径填 `/data/db_knowledge/<分支名>`
- (例:`/data/db_knowledge/oracle-19c`)
- 同步 → 等待向量化完成(首次建知识库的 embedding 较慢,CPU 跑 bge-m3)

## DB-GPT 源码 git 管理 + 动态更新(不重建镜像)

容器里的 DB-GPT 源码(`/app/packages/`)可通过 **bind-mount 你 fork 的 git 仓库** 来管理,改代码后 `restart` 即生效,**永远不用重建镜像/容器**。

### 首次准备(离线机器)
```bash
# clone 你的 fork 到宿主机(慢但能拉)
git clone -b main git@github.com:WinterStarHu/DB-GPT.git /data/dbgpt-source
# (fork 是从 eosphoros-ai/DB-GPT fork 的,packages/ 布局与容器一致)
```
> `/data/dbgpt-source/packages` 挂载进容器 `/app/packages`,覆盖镜像内置源码。
> 容器内 editable 安装(`_editable_impl_dbgpt*.pth`)指向 `/app/packages/*/src/`,挂载后以你 fork 的源码为准。

### 改代码 + 同步流程
```bash
# (在任意能 push 的机器上)改代码 → push 到你的 fork
#   git commit + git push origin main

# 离线机器:拉取改动
cd /data/dbgpt-source && git pull

# 重启 dbgpt 容器(不重建,只重启)
docker compose restart dbgpt
```
**改代码 → push → 离线机器 pull → restart**,镜像/容器都不重建。

### 版本对齐说明
- 容器预装 DB-GPT 0.8.2(site-packages dist-info)
- 你的 fork main 比 v0.8.2 领先若干 commit(完全包含 v0.8.2,behind_by=0)
- 挂载 main 进去 = 向前更新,兼容(除非新增第三方依赖,那需在容器内补装)
- 想严格对齐:在 fork 上建 `v0.8.2-patches` 分支基于 `v0.8.2` tag,挂载该分支

### traffic_guard 也是动态的
`/data/dbgpt-patches/traffic_guard.py` 挂载进容器,改完 `docker compose restart dbgpt` 生效,不碰镜像。

### 何时才需要重建镜像
只有以下情况才重建(低频):
- DB-GPT 新增第三方依赖(需在镜像里 `pip install`)
- 想把改动永久固化进镜像 base(不再依赖挂载)
- DB-GPT 大版本升级(dist-info 版本变了需重装)

日常改代码 = git pull + restart,不碰镜像。

## 知识库刷新(不需要重建镜像/容器)

```bash
# 更新某分支内容
cd /data/db_knowledge/oracle-19c && git pull
# 去 DB-GPT 后台 → 该知识库 → 点"重新同步"(重新向量化)
# 加新分支:
cd /data/db_knowledge && git clone --depth 1 -b <新分支> git@github.com:WinterStarHu/db_knowledge.git <新分支>
# 然后 DB-GPT 新建知识库指向新目录
```

**镜像/容器都不动**,只动数据卷目录 + DB-GPT 后台同步。

## 镜像本身更新(低频)
DB-GPT 程序或 ollama 模型更新时,才需要:
1. 外网机器重跑 `build-and-export.sh`
2. 拷新 tar 到离线机器
3. `docker load -i xxx.tar`
4. `docker compose down && docker compose up -d`

## 环境变量说明

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_BASE` | 自建 LLM 的 OpenAI 兼容 API base | (必填) |
| `LLM_MODEL_NAME` | 自建 LLM 模型名 | (必填) |
| `LLM_API_KEY` | 自建 LLM API key | dbgpt |
| `TRAFFIC_GUARD_ENABLED` | traffic_guard 开关 | false(全放行) |
| `TRAFFIC_GUARD_ALLOW_DOMAINS` | 额外放行 POST 的域名(逗号分隔) | (空) |
| `EMBEDDING_MODEL_NAME` | embedding 模型名 | bge-m3 |
| `EMBEDDING_MODEL_API_URL` | embedding 服务地址 | http://ollama:11434 |
| `VISION_OCR_ENABLED` | 本地多模态开关(见下) | false |
| `VISION_OCR_MODEL` | ollama 视觉模型名 | minicpm-v |
| `VISION_OCR_API_URL` | ollama 服务地址(OCR 用) | http://ollama:11434 |

## 本地多模态(方式2):MiniCPM-V 识图 → 自建 LLM 答题

自建 LLM 是文字模型(看不见图)。多模态走**两阶段**:
1. 用户在聊天里上传图片(报错截图/表结构/文档截图等)
2. 本地 **MiniCPM-V**(国产,面壁智能,CPU 经 ollama 跑)把图 **OCR 成文字**
3. 文字喂给**自建 LLM**(不改)答题

### 为什么这样
- 自建 LLM 推理强但看不见图;MiniCPM-V(CPU)能识图但推理弱。分工:MiniCPM-V 只做"图→文字",自建 LLM 做"理解+答题"。
- 视觉阶段**直连 ollama `/api/generate`**(DB-GPT 自带的 ollama proxy 不传图),由 fork 的 `base_chat.py` 挂钩 + bind-mount 的 `vision_ocr.py` 实现。
- 全程国产模型(bge-m3 智源 + MiniCPM-V 面壁),ollama 为 CPU 推理引擎。

### 体积/性能
- minicpm-v(Q4,8B)约 5–6GB,加上 bge-m3(~1.2GB)模型文件共 ~6.7GB,单独打成 `ollama-models.tar`。ollama 镜像本身只有 ~200MB。拷一次到离线机器,长期用。
- 纯 CPU 跑 8B VLM:每张图 OCR 几秒到几十秒,适合偶发 OCR,不适合高并发实时。
- `VISION_OCR_ENABLED` 默认 `false`,平时只跑文字问答;需要识图时再开。

### 开启多模态
1. 部署时模型已解压到 `/data/ollama-models`(含 minicpm-v),compose bind-mount 进 ollama 容器
2. `.env` 设 `VISION_OCR_ENABLED=true`
3. `docker compose up -d` → 聊天里传图测试

### 模型管理(换/加模型不用重建镜像)
- 模型用 bind-mount(`/data/ollama-models:/root/.ollama`),**换/加模型只需替换宿主机文件 + `docker compose restart ollama`**,不用重建镜像、不用重启容器重建。
- 加新模型:有网机器 `ollama pull <model>` → `docker cp ollama:/root/.ollama/. /data/ollama-models/` → 离线机器 `docker compose restart ollama`。
- `build-and-export.sh` 会把源容器的所有模型整体导出成 `ollama-models.tar`(纯文件包,非镜像层)。

### 关闭/降级
- `VISION_OCR_ENABLED=false`(默认):`vision_ocr.py` 不介入,纯文字问答,不多耗资源。
- OCR 失败(模块缺失/ollama 不可用/超时):该图降级为 `[图片识别失败]` 文字,不阻塞聊天,不崩。
- 改 `vision_ocr.py` 或 fork 的 `base_chat.py` → `git pull` + `docker compose restart dbgpt` 生效,不重建镜像。

## traffic_guard
- `TRAFFIC_GUARD_ENABLED=false`(默认):全放行,离线环境无感
- `=true`:启用拦截
  - GET/HEAD/OPTIONS:放行
  - POST/PUT/DELETE:拦截,例外 → docker 内部地址(localhost/127.x/172.x/10.x/192.168.x)+ 白名单域名
  - 用 `TRAFFIC_GUARD_ALLOW_DOMAINS` 加白名单(如自建 LLM 域名)

## 目录结构
```
dockerhub/
├── README.md
├── docker-compose.yml          # 离线部署用
├── .env.example
├── build-and-export.sh         # 外网构建+导出脚本(自动从容器提取 ollama 文件)
├── dbgpt/
│   ├── Dockerfile              # FROM eosphorosai/dbgpt-openai + 可配置 traffic_guard
│   └── traffic_guard.py        # 可配置版(TRAFFIC_GUARD_ENABLED 开关)
└── ollama/
    ├── Dockerfile              # FROM ubuntu:24.04 + ollama 二进制 + CPU 库(不含模型)
    └── ollama-init.sh          # 启动脚本(检查 bge-m3 + minicpm-v,缺失只警告)
    # (构建时由 build-and-export.sh 提取:ollama-bin, ollama-lib/;模型单独导出 ollama-models.tar)
```
