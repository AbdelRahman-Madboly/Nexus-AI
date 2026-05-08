# File Tree: Nexus-AI

**Root Path:** `c:\Dan_WS\Nexus-AI`

```
├── api
│   ├── agents
│   │   ├── __init__.py
│   │   ├── followup_agent.py
│   │   ├── graph.py
│   │   ├── lead_agent.py
│   │   └── reporter_agent.py
│   ├── llm
│   │   ├── __init__.py
│   │   ├── claude_client.py
│   │   ├── gemini_client.py
│   │   ├── llm_router.py
│   │   ├── ollama_client.py
│   │   └── openai_client.py
│   ├── mcp
│   │   ├── __init__.py
│   │   └── server.py
│   ├── models
│   │   ├── __init__.py
│   │   └── crm_models.py
│   ├── rag
│   │   ├── __init__.py
│   │   ├── ingestor.py
│   │   └── retriever.py
│   ├── routers
│   │   ├── __init__.py
│   │   ├── agent_router.py
│   │   ├── mcp_router.py
│   │   └── rag_router.py
│   ├── Dockerfile
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   └── requirements.txt
├── dashboard
│   ├── public
│   │   └── favicon.ico
│   ├── src
│   │   ├── api
│   │   │   └── nexusApi.ts
│   │   ├── pages
│   │   │   ├── AgentTracer.tsx
│   │   │   ├── Pipeline.tsx
│   │   │   └── RagChat.tsx
│   │   └── App.tsx
│   ├── Dockerfile
│   ├── package.json
│   └── vite.config.ts
├── docs
│   ├── api_contract.md
│   ├── architecture.md
│   ├── demo_script.md
│   └── openclaw_setup.md
├── n8n
│   └── workflows
│       ├── alert-escalation.json
│       ├── followup-scheduler.json
│       ├── lead-intake.json
│       └── pipeline-digest.json
├── openclaw
│   ├── skills
│   │   ├── nexus-leads
│   │   │   └── SKILL.md
│   │   ├── nexus-pipeline
│   │   │   └── SKILL.md
│   │   └── nexus-rag
│   │       └── SKILL.md
│   ├── .env.example
│   ├── MEMORY.md
│   ├── README.md
│   └── SOUL.md
├── tests
│   ├── __init__.py
│   ├── test_agents.py
│   ├── test_database.py
│   ├── test_openclaw_skills.py
│   └── test_rag.py
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
└── docker-compose.yml
```

---