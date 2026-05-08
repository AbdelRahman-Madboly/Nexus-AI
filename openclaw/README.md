# OpenClaw Setup Guide

See [docs/openclaw_setup.md](../docs/openclaw_setup.md) for full instructions.

## Quick Start
```bash
npm install -g openclaw
cp openclaw/.env.example openclaw/.env
# Add your Telegram bot token
openclaw start
```

Send a Telegram message to your bot: "What does Nexus do?"
You should receive a RAG-grounded answer within 30 seconds.
