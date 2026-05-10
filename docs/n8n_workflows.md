# n8n Workflows — Nexus-AI Reference

## Overview

n8n is a self-hosted workflow automation tool running inside the Nexus-AI Docker Compose stack (port 5678). It connects external events — webhook calls, cron schedules, emails, Slack messages — to the Nexus FastAPI without writing any additional code. Each workflow is a directed graph of nodes: a trigger node fires first, data flows through transformation and HTTP nodes, and terminal nodes send notifications or return responses.

In Nexus-AI, n8n sits between the outside world and the FastAPI backend. It handles the "when and who" layer — when a new lead arrives via a web form, when Monday morning comes, when a deal is flagged critical — while the FastAPI handles the "what" layer: AI classification, RAG retrieval, LangGraph agent execution. This separation means the AI logic is fully testable independently of the automation timing.

---

## Prerequisites

All three services must be running before using any workflow:

| Service | URL | Start command |
|---|---|---|
| n8n | http://localhost:5678 | `docker-compose up -d nexus-n8n` |
| Nexus FastAPI | http://localhost:8000 | `docker-compose up -d nexus-api` |
| OpenClaw (optional) | http://localhost:3456 | `node openclaw/index.js` |

Inside Docker, n8n reaches the FastAPI via `http://nexus-api:8000` (service name, not localhost). OpenClaw is reached via `http://nexus-openclaw:3456`.

---

## How to Import a Workflow

1. Open http://localhost:5678
2. Click the menu icon (☰, top left) → **Import from File**
3. Select the `.json` file from `n8n/workflows/`
4. The workflow opens in the editor
5. Click the **Activate** toggle (top right corner — turns green when live)

**Webhooks only listen when the workflow is Active.** Cron triggers also only fire when active. Always activate after importing.

---

## Credentials Setup

| Credential | n8n Type | Where to create |
|---|---|---|
| Slack | Slack API (OAuth2) | api.slack.com → create app → Bot Token (`xoxb-`) |
| Gmail | Gmail OAuth2 | console.cloud.google.com → OAuth2 Client ID |
| Twilio/WhatsApp | Called via HTTP Request — no n8n credential needed | `TWILIO_*` vars in `.env` |

### Slack setup
1. Go to https://api.slack.com/apps → **Create New App** → From scratch
2. Under **OAuth & Permissions** → add Bot Token Scopes: `chat:write`, `chat:write.public`
3. Install to workspace → copy the **Bot User OAuth Token**
4. n8n UI → **Credentials** → New → **Slack API** → paste token → Save
5. In each Slack channel: `/invite @your-bot-name`

Required channels: `#sales-alerts`, `#sales-leads`, `#sales-ops`, `#sales-team`

### Gmail setup
1. Go to https://console.cloud.google.com → **APIs & Services** → **Credentials**
2. Create **OAuth 2.0 Client ID** → Web application
3. Authorized redirect URI: `http://localhost:5678/rest/oauth2-credential/callback`
4. n8n UI → **Credentials** → New → **Gmail OAuth2** → paste Client ID + Secret → **Connect**
5. Complete the Google sign-in popup

---

## Workflow 1 — Lead Intake

| Field | Value |
|---|---|
| File | `n8n/workflows/lead-intake.json` |
| Trigger | `POST http://localhost:5678/webhook/lead-intake` |
| Required body fields | `company`, `contact_name`, `source`, `message` |
| Optional body fields | `contact_email` |
| Output | Classification JSON returned to caller |
| Notifications | Slack `#sales-alerts` (hot/escalated) or `#sales-leads` (all others) |

**Node flow:**
```
Webhook → Extract Lead Fields → Classify Lead → Hot Lead or Escalated?
  TRUE  → Slack #sales-alerts → Respond to Webhook
  FALSE → Slack #sales-leads  → Respond to Webhook
```

**Test command:**
```bash
curl -X POST http://localhost:5678/webhook/lead-intake \
  -H "Content-Type: application/json" \
  -d '{
    "company": "TechCorp Dubai",
    "contact_name": "Sara Ahmed",
    "contact_email": "sara@techcorp.ae",
    "source": "n8n_webhook",
    "message": "We need an AI CRM for our 150-person sales team. Budget approved for Q3."
  }'
```

Expected response:
```json
{ "stage": "hot_lead", "score": 82, "reasoning": "...", "run_id": "..." }
```

---

## Workflow 2 — Follow-up Scheduler

| Field | Value |
|---|---|
| File | `n8n/workflows/followup-scheduler.json` |
| Trigger | Daily cron at 9:00 AM (`0 9 * * *`) |
| Condition | Fires email + Slack only if `avg_deal_age > 7` OR bottlenecks present |
| Output | Gmail draft to `sales@projecx.io` + Slack `#sales-ops` |

**Node flow:**
```
Schedule Trigger → Get Pipeline Report → Check for Stale Deals → Stale Deals Found?
  TRUE  → Generate Follow-up Draft → Send Follow-up Draft (Gmail) → Notify: Follow-up Sent (Slack)
  FALSE → No Stale Deals (NoOp)
```

