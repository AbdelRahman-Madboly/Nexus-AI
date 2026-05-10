# Nexus OpenClaw Gateway

The conversational layer for Nexus-AI. Connects Telegram, WhatsApp, and Slack to the
Nexus FastAPI backend via intent routing and skills.

```
User message → channel adapter → intent router → skill → FastAPI endpoint → response
```

---

## What It Does

OpenClaw translates natural language messages from three chat channels into API calls
against the Nexus FastAPI backend (port 8000), then formats the responses for each channel.

Three skills are available:

| Keyword triggers | Skill | Backend endpoint |
|---|---|---|
| "what is", "search", "tell me about", anything unknown | `nexus-rag` | `POST /api/rag/query` |
| "classify", "lead", "followup", "follow up" | `nexus-leads` | `POST /api/agents/lead/classify` or `/followup` |
| "pipeline", "kpi", "report", "conversion" | `nexus-pipeline` | `GET /api/agents/pipeline/report` |

---

## Requirements

- Node.js v22+ (already installed in WSL2 via NodeSource)
- Nexus FastAPI running on port 8000
- `.env` in the project root with the variables below

---

## Environment Variables

All read from the root `.env` file (one level above `openclaw/`).

### Required (Telegram)

```bash
TELEGRAM_BOT_TOKEN=<your-token>         # from @BotFather on Telegram
OPENCLAW_NEXUS_API_URL=http://localhost:8000  # http://nexus-api:8000 in Docker
```

### Optional (WhatsApp via Twilio)

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+14155238886       # your Twilio WhatsApp-enabled number
```

### Optional (Slack)

```bash
SLACK_BOT_TOKEN=xoxb-xxxx-xxxx-xxxx   # from Slack App → OAuth & Permissions
SLACK_APP_TOKEN=xapp-xxxx-xxxx-xxxx   # from Slack App → Basic Information → App-Level Tokens
```

The gateway starts with only Telegram if WhatsApp or Slack vars are missing.
A warning is logged, but the process does not exit.

---

## Installation

```bash
cd openclaw
npm install
```

---

## Starting the Gateway

```bash
# From the openclaw/ directory
node index.js

# Or from the project root
node openclaw/index.js
```

Expected output on successful start:

```
Nexus OpenClaw Gateway starting...
Nexus API: http://localhost:8000
Telegram bot connected — polling for messages
Webhook server listening on port 3456
WhatsApp channel active — webhook at /webhook/whatsapp
Slack bot connected — Socket Mode active
```

If WhatsApp or Slack tokens are not set:

```
WARNING: Twilio env vars missing — WhatsApp channel will not start
WARNING: Slack env vars missing — Slack channel will not start
```

---

## Channel Setup

### Telegram

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. `/newbot` → follow prompts → copy the token into `TELEGRAM_BOT_TOKEN` in `.env`
3. Start the gateway — the bot is immediately available via polling
4. Find your bot by username and start a conversation

No public URL required. The bot polls Telegram's servers.

**Tip:** If you see `409 Conflict` in the logs, two instances of the gateway are running.
Kill them all and restart:

```bash
pkill -f "node index.js"
node openclaw/index.js
```

---

### WhatsApp via Twilio

Twilio uses **webhooks** — Twilio POSTs incoming messages to your server.
For local development, you need [ngrok](https://ngrok.com) to give Twilio a public URL.

**Step 1: Install ngrok**

```bash
npm install -g ngrok
# or: brew install ngrok  (Mac)
```

**Step 2: Start the gateway, then expose port 3456**

```bash
# Terminal 1
node openclaw/index.js

# Terminal 2
ngrok http 3456
```

Copy the `https://xxxxx.ngrok.io` URL that ngrok displays.

**Step 3: Configure Twilio**

