# OpenClaw Setup Guide

## Prerequisites
- Node.js 24+
- A Telegram bot token (from @BotFather)
- Ollama running locally (or API key for cloud LLM)

## Installation
```bash
npm install -g openclaw
```

## Configuration
1. Copy `openclaw/.env.example` to `openclaw/.env`
2. Add your `TELEGRAM_BOT_TOKEN`
3. Set `OPENCLAW_NEXUS_API_URL=http://localhost:8000`

## Starting the Gateway
```bash
cd openclaw
openclaw start
```

## Installing Nexus Skills
```bash
openclaw install ./skills/nexus-rag
openclaw install ./skills/nexus-leads
openclaw install ./skills/nexus-pipeline
```

## Testing
Send to your Telegram bot: `What does Nexus do?`
Expected: RAG-grounded answer within 30 seconds.
