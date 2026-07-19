# 🤖 AgentKnowledgeHub — 企业级多Agent知识管理系统

<div align="center">

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2%2B-FF6B6B)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)

**一个企业级的「多Agent协作」知识管理系统**

4个AI Agent分工协作，完成企业知识的全生命周期管理：文档解析 → 知识抽取 → 智能问答 → 增量更新

[快速开始](#-快速开始) · [系统架构](#-系统架构) · [功能演示](#-功能演示) · [API文档](#-api-接口)

</div>

---

## 📌 先看这里（写给小白）

> 如果你是第一次接触多Agent系统，先看这几个问题的解答：

### 什么是 Agent？
Agent（智能体）就是一个"能思考、能执行"的AI程序。它可以：
- 理解你的需求（自然语言）
- 决定需要调用哪些工具（如搜索、写文件、调用API）
- 执行工具，得到结果
- 根据结果继续思考，直到完成任务

### 什么是多Agent？
当一个任务太复杂，交给多个专职Agent协作完成。就像公司里：
- **秘书** 负责整理文件
- **分析师** 负责提炼关键信息
- **顾问** 负责回答问题
- **管理员** 负责持续更新维护

本项目就是用AI实现了这4个角色的分工协作。

### 这个项目能做什么？
你上传一份公司的PDF文档（比如年报、合同、产品手册），然后可以：
- 直接用自然语言提问："张三的职位是什么？" / "Q3营收多少？"
- AI会综合理解文档内容，给出准确答案
- 文档更新后，知识库自动同步，不用重新上传

---

## 📋 目录

- [项目简介](#-项目简介)
- [系统架构](#-系统架构)
- [技术栈](#-技术栈)
- [快速开始](#-快速开始)
- [功能演示](#-功能演示)
- [项目结构](#-项目结构)
- [API接口](#-api-接口)
- [常见问题](#-常见问题-faq)
- [参考资料](#-参考资料)

---

## 🎯 项目简介

**AgentKnowledgeHub** 包含 **4个核心Agent**，通过 [LangGraph](https://langchain-ai.github.io/langgraph/) 有向图编排，实现企业知识的全链路智能处理。

### 4个Agent是什么，分别做什么？

| Agent | 中文名 | 职责 | 类比理解 |
|-------|--------|------|----------|
| `DocParserAgent` | 文档解析Agent | 把PDF/图片/表格等各种格式的文档"读懂"，切割成小段落 | 超强秘书，能看懂任何格式的文件 |
| `KnowledgeExtractAgent` | 知识抽取Agent | 从文本中自动提取人名、公司、关系等结构化信息 | 分析师，把信息整理成知识图谱 |
| `QAAgent` | 问答Agent | 接收用户问题，同时查向量库和知识图谱，生成精准答案 | 专家顾问，综合多源信息回答 |
| `KnowledgeUpdateAgent` | 知识更新Agent | 监听文档变更，只更新变化的部分，保持知识库最新 | 勤快管理员，实时维护知识库 |

### 三大技术亮点

| 亮点 | 说明 | 解决什么问题 |
|------|------|-------------|
| **多模态RAG** | 不只处理文字，还能理解PDF里的图片、表格、流程图 | 传统系统只能处理纯文字 |
| **GraphRAG (知识图谱)** | 用图数据库存储实体关系，支持多跳推理 | 纯向量检索无法处理"关系型"和"多步推理"问题 |
| **CDC增量更新** | 文档变了只更新变化的部分 | 传统方案每次全量重建，1000个文档改5个要30分钟 |

---

## 🏗 系统架构

### 整体架构图

```
┌──────────────────────────────────────────────────────────┐
│                      用户接口层                            │
│              REST API / Web UI / SDK                      │
└──────────────┬───────────────────────────┬───────────────┘
               │                           │
┌──────────────▼───────────────────────────▼───────────────┐
│                 编排引擎 (LangGraph 有向图)                  │
│    ┌─────────────┬──────────────┬──────────────┐         │
│    │ 文档入库流程  │   问答流程    │  增量更新流程  │         │
│    └──────┬──────┴──────┬───────┴──────┬───────┘         │
└───────────│─────────────│──────────────│─────────────────┘
            │             │              │
┌───────────▼──┐ ┌───────▼────┐ ┌───────▼──────┐ ┌────────────┐
│ 文档解析Agent │ │  问答Agent  │ │ 知识更新Agent │ │ 知识抽取Agent│
│              │ │            │ │              │ │            │
│ - PDF解析    │ │ - 意图识别  │ │ - 文件监听    │ │ - NER实体识别│
│ - 图片OCR    │ │ - 向量检索  │ │ - CDC消费    │ │ - 关系抽取  │
│ - 表格提取   │ │ - 图谱检索  │ │ - 差量对比    │ │ - 事件抽取  │
│ - 文档分块   │ │ - 混合排序  │ │ - 增量更新    │ │ - 三元组生成│
└──────┬───────┘ │ - 答案生成  │ │ - 版本管理    │ └─────┬──────┘
       │         └──┬────┬────┘ └──────┬───────┘       │
       │            │    │             │               │
┌──────▼────────────▼────│─────────────▼───────────────▼──┐
│                        存储层                              │
│  ┌─────────────┐     ┌──────────────┐  ┌──────────────┐  │
│  │ ChromaDB /  │     │  Neo4j       │  │   Kafka      │  │
│  │ PGVector    │     │  知识图谱     │  │   CDC队列    │  │
│  │ 向量数据库   │     │              │  │              │  │
│  └─────────────┘     └──────────────┘  └──────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 三条工作流水线（每个数据怎么流转的）

**流水线1：文档入库**（上传文档时触发）

```
用户上传文档
     │
     ▼
文档解析Agent  ←── 支持 PDF / Word / Excel / 图片 / Markdown
  ├── 识别文件类型
  ├── 解析内容（文字 + 图片OCR + 表格提取）
  └── 切割成小块（Chunk）
     │
     ▼
知识抽取Agent
  ├── 命名实体识别（NER）：找出人名、公司名、地名等
  ├── 关系抽取：找出实体之间的关系
  └── 生成三元组：("张三", "就职于", "腾讯")
     │
     ├──────────────────────────────┐
     ▼                              ▼
存入向量数据库                   存入知识图谱
(ChromaDB/PGVector)              (Neo4j)
```

**流水线2：智能问答**（用户提问时触发）

```
用户提问："张三负责什么业务？和李四有什么合作关系？"
     │
     ▼
意图识别 + 查询改写
     │
     ├──────────────────┐
     ▼                  ▼
向量检索              图谱检索
(语义相似度)          (关系路径查询)
     │                  │
     └────────┬─────────┘
              ▼
         混合重排序
         (RRF算法)
              │
              ▼
         LLM生成答案
              │
              ▼
    返回答案 + 来源引用
```

**流水线3：增量更新**（文档修改时触发）

```
文档被修改 / 数据库记录更新
     │
     ▼
CDC事件产生（通过Kafka或文件监听）
     │
     ▼
知识更新Agent
  ├── 差量分析：找出哪些部分变了
  ├── 增量解析：只重新处理变化的内容
  └── 版本管理：记录更新时间和版本号
     │
     ├──────────────┐
     ▼              ▼
更新向量库        更新知识图谱
```

---

## 🛠 技术栈

### Python版（主要实现，功能最完整）

| 组件 | 技术选型 | 为什么选它 |
|------|----------|------------|
| **Agent编排** | [LangGraph](https://langchain-ai.github.io/langgraph/) | 2025年生产级Agent编排标准，有向图 + 状态持久化 |
| **LLM调用** | [LangChain](https://python.langchain.com/) + OpenAI | 最成熟的LLM应用框架，支持几十种LLM |
| **向量数据库** | [ChromaDB](https://www.trychroma.com/) / [PGVector](https://github.com/pgvector/pgvector) | ChromaDB开箱即用；PGVector适合已有PostgreSQL的企业 |
| **知识图谱** | [Neo4j](https://neo4j.com/) | 图数据库的事实标准，Cypher查询语言强大 |
| **消息队列** | [Apache Kafka](https://kafka.apache.org/) | CDC事件流处理的工业标准 |
| **API框架** | [FastAPI](https://fastapi.tiangolo.com/) | 异步高性能，自动生成OpenAPI/Swagger文档 |
| **文档解析** | [Unstructured](https://unstructured.io/) + PyPDF2 + Tesseract | 多模态文档解析全家桶 |
| **容器化** | [Docker Compose](https://docs.docker.com/compose/) | 一键启动所有依赖服务 |


---



## 🚀 快速开始

### 前置条件

在开始之前，你需要安装：

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)（用于一键启动依赖服务）
- 一个 OpenAI API Key（或者用国内兼容接口，见下方FAQ）

### 步骤1：克隆项目

```bash
git clone https://github.com/bcefghj/agent-knowledge-hub.git
cd agent-knowledge-hub
```

### 步骤2：配置环境变量

```bash
cd python
cp .env.example .env
```

用任意编辑器打开 `.env`，填入你的配置：

```env
# OpenAI配置（必填）
OPENAI_API_KEY=sk-你的APIKey
OPENAI_BASE_URL=https://api.openai.com/v1  # 国内用户可替换为兼容接口地址

# 数据库配置（使用Docker默认值即可，不用改）
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
CHROMA_HOST=localhost
CHROMA_PORT=8000
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

### 步骤3：一键启动所有服务

```bash
# 回到项目根目录
cd ..

# 启动所有依赖（Neo4j、ChromaDB、Kafka）
docker-compose up -d
```

等待约1分钟，然后检查服务状态：

```bash
docker-compose ps
```

你应该看到所有服务状态为 `Up`。

### 步骤4：启动Python API服务

```bash
cd python
pip install -r requirements.txt
python -m api.main
```

看到 `Uvicorn running on http://0.0.0.0:8080` 就说明启动成功了！

### 步骤5：验证服务

打开浏览器访问 [http://localhost:8080/docs](http://localhost:8080/docs)，可以看到交互式API文档。

或者用命令行：

```bash
# 健康检查
curl http://localhost:8080/api/health

# 上传一个文档
curl -X POST http://localhost:8080/api/ingest/upload \
  -F "file=@你的文档.pdf"

# 提问
curl -X POST http://localhost:8080/api/qa/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "这个文档讲了什么？"}'
```

---

## 🎬 功能演示

### 功能1：多模态文档解析

文档解析Agent可以自动识别文件类型，调用对应的解析器：

```python
from agents.doc_parser_agent import DocParserAgent

agent = DocParserAgent()

# 解析不同格式的文档
chunks = await agent.parse("年度报告.pdf")    # PDF → 文字 + 图片识别 + 表格提取
chunks = await agent.parse("组织架构.png")    # 图片 → OCR文字识别 + LLM视觉理解
chunks = await agent.parse("财务数据.xlsx")   # Excel → 结构化文本
chunks = await agent.parse("产品文档.md")     # Markdown → 纯文本

# 每个chunk包含：
# chunk.text      - 文本内容
# chunk.metadata  - 来源文件、页码、类型等
# chunk.embedding - 向量表示（自动生成）
```

### 功能2：知识图谱自动构建

知识抽取Agent从文本中提取三元组，自动构建知识图谱：

```python
from agents.knowledge_extract_agent import KnowledgeExtractAgent

extractor = KnowledgeExtractAgent()
result = await extractor.extract(chunks)

# 输出示例：
# entities（实体）:
#   - ("张三", Person, {"职位": "CEO", "年龄": "45"})
#   - ("腾讯", Organization, {"行业": "互联网", "规模": "大型"})
#   - ("微信", Product, {"类型": "社交软件"})
#
# relations（关系）:
#   - ("张三", "就职于", "腾讯")
#   - ("腾讯", "开发了", "微信")
#   - ("张三", "负责", "微信")
```

在Neo4j浏览器（访问 [http://localhost:7474](http://localhost:7474)）中可以可视化查看知识图谱。

### 功能3：GraphRAG 混合检索问答

问答Agent同时从向量库和知识图谱中检索，结合两个来源的信息生成答案：

```python
from agents.qa_agent import QAAgent
from services.vector_store import VectorStore
from services.knowledge_graph import KnowledgeGraphService

# 初始化
vs = VectorStore()
kg = KnowledgeGraphService()
qa = QAAgent(vector_store=vs, knowledge_graph=kg)

# 提问（支持复杂的多跳推理问题）
result = await qa.answer("张三负责的产品，它的主要竞争对手是谁？")

print(result.answer)     # 生成的自然语言答案
print(result.sources)    # 来源引用（哪些文档/哪些知识图谱节点）
print(result.confidence) # 置信度分数

# 内部执行流程：
# 1. 向量检索 → 找到语义相关的文档段落（用余弦相似度）
# 2. 实体链接 → 识别问题中的"张三"是哪个实体
# 3. 图谱检索 → 张三 → 负责 → 微信 → 竞争对手 → QQ / 钉钉
# 4. 混合重排序 → RRF算法
# 5. LLM生成 → 综合所有信息，生成结构化答案
```

### 功能4：CDC 增量更新（只更新变化的部分）

```python
from agents.knowledge_update_agent import KnowledgeUpdateAgent

update_agent = KnowledgeUpdateAgent(...)

# 场景：你修改了一个PDF文件的第3页

# ❌ 传统做法（全量更新）：
#   1. 删除该文档所有向量 （删 1000 条）
#   2. 重新解析整个PDF     （解析 50 页）
#   3. 重新入库所有内容    （写入 1000 条）
#   耗时：~30 分钟

# ✅ CDC做法（增量更新）：
#   1. 检测到第3页内容变化
#   2. 只重新解析第3页
#   3. 只更新第3页相关的向量和知识图谱节点
#   耗时：~30 秒（快60倍！）

await update_agent.process_cdc_event(event={
    "operation": "UPDATE",
    "resource_path": "/docs/年度报告.pdf",
    "changed_pages": [3]
})
```

### 功能5：飞书入库与问答

![alt text](image.png)

![alt text](image-1.png)


---

## 📁 项目结构

```
AgentKnowledgeHub/
│
├── README.md                          ← 你正在看的这个文件
├── docker-compose.yml                 ← 一键启动所有依赖服务
│
├── docs/                              ← 文档目录
│   ├── architecture.md                ← 架构设计详解（每个决策的理由）
│   ├── interview-guide.md             ← 面试八股文 + STAR法则话术
│   ├── resume-template.md             ← 简历写法模板
│   ├── tech-deep-dive.md              ← 核心代码逐行讲解
│   └── project-plan.md               ← 项目规划方案
│
├── python/                            ← Python实现（功能最完整，推荐）
│   ├── agents/                        ← 4个核心Agent
│   │   ├── doc_parser_agent.py        ← 文档解析Agent
│   │   ├── knowledge_extract_agent.py ← 知识抽取Agent
│   │   ├── qa_agent.py                ← 问答Agent
│   │   └── knowledge_update_agent.py  ← 知识更新Agent
│   ├── orchestrator/
│   │   └── graph.py                   ← LangGraph编排引擎（定义3条流水线）
│   ├── services/
│   │   ├── vector_store.py            ← 向量库服务（ChromaDB/PGVector）
│   │   ├── knowledge_graph.py         ← 知识图谱服务（Neo4j）
│   │   ├── graph_rag.py               ← GraphRAG混合检索管道
│   │   ├── cdc_processor.py           ← CDC增量更新处理器
│   │   └── multimodal.py              ← 多模态处理服务
│   ├── api/
│   │   └── main.py                    ← FastAPI入口（REST API）
│   ├── config/
│   │   └── settings.py                ← 配置管理
│   ├── Dockerfile                     ← Python服务容器化
│   ├── requirements.txt               ← Python依赖
│   └── .env.example                   ← 环境变量模板（复制为.env后填写）
│
├── java/                              ← Java实现（Spring生态）
│   ├── src/main/java/com/agenthub/
│   │   ├── agent/                     ← 4个Agent（Spring Bean）
│   │   │   ├── DocParserAgent.java
│   │   │   ├── KnowledgeExtractAgent.java
│   │   │   ├── QAAgent.java
│   │   │   └── KnowledgeUpdateAgent.java
│   │   ├── service/                   ← 服务层
│   │   │   ├── VectorStoreService.java
│   │   │   └── KnowledgeGraphService.java
│   │   ├── controller/                ← REST Controller
│   │   │   └── KnowledgeController.java
│   │   └── model/                     ← 数据模型（POJO）
│   ├── src/main/resources/
│   │   └── application.yml            ← Spring Boot配置
│   └── pom.xml                        ← Maven依赖管理
│
└── golang/                            ← Go实现（高并发）
    ├── agent/                         ← Agent实现
    │   ├── doc_parser.go
    │   ├── knowledge_extract.go
    │   └── qa.go
    ├── service/                       ← 服务层
    │   ├── vector_store.go
    │   └── knowledge_graph.go
    ├── api/
    │   └── server.go                  ← Gin HTTP服务器
    ├── model/
    │   └── types.go                   ← 数据结构定义
    ├── config/
    │   └── config.go                  ← 配置读取
    ├── main.go                        ← 程序入口
    └── go.mod                         ← Go模块依赖
```

---

## 📡 API 接口

启动服务后，访问 [http://localhost:8080/docs](http://localhost:8080/docs) 查看交互式 Swagger API 文档。

### 文档管理接口

| 方法 | 路径 | 说明 | 示例 |
|------|------|------|------|
| `POST` | `/api/ingest/upload` | 上传单个文档 | `curl -F "file=@doc.pdf" http://localhost:8080/api/ingest/upload` |
| `POST` | `/api/ingest/batch` | 批量上传文档 | 上传多个文件，自动并行处理 |

### 智能问答接口

| 方法 | 路径 | 说明 | 请求体示例 |
|------|------|------|-----------|
| `POST` | `/api/qa/ask` | 智能问答 | `{"question": "张三的职位？", "top_k": 5}` |

**响应示例：**
```json
{
  "answer": "根据文档，张三担任腾讯公司CEO职务，负责微信产品线。",
  "confidence": 0.94,
  "sources": [
    {"doc": "年度报告.pdf", "page": 3, "type": "vector"},
    {"entity": "张三", "relation": "就职于", "target": "腾讯", "type": "graph"}
  ]
}
```

### 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/admin/stats` | 查看系统统计（文档数、实体数、关系数） |
| `POST` | `/api/admin/update` | 手动触发全量更新 |
| `GET` | `/api/health` | 健康检查 |

---




## ❓ 常见问题 FAQ

### Q: 我没有OpenAI API Key怎么办？

完全没问题！可以用任何兼容OpenAI接口的LLM服务：

```env
# 国内免费/便宜的选择：
# 1. 通义千问（阿里）
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=你的通义千问APIKey

# 2. 智谱AI（GLM系列）
OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
OPENAI_API_KEY=你的智谱APIKey

# 3. 本地部署（完全免费）
# 先安装 Ollama: https://ollama.ai/
# 然后 ollama pull qwen2
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=qwen2
```

### Q: Docker启动后服务报错？

```bash
# 查看所有服务状态
docker-compose ps

# 查看某个服务的日志
docker-compose logs neo4j
docker-compose logs kafka

# 重启某个服务
docker-compose restart neo4j
```

Neo4j需要的内存比较多，建议给Docker分配至少4GB内存（Docker Desktop → Settings → Resources → Memory）。

### Q: 这个项目可以直接用在公司生产环境吗？

这是一个**架构展示 + 学习项目**，展示了企业级系统的设计思路。如果要用在生产环境，还需要补充：

- 用户认证和权限控制（JWT / OAuth2）
- API限流和熔断（防止滥用）
- 完善的日志和监控（ELK Stack / Prometheus）
- 全面的单元测试和集成测试
- 生产级的数据备份方案


### Q: 如何运行测试？

```bash
# Python
cd python
pytest tests/
```

---

## 🔗 参考资料

### 核心框架文档

- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/) — Agent编排框架
- [LangChain 官方文档](https://python.langchain.com/docs/get_started/introduction) — LLM应用框架
- [Spring AI 官方文档](https://docs.spring.io/spring-ai/reference/) — Java AI框架
- [Neo4j 官方文档](https://neo4j.com/docs/) — 图数据库
- [ChromaDB 官方文档](https://docs.trychroma.com/) — 向量数据库
- [FastAPI 官方文档](https://fastapi.tiangolo.com/) — Python API框架

### 关键论文

- [RAG原始论文 (2020)](https://arxiv.org/abs/2005.11401) — Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks
- [GraphRAG论文 (2024)](https://arxiv.org/abs/2404.16130) — From Local to Global: A Graph RAG Approach to Query-Focused Summarization
- [Microsoft GraphRAG 开源项目](https://github.com/microsoft/graphrag)

### 相关学习资源

- [LangGraph教程（官方）](https://langchain-ai.github.io/langgraph/tutorials/)
- [Neo4j Graph Academy](https://graphacademy.neo4j.com/) — 免费图数据库课程
- [向量数据库选型对比](https://benchmark.vectorview.ai/vectordbs.html)

---


## 📄 License

[MIT License](./LICENSE) — 可以自由使用、修改、分发，只需保留原始版权声明。