1. Go to [Twilio Console](https://console.twilio.com) → Messaging → Try it out → Send a WhatsApp message
2. Under "Sandbox Configuration" → "When a message comes in":
   ```
   https://xxxxx.ngrok.io/webhook/whatsapp
   ```
   Method: `HTTP POST`
3. Save

**Step 4: Connect your phone**

Follow the Twilio sandbox instructions (send a specific word to the sandbox number).
Then send any message — it routes through ngrok → OpenClaw → Nexus FastAPI.

**Note:** ngrok URLs change every time you restart ngrok (free tier).
Update the Twilio webhook URL each session, or upgrade to a paid ngrok plan for a stable URL.
For production, use your server's real domain with HTTPS.

---

### Slack

Slack uses **Socket Mode** — the bot connects outbound to Slack's servers.
No public URL or ngrok needed.

**Step 1: Create a Slack App**

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch
2. Name it "Nexus" and pick your workspace

**Step 2: Enable Socket Mode**

In the app settings → Socket Mode → Enable Socket Mode → Create App-Level Token:
- Name: `nexus-socket`
- Scopes: `connections:write`
- Copy the `xapp-…` token → `SLACK_APP_TOKEN` in `.env`

**Step 3: Add Bot Token Scopes**

OAuth & Permissions → Bot Token Scopes → Add:
- `chat:write`
- `im:history`
- `channels:history`
- `groups:history`

**Step 4: Enable Event Subscriptions**

Event Subscriptions → Enable Events → Subscribe to Bot Events:
- `message.im`
- `message.channels`
- `message.groups`

**Step 5: Install to Workspace**

OAuth & Permissions → Install to Workspace → Copy the `xoxb-…` token → `SLACK_BOT_TOKEN` in `.env`

**Step 6: Start the gateway**

The Slack app connects automatically when both tokens are set.

**Step 7: Invite the bot to a channel**

In Slack: `/invite @Nexus` in any channel where you want it to respond.

---

## Running Integration Tests

The integration tests require Nexus FastAPI to be running.

```bash
# Terminal 1: Start FastAPI
cd /mnt/c/Dan_WS/Nexus-AI
source venv/bin/activate
uvicorn api.main:app --reload --port 8000

# Terminal 2: Run tests
node tests/test_openclaw_skills.js
```

Expected output:

```
✅ Health endpoint returns ok or degraded
✅ RAG query returns answer string and sources array
✅ Lead classify returns valid stage and numeric score
✅ MCP tools endpoint returns exactly 10 tools
✅ Pipeline report returns kpis object with required fields

5 tests — 5 passed, 0 failed
```

**Note:** Test 5 (pipeline report) takes 5–25 seconds because the Pipeline Reporter
makes a real LLM call. This is normal behaviour. The test timeout is 60 seconds.

**Note:** Test 2 (RAG) checks the response shape only. If no documents have been
ingested, the answer will be "I don't have that information in the knowledge base."
which still passes (it's a non-empty string). For a richer test:

```bash
curl -X POST http://localhost:8000/api/rag/ingest \
     -H 'Content-Type: application/json' \
     -d '{"source": "https://projecx.io"}'
```

---

## Skill Reference

### nexus-rag — Knowledge Base Search

**Trigger keywords:** "what is", "search", "tell me about", or any unknown question.

**Example messages:**
- `What is Revenyu?`
- `Tell me about Bandora CMS`
- `Search for AI CRM features`

**What it does:** Calls `POST /api/rag/query` with hybrid semantic + BM25 retrieval,
CrossEncoder reranking, and an LLM-generated answer with source citations.

**First query after startup:** Slow (~55 seconds) — the CrossEncoder model (~90MB) is
being downloaded from HuggingFace. All subsequent queries are fast (2–15 seconds).

---

### nexus-leads — Lead Classifier + Follow-up Writer

**Trigger keywords:** "classify", "lead", "followup", "follow up", "follow-up"

**Example messages — classify:**
- `Classify this lead: Company: Gulf Properties, contact: Ahmed Hassan, ahmed@gulf.ae. Message: We need an AI CRM for 200 agents, budget approved.`
- `New lead from Acme Corp — they want to automate their sales pipeline`

**Example messages — follow-up:**
- `followup for deal ae140801-dce7-4b8c-9a44-08df0408f195`
- `write a follow up for deal ae140801-dce7-4b8c-9a44-08df0408f195`

**For follow-ups:** Find deal IDs in the database:
```bash
sqlite3 /mnt/c/Dan_WS/Nexus-AI/nexus.db "SELECT id, stage FROM deals LIMIT 5;"
```

---

### nexus-pipeline — Pipeline KPI Report

**Trigger keywords:** "pipeline", "kpi", "report", "conversion"

**Example messages:**
- `Pipeline report`
- `What are our KPIs?`
- `Show me the conversion rate`
- `Report`

**What it does:** Calls `GET /api/agents/pipeline/report` which runs the 5-node
Pipeline Reporter agent — SQL queries → KPI computation → bottleneck detection → LLM digest.

**Speed:** 5–25 seconds (LLM call). Send the trigger and wait.

---

## Architecture

```
openclaw/
├── SOUL.md              ← Nexus persona definition
├── MEMORY.md            ← company context seed
├── package.json         ← Node.js ESM project
├── index.js             ← entry point: Telegram + WhatsApp + Slack + intent router
└── skills/
    ├── nexus-rag/skill.js      ← POST /api/rag/query
    ├── nexus-leads/skill.js    ← POST /api/agents/lead/classify + /followup
    └── nexus-pipeline/skill.js ← GET /api/agents/pipeline/report
```

The gateway runs at port 3456 (WhatsApp webhook + health endpoint).
Telegram and Slack use outbound connections (polling / Socket Mode) — no inbound port needed.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FATAL: TELEGRAM_BOT_TOKEN is not set` | Missing env var | Add to `.env`, restart |
| `409 Conflict` in Telegram logs | Two bot instances running | `pkill -f "node index.js"` then restart |
| `EAI_AGAIN api.telegram.org` | WSL2 DNS intermittency | Add `nameserver 8.8.8.8` to `/etc/resolv.conf` |
| WhatsApp messages sent but no reply | ngrok URL not set in Twilio | Update webhook URL in Twilio console |
| `Slack startup failed` | Wrong token type | `SLACK_APP_TOKEN` must start with `xapp-`, not `xoxb-` |
| Pipeline times out | LLM cold start on free tier | Wait 30s and retry; or switch to `LLM_BACKEND=ollama` in `.env` |
| RAG returns empty answer | No documents ingested | Run `POST /api/rag/ingest` with a URL or file path |
| `ECONNREFUSED` from any skill | FastAPI not running | `uvicorn api.main:app --reload --port 8000` |

---

*Nexus-AI OpenClaw Gateway — Phase 4 complete*
*Owner: Abdel Rahman M. El-Saied*