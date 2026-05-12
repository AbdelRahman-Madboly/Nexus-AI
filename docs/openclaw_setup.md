# OpenClaw Gateway — Setup Guide
> Connect Telegram, WhatsApp, and Slack to Nexus-AI without touching the dashboard.
> Owner: Abdel Rahman M. El-Saied

---

## What OpenClaw Is

OpenClaw is the Node.js messaging gateway that sits between your chat channels and the
Nexus-AI FastAPI backend. It runs on port 3456 and handles three channels in parallel:

- **Telegram** — polling mode, no public URL required
- **WhatsApp** — Twilio webhook, requires a public URL (ngrok for local dev)
- **Slack** — Socket Mode, no public URL required

All three channels route through the same intent detector and call the same FastAPI
endpoints. The user experience is identical regardless of which channel they use.

---

## Architecture

```
User message (any channel)
        ↓
Intent Router  (keyword-based, zero LLM cost)
        ↓
  ┌─────┴──────┐
  pipeline?   leads?   (everything else)
  ↓           ↓              ↓
nexus-pipeline  nexus-leads  nexus-rag
  ↓           ↓              ↓
GET /api/agents/pipeline/report
POST /api/agents/lead/classify
POST /api/agents/lead/followup
POST /api/rag/query
        ↓
Formatted response → back to the originating channel
```

**Intent routing keywords (checked in this order):**

| Keywords | Skill |
|---|---|
| `pipeline`, `kpi`, `report`, `conversion` | nexus-pipeline |
| `classify`, `lead`, `followup`, `follow up`, `follow-up` | nexus-leads |
| Everything else | nexus-rag (default) |

---

## Prerequisites

- Node.js v22+ installed in WSL2
  ```bash
  node --version   # must be v22.x.x
  ```
- Nexus-AI FastAPI running on port 8000
  ```bash
  curl http://localhost:8000/api/health   # must return status: ok
  ```
- At least one channel token configured (Telegram is required; WhatsApp and Slack are optional)

---

## Part 1 — Telegram Setup

Telegram uses polling — no public URL needed. It works on localhost.

### 1.1 — Create a bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Follow the prompts — give it a name and a username (must end in `bot`)
4. BotFather replies with your bot token:
   ```
   8718556370:AAH0P2sGLqunb-DCQJw36HwjtVJztsiP48c
   ```
5. Copy this token — you will not see it again (you can revoke and regenerate with `/token`)

### 1.2 — Add to `.env`

```bash
TELEGRAM_BOT_TOKEN=8718556370:AAH0P2sGLqunb-DCQJw36HwjtVJztsiP48c
```

### 1.3 — Test

Start the gateway (see Part 4), then open Telegram and send your bot:

```
/start
```

Expected response: welcome message listing the three available skills.

```
What is Revenyu?
```

Expected: RAG answer from the knowledge base.

```
pipeline report
```

Expected: formatted KPI summary (takes 5–15s for the reporter agent to run).

---

## Part 2 — WhatsApp Setup (Twilio)

WhatsApp uses an inbound Twilio webhook. Twilio needs a public HTTPS URL to send messages
to. In local development, use ngrok. In production, use your server's public IP with a
reverse proxy.

### 2.1 — Create a Twilio account

