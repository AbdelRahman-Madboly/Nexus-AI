# Nexus-AI — API Contract

## Endpoints

### Health
GET /api/health

### RAG
POST /api/rag/ingest
POST /api/rag/query

### Agents
POST /api/agents/lead/classify
POST /api/agents/lead/followup
GET /api/agents/pipeline/report
GET /api/agents/trace/{run_id}

### MCP
See FastMCP auto-generated docs at /api/mcp/docs
