# LLM Survey: Digital Twin Time Travel Research

## 1. Text-to-SQL LLM Benchmarks

### BIRD Leaderboard (Top Models)

| Rank | Model | Accuracy | Type |
|------|-------|----------|------|
| 1 | AskData + GPT-4o | 81.95% | Multi-agent |
| 2 | Agentar-Scale-SQL | 81.67% | Multi-agent |
| 3 | Gemini-SQL (Google) | 77.14% | Single-model |
| 4 | Q-SQL (AWS) | 76.47% | Single-model |
| 5 | Databricks RLVR 32B | 75.68% | Single-model |

Human performance: 92.96%

### Spider 2.0 (Enterprise-hard)

| Model | Success Rate |
|-------|-------------|
| o3-mini | 23.77% |
| Claude 3.7 Sonnet (agentic) | 17.78% |
| GPT-4o (DAIL-SQL) | 10.1% |

### SQL-Specialized Models

- **SQLCoder-70b** (Defog.ai, CodeLlama fine-tune): 93% on Defog benchmark
- **defog/llama-3-sqlcoder-8b**: Production-ready, used in agentic pipelines
- **DAIL-SQL**: 86.6% on Spider 1.0 (GPT-4 backbone)
- **Qwen2.5-Coder**: 82% on Spider (best open-weight)

---

## 2. LLM + Digital Twin 관련 논문

### 직접 관련 논문

| Paper | Year/Venue | LLM Used | Key Finding |
|-------|-----------|----------|-------------|
| **Real2USD** | 2024, arXiv:2510.10778 | Google Gemini | USD의 XML 텍스트를 LLM에 직접 입력 → 공간 추론 + 네비게이션 성공 |
| **Graph-DT-GPT** | 2025, ScienceDirect | Claude Sonnet 3.5, GPT-4o | Claude 100% / GPT-4o 95.5% 정확도 (NL→Graph DT query) |
| **CALM-DT** | ICML 2025 | LLM as DT itself | LLM이 DT 자체로 동작, 자연어로 상태 업데이트 |
| **Agentic NL-to-SQL (spatio-temporal)** | 2025, arXiv:2510.25997 | Mistral Large + SQLCoder-8b | 91.4% 정확도 (ReAct 에이전트 아키텍처) |
| **LLM-DT Survey** | 2025, arXiv:2503.02167 | GPT-4 | 설명-예측-처방 프레임워크 제안 |
| **Scene-LLM** | WACV 2025 | Custom | 3D 공간 특징을 LLM 임베딩에 투영 |
| **3DGraphLLM** | ICCV 2025 | Custom | 3D scene graph + LLM for grounding |
| **InfiniteWorld** | 2024, arXiv:2412.05789 | VLM | Isaac Sim 기반 로봇 인터랙션 |

### NVIDIA USD + AI

- **ChatUSD** (SIGGRAPH 2023): USD Python API 기반 LLM copilot
- **USD Code NIM**: Llama 3 70B fine-tune + RAG + MoE, Python-USD 코드 생성
- **USD Search NIM**: 3D 에셋 시맨틱 검색
- **USD Validate NIM**: RTX 렌더 호환성 검증

---

## 3. 모델 비교

### API Models

| Model | Code (SWE-bench) | Reasoning (GPQA) | Context | SQL |
|-------|-------------------|-------------------|---------|-----|
| Gemini 2.5 Pro | 80.6% | 84% | 1M | BIRD 77.14% (Gemini-SQL) |
| Claude Opus 4.6 | 80.8% | Strong | 200K | DT query 100% (Graph-DT-GPT) |
| Claude Sonnet 3.7 | ~65% | 68% | 200K | Spider 2.0 17.78% |
| GPT-4o | ~50% | Good | 128K | BIRD 81.95% (with agent) |
| o3-mini | Best Spider 2.0 | Excellent | 128K | Spider 2.0 23.77% |

### Open-Source Models