1. Sign up at [twilio.com](https://www.twilio.com)
2. Go to **Console** → **Messaging** → **Try it out** → **Send a WhatsApp message**
3. Follow the sandbox setup — you will send a join code to the Twilio sandbox number from your WhatsApp

### 2.2 — Get your credentials

From the Twilio Console dashboard:

| Value | Where to find it |
|---|---|
| Account SID | Dashboard → Account Info |
| Auth Token | Dashboard → Account Info (click to reveal) |
| Phone number | Messaging → Senders → WhatsApp senders |

### 2.3 — Add to `.env`

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+14155238886   # your Twilio sandbox number
```

### 2.4 — Expose port 3456 with ngrok (local dev)

```bash
# Install ngrok if not already installed
# Download from: https://ngrok.com/download

# Expose the gateway port
ngrok http 3456
```

ngrok will display a public URL like:
```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:3456
```

### 2.5 — Configure Twilio webhook

1. In the Twilio Console → **Messaging** → **Settings** → **WhatsApp sandbox settings**
2. Set **When a message comes in** to:
   ```
   https://abc123.ngrok-free.app/webhook/whatsapp
   ```
   Method: `HTTP POST`
3. Save

### 2.6 — Test

Send a WhatsApp message to your Twilio sandbox number:

```
pipeline report
```

Expected: TwiML formatted response with KPI summary.

**Note:** WhatsApp responses are plain text only — no markdown formatting.

**Note:** ngrok URLs change every session (free tier). Update the Twilio webhook URL each time you restart ngrok. For persistent dev, use a paid ngrok plan or deploy to a VPS.

---

## Part 3 — Slack Setup

Slack uses Socket Mode — a persistent WebSocket connection from the gateway to Slack.
No public URL is required.

### 3.1 — Create a Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Name it `Nexus-AI` and pick your workspace

### 3.2 — Enable Socket Mode

1. Left sidebar → **Socket Mode**
2. Toggle **Enable Socket Mode** on
3. Give the token a name (e.g. `nexus-socket`)
4. Copy the **App-Level Token** — starts with `xapp-`

### 3.3 — Add OAuth scopes

Left sidebar → **OAuth & Permissions** → **Bot Token Scopes** → Add:

| Scope | Why |
|---|---|
| `chat:write` | Post messages to channels |
| `app_mentions:read` | Respond when @mentioned |
| `channels:history` | Read channel messages |
| `im:history` | Read direct messages |
| `im:read` | Access DM conversations |
| `im:write` | Send direct messages |

### 3.4 — Enable Events

1. Left sidebar → **Event Subscriptions**
2. Toggle **Enable Events** on
3. Under **Subscribe to bot events**, add:
   - `message.channels`
   - `message.im`
   - `app_mention`

### 3.5 — Install the app

1. Left sidebar → **OAuth & Permissions**
2. Click **Install to Workspace**
3. Copy the **Bot User OAuth Token** — starts with `xoxb-`

### 3.6 — Add to `.env`

```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_APP_TOKEN=xapp-your-app-level-token-here
```

### 3.7 — Invite the bot to a channel

In Slack, open the channel you want the bot to respond in and run:

```
/invite @Nexus-AI
```

### 3.8 — Test

Send a message in the channel (or DM the bot directly):

```
pipeline report
```

Expected: formatted KPI summary posted in the channel.

---

## Part 4 — Starting the Gateway

### Development (direct Node.js)

```bash
cd /mnt/c/Dan_WS/Nexus-AI/openclaw

# Install dependencies (first time only)
npm install

# Start with live reload
npm run dev
# or: node --watch index.js

# Start without reload
npm start
# or: node index.js
```

Expected startup output:

```
[OpenClaw] Nexus API: http://nexus-api:8000
[Telegram] Bot started — polling
[WhatsApp] Express webhook on port 3456
[Slack]    Socket Mode connected
[OpenClaw] All channels ready
```

If a channel token is missing, it logs a warning and skips that channel — the process
does not exit. Telegram is the only required channel.

### Production (Docker)

The `nexus-openclaw` service in `docker-compose.yml` is currently a placeholder
(`node:22-alpine` running `tail -f /dev/null`). To run the gateway in Docker:

1. Add a `Dockerfile` to `openclaw/`:

   ```dockerfile
   FROM node:22-alpine
   WORKDIR /app
   COPY package*.json ./
   RUN npm ci --production
   COPY . .
   CMD ["node", "index.js"]
   ```

2. Update `docker-compose.yml` `nexus-openclaw` service:

   ```yaml
   nexus-openclaw:
     build:
       context: ./openclaw
       dockerfile: Dockerfile
     ports:
       - "3456:3456"
     env_file: .env
     depends_on:
       - nexus-api
   ```

3. Rebuild:

   ```bash
   docker-compose down && docker-compose up -d --build nexus-openclaw
   ```

---

## Part 5 — Message Routing Reference

### What each skill does

**nexus-rag** — calls `POST /api/rag/query`

Accepts any natural language question. Returns the LLM answer plus source count and latency.

```
You: What is Revenyu?
Bot: Revenyu is a next-generation CRM platform purpose-built for the real estate sector
     in the UAE and broader GCC region.

     📚 Sources: 3 chunks (1.5s)
```

**nexus-leads** — calls `POST /api/agents/lead/classify` or `POST /api/agents/lead/followup`

Sub-intent detection happens inside the skill. "followup" / "follow up" / "follow-up"
keywords trigger `handleFollowup()`. Everything else triggers `handleClassify()`.

Classify example:
```
You: classify lead: Acme Corp, Jane Smith, jane@acme.com — they want CRM for 200 agents, budget approved
Bot: 🔥 Lead classified as HOT_LEAD (score: 88/100)

     Reasoning: High intent: budget approved, 200-agent scale, explicit CRM need.

     Run ID: `1dd1b8d6-...`
```

Follow-up example (UUID must be in the message):
```
You: followup for deal 1dd1b8d6-3502-4637-af63-90afa0e052f1
Bot: ✉️ Follow-up draft (review score: 82/100)

     Dear Jane, following our conversation about the Revenyu CRM deployment...

     Run ID: `9397bbb8-...`
```

Stage emoji reference:

| Stage | Emoji |
|---|---|
| `hot_lead` | 🔥 |
| `nurture` | 🌱 |
| `proposal` | 📋 |
| `closed_won` | 🏆 |
| `closed_lost` | ❌ |
| `disqualified` | 🚫 |
| `escalated` | ⚠️ |
| `new_lead` | 🆕 |

**nexus-pipeline** — calls `GET /api/agents/pipeline/report`

Timeout is 60 seconds (overrides the shared 30s default). Returns headline KPIs, bottleneck
bullets, and the first paragraph of the LLM executive digest.

```
You: pipeline report
Bot: 📊 Conversion: 32.5% · ⏱ Avg deal age: 14.2 days · 💰 Pipeline: $245,000

     ⚠️ Bottlenecks:
     • Lead qualification bottleneck
     • Deals aging: average 14.2 days in pipeline

     The pipeline shows healthy volume but stagnation in the nurture stage...

     Run ID: `abc12345-...`
```

---

## Part 6 — Channel Character Limits

| Channel | Limit | Notes |
|---|---|---|
| Telegram | 4096 chars | Markdown supported; long responses truncated |
| WhatsApp | 1500 chars | Plain text only — markdown stripped before sending |
| Slack | 2800 chars | Markdown supported; mrkdwn formatting |

All three truncate gracefully with a `… (truncated)` suffix if over limit.

---

## Part 7 — Troubleshooting

### Telegram `409 Conflict`

```
Cause: Two instances of the bot are running (two node index.js processes)
Fix:   pkill -f "node index.js"
       Then restart: node openclaw/index.js
```

### Telegram `EAI_AGAIN` DNS errors

```
Cause: WSL2 DNS intermittency — known issue, not a code problem
Impact: bot.on('polling_error') catches it and continues polling
Fix if persistent: echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
```

### WhatsApp — Twilio returns 11200 (HTTP retrieval failure)

```
Cause: ngrok URL not set in Twilio webhook, or ngrok session expired
Fix:   Restart ngrok → copy new URL → update Twilio sandbox settings webhook URL
```

### WhatsApp — no response received

```
Cause A: Express server not running (port 3456 not open)
Cause B: TWILIO_AUTH_TOKEN wrong — Twilio sends but validation fails silently
Fix A:   curl http://localhost:3456/health → should return {"status":"ok"}
Fix B:   Double-check TWILIO_AUTH_TOKEN in .env matches Twilio console
```

### Slack — bot connects but doesn't respond

```
Cause A: Bot not invited to the channel (/invite @Nexus-AI)
Cause B: Missing message.channels or message.im event subscription
Cause C: Bot responding to its own messages (infinite loop guard missing)
Fix A:   /invite @Nexus-AI in the target channel
Fix B:   api.slack.com/apps → Event Subscriptions → add missing event → reinstall app
Fix C:   Already guarded in index.js — check bot_message and message_changed subtypes
```

### Gateway starts but all skills return "FastAPI not running"

```
Cause: OPENCLAW_NEXUS_API_URL in .env pointing to wrong address
       In Docker: http://nexus-api:8000 (service name)
       In dev (direct node): http://localhost:8000
Fix:   Check OPENCLAW_NEXUS_API_URL in .env matches how the API is running
```

---

## Part 8 — Integration Tests

```bash
# FastAPI must be running before running tests
node tests/test_openclaw_skills.js
```

| Test | Endpoint | What it checks |
|---|---|---|
| 1 Health | GET /api/health | `status` in `['ok','degraded']`, components object present |
| 2 RAG | POST /api/rag/query | `answer:string`, `sources:array`, `latency_ms:number` |
| 3 Leads | POST /api/agents/lead/classify | `stage` valid, `score` 0–100, `run_id` string |
| 4 MCP | GET /api/mcp/tools | `count === 10`, each tool has `name` + `description` |
| 5 Pipeline | GET /api/agents/pipeline/report | `kpis` has 4 fields, `bottlenecks:array`, `digest:string` |

Expected output:
```
✅ Test 1 passed: Health check
✅ Test 2 passed: RAG query
✅ Test 3 passed: Lead classification
✅ Test 4 passed: MCP tools list
✅ Test 5 passed: Pipeline report
5 tests — 5 passed, 0 failed
```

---

*OpenClaw Setup Guide — v1.0.0*
*Owner: Abdel Rahman M. El-Saied*
*GitHub: github.com/AbdelRahman-Madboly/Nexus-AI*