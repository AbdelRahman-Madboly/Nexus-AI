# Nexus-AI — 10-Minute CEO Demo Script

## Setup (before demo)
```bash
docker-compose up -d
```
Wait 60 seconds for all services to start.

## Step 1 — RAG (2 min)
Open http://localhost:3000 → RAG Chat
Type: "What is Revenyu and what is its AI layer built on?"
Show: Answer appears with citation to Projecx website content.

## Step 2 — Lead Agent (2 min)
POST http://localhost:8000/api/agents/lead/classify
Body: {"company": "Acme Corp", "contact": "CEO", "budget": "$50k", "timeline": "Q3"}
Show: Lead classified as hot_lead, trace visible in Agent Tracer page.

## Step 3 — OpenClaw (2 min)
On Telegram: "Classify this lead: John Smith, CTO at TechCorp, interested in AI CRM, budget $30k"
Show: Response arrives via Telegram: "Lead classified as hot_lead (score: 82)"

## Step 4 — MCP (2 min)
Open Claude Desktop
Type: "How many leads are in hot_lead stage?"
Show: Claude calls nexus_query_leads, returns live number from SQLite.

## Step 5 — n8n (1 min)
Open n8n at localhost:5678
Show: 4 workflows ready to activate. Trigger Lead Intake webhook.
Show: Slack message + Telegram notification appear automatically.