| Model | Code | SQL | Notes |
|-------|------|-----|-------|
| Qwen3-235B-A22B | 69.5% LiveCodeBench | 82% Spider | Best open-weight coding/SQL |
| DeepSeek-V3 | GPT-4o class | Strong | Cost-effective |
| DeepSeek-R1 | Top reasoning | Excellent multi-step | Complex reasoning |
| SQLCoder-70b | — | 93% (Defog) | Best SQL-specific |
| defog/sqlcoder-8b | — | Production-ready | Lightweight, agentic pipeline |
| Qwen2.5-Coder-32B | High | 82% Spider | Balanced size/quality |

---

## 4. 이 프로젝트에 대한 추천

### 추천 아키텍처

```
User NL query
      |
      v
[Router LLM] — intent classification:
  - "state query"   → SQL Agent → Trino → Iceberg
  - "restore"       → MinIO USD download → Isaac Sim Open
  - "structure"     → USD path parser
      |
      v
[SQL Agent]
  Schema linker (RAG over Iceberg DDL)
  → SQL generator LLM
  → Execute via Trino
  → Return result
```

### 추천 모델 조합

**Option A: API 기반 (최고 품질)**
- Router + SQL: **Gemini 2.5 Pro** 또는 **Claude Opus 4.6**
- 장점: 1M context, USD 텍스트 직접 파싱 가능 (Real2USD 검증)

**Option B: Open-source (비용 절감, 자체 호스팅)**
- Router: **Qwen3-235B** 또는 **DeepSeek-V3**
- SQL: **defog/llama-3-sqlcoder-8b** (ReAct agent의 tool로 사용)

**Option C: Hybrid (논문용 추천)**
- Router: Claude/GPT-4o (API)
- SQL: SQLCoder-8b (local, fine-tuned)
- 비교 실험: API vs Open-source 정확도/속도/비용 비교

### Trino 방언 대응

Trino SQL 특수 문법 (`FOR VERSION AS OF`, `$partitions` 등)은 few-shot 예시 또는 시스템 프롬프트로 주입. 모델 선택보다 **Iceberg 스키마 RAG**가 더 중요.

### USD 파싱

Real2USD 논문에서 검증: USD의 텍스트 포맷을 LLM에 직접 입력 가능. 별도 USD 파서 불필요 — prim 계층 구조를 텍스트로 제공하면 LLM이 추론 가능.

---

## 5. 논문 인용 추천

직접 인용할 핵심 논문:
1. **CALM-DT** (ICML 2025) — LLM as Digital Twin
2. **Real2USD** (arXiv:2510.10778) — LLM + OpenUSD
3. **Graph-DT-GPT** (ScienceDirect 2025) — NL → DT query
4. **Agentic spatio-temporal SQL** (arXiv:2510.25997) — NL → SQL agent
5. **DAIL-SQL** (VLDB) — Text-to-SQL pipeline
6. **NVIDIA USD Code NIM** — Industry USD + AI

---

## Sources

- [BIRD-bench Leaderboard](https://bird-bench.github.io/)
- [Spider 2.0](https://spider2-sql.github.io/)
- [Defog SQLCoder-70b](https://defog.ai/blog/open-sourcing-sqlcoder-70b)
- [Real2USD (arXiv:2510.10778)](https://arxiv.org/html/2510.10778v1)
- [Graph-DT-GPT (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S0926580526000324)
- [CALM-DT (ICML 2025)](https://icml.cc/virtual/2025/poster/44291)
- [Agentic SQL (arXiv:2510.25997)](https://arxiv.org/html/2510.25997)
- [LLM-DT Survey (arXiv:2503.02167)](https://arxiv.org/html/2503.02167v1)
- [Scene-LLM (arXiv:2403.11401)](https://arxiv.org/abs/2403.11401)
- [3DGraphLLM (ICCV 2025)](https://github.com/CognitiveAISystems/3DGraphLLM)
- [InfiniteWorld (arXiv:2412.05789)](https://arxiv.org/html/2412.05789v1)
- [NVIDIA USD Code NIM](https://docs.omniverse.nvidia.com/services/latest/services/usd-code/architecture.html)
- [Lambda LLM Benchmarks](https://lambda.ai/llm-benchmarks-leaderboard)