**Manual test (no need to wait for 9 AM):**
- Open http://localhost:5678 → **Follow-up Scheduler** → **Test** tab → **Execute Now**
- Expected: pipeline report fetched; if stale deals found, Gmail sent + Slack notified

---

## Workflow 3 — Pipeline Digest

| Field | Value |
|---|---|
| File | `n8n/workflows/pipeline-digest.json` |
| Trigger | Every Monday at 8:00 AM (`0 8 * * 1`) |
| Output | Gmail HTML report to `sales@projecx.io` + Slack `#sales-team` |

**Node flow:**
```
Schedule Trigger → Get Pipeline Report → Format KPI Fields → Send Weekly Digest (Gmail) → Post Weekly Summary (Slack)
```

**KPIs included:** Conversion rate, avg deal age, total pipeline value, bottleneck count + full LLM digest.

**Manual test:**
- Open http://localhost:5678 → **Pipeline Digest** → **Test** tab → **Execute Now**
- Expected: Gmail sent + Slack message in `#sales-team`

---

## Workflow 4 — Alert Escalation

| Field | Value |
|---|---|
| File | `n8n/workflows/alert-escalation.json` |
| Trigger | `POST http://localhost:5678/webhook/alert-escalation` |
| Required body fields | `deal_id`, `company`, `contact_name`, `reason` |
| Optional body fields | `escalation_level` (`standard`\|`critical`, default `standard`), `assigned_to` |
| Immediate output | JSON acknowledgement + WhatsApp alert + Slack `#sales-alerts` |
| Delayed output (4 hrs) | Slack `#sales-alerts` (critical) or `#sales-team` (standard) |

**Node flow:**
```
Webhook → Extract Alert Fields → [WhatsApp Alert + Immediate Slack] (parallel)
  → Respond to Webhook (immediate acknowledgement)
  → Wait 4 Hours
  → Critical Escalation?
      TRUE  → Escalation: Critical (#sales-alerts @channel)
      FALSE → Escalation: Reminder (#sales-team)
```

**Important:** `Respond to Webhook` runs *before* the Wait node. The caller gets an immediate `200 acknowledged` response; the 4-hour follow-up executes asynchronously in the background.

**Test command:**
```bash
curl -X POST http://localhost:5678/webhook/alert-escalation \
  -H "Content-Type: application/json" \
  -d '{
    "deal_id": "test-deal-001",
    "company": "Risky Corp",
    "contact_name": "Omar Hassan",
    "escalation_level": "critical",
    "reason": "Contract dispute — legal review required",
    "assigned_to": "Abdel Rahman"
  }'
```

Expected immediate response:
```json
{ "acknowledged": true, "deal_id": "test-deal-001", "escalation_review_in": "4 hours" }
```

**For demo:** Shorten the Wait node to 1 minute to see the follow-up Slack fire without waiting 4 hours. Restore to 4 hours before production.

---

## Environment Variables Used by Workflows

| Variable | Used by | Purpose |
|---|---|---|
| `N8N_WEBHOOK_URL` | All webhook workflows | Base URL for webhook triggers |
| `SLACK_BOT_TOKEN` | All Slack nodes | Bot authentication |
| `TWILIO_PHONE_NUMBER` | Alert Escalation | WhatsApp destination number |
| `TWILIO_ACCOUNT_SID` | OpenClaw (called by n8n) | WhatsApp sending |
| `TWILIO_AUTH_TOKEN` | OpenClaw (called by n8n) | WhatsApp sending |

These are set in `.env` and read by their respective services. n8n itself only needs the Slack credential (configured in n8n UI) — the rest are consumed by the FastAPI and OpenClaw containers it calls over HTTP.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Webhook returns 404 | Workflow not activated | Open workflow → click Activate toggle (must turn green) |
| HTTP Request fails — ECONNREFUSED | Using `localhost:8000` inside Docker | Change to `http://nexus-api:8000` in the node URL |
| HTTP Request fails — DNS error | `nexus-api` container not running | `docker-compose ps` → restart if down |
| Slack node runs but no message appears | Bot not in channel | In Slack: channel settings → Integrations → Add your bot |
| Slack node returns auth error | Wrong token or expired | n8n Credentials → Slack API → re-enter token |
| Gmail node returns 401 / invalid_grant | OAuth2 refresh token expired | n8n Credentials → Gmail OAuth2 → Reconnect → re-authorize |
| curl hangs for minutes | Respond to Webhook is after Wait node | Move Respond to Webhook to before the Wait node |
| Pipeline report times out | Default n8n timeout 10s; reporter takes 5–15s | HTTP Request node → Options → Timeout: 90000 |
| `$json.body` is undefined | n8n version uses `$json` directly for webhook body | Check execution log — click node after test run to see actual structure |
| Wait node fires immediately in test | Using "Test" mode bypasses Wait by default | Use "Execute" mode or temporarily set Wait to 1 minute |

---

*docs/n8n_workflows.md — Nexus-AI Phase 5*
*4 workflows: Lead Intake · Follow-up Scheduler · Pipeline Digest · Alert Escalation*
*Owner: Abdel Rahman M. El-Saied*