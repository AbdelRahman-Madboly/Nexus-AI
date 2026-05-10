/**
 * openclaw/index.js
 * =================
 * Nexus-AI OpenClaw Gateway — Phase 4, Day 12
 *
 * Entry point for the conversational gateway.
 * Handles three channels in parallel:
 *   - Telegram  (polling — no public URL needed)
 *   - WhatsApp  (Twilio webhook — Express server on port 3456)
 *   - Slack     (Bolt SDK Socket Mode — no public URL needed)
 *
 * All three channels share the same routeIntent() and dispatchSkill() functions.
 * Adding a fourth channel in the future means writing ~20 lines of adapter code.
 *
 * Architecture:
 *   User message → channel adapter → routeIntent() → dispatchSkill() → skill.js → FastAPI → response
 *
 * Day 11: Telegram + RAG skill + Leads skill
 * Day 12: WhatsApp + Slack + Pipeline skill + dispatchSkill() shared helper
 */

// ---------------------------------------------------------------------------
// ESM-safe __dirname (not available natively in ESM modules)
// ---------------------------------------------------------------------------
import { dirname, resolve } from 'path';
import { fileURLToPath }    from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);

// ---------------------------------------------------------------------------
// Load .env from project root (one level above openclaw/)
// Must happen BEFORE any process.env read — including import-time env checks
// ---------------------------------------------------------------------------
import { config } from 'dotenv';
config({ path: resolve(__dirname, '../.env') });

// ---------------------------------------------------------------------------
// Core imports
// ---------------------------------------------------------------------------
import TelegramBot         from 'node-telegram-bot-api';
import axios               from 'axios';
import express             from 'express';
import twilio              from 'twilio';
import { App as SlackApp } from '@slack/bolt';

// ---------------------------------------------------------------------------
// Skills — all three are now live
// ---------------------------------------------------------------------------
import { handleRag }      from './skills/nexus-rag/skill.js';
import { handleLeads }    from './skills/nexus-leads/skill.js';
import { handlePipeline } from './skills/nexus-pipeline/skill.js';

// ---------------------------------------------------------------------------
// Validate required environment variables at startup
// Fail fast with a clear message rather than a cryptic runtime error later
// ---------------------------------------------------------------------------
const TELEGRAM_BOT_TOKEN     = process.env.TELEGRAM_BOT_TOKEN;
const OPENCLAW_NEXUS_API_URL = process.env.OPENCLAW_NEXUS_API_URL || 'http://localhost:8000';
const TWILIO_ACCOUNT_SID     = process.env.TWILIO_ACCOUNT_SID;
const TWILIO_AUTH_TOKEN      = process.env.TWILIO_AUTH_TOKEN;
const TWILIO_PHONE_NUMBER    = process.env.TWILIO_PHONE_NUMBER;
const SLACK_BOT_TOKEN        = process.env.SLACK_BOT_TOKEN;
const SLACK_APP_TOKEN        = process.env.SLACK_APP_TOKEN;

if (!TELEGRAM_BOT_TOKEN) {
  console.error('FATAL: TELEGRAM_BOT_TOKEN is not set in .env');
  process.exit(1);
}

// WhatsApp and Slack are optional — log a warning but do not crash.
// This lets the gateway run with only Telegram during development.
if (!TWILIO_ACCOUNT_SID || !TWILIO_AUTH_TOKEN || !TWILIO_PHONE_NUMBER) {
  console.warn('WARNING: Twilio env vars missing — WhatsApp channel will not start');
}
if (!SLACK_BOT_TOKEN || !SLACK_APP_TOKEN) {
  console.warn('WARNING: Slack env vars missing — Slack channel will not start');
}

// ---------------------------------------------------------------------------
// Shared axios instance — all skills import this
// 30-second timeout covers most LLM calls (classify, RAG).
// Pipeline skill overrides to 60s for its slower reporter agent.
// ---------------------------------------------------------------------------
export const nexusApi = axios.create({
  baseURL: OPENCLAW_NEXUS_API_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

// ---------------------------------------------------------------------------
// Intent router — keyword-based, deterministic, zero LLM cost
// Returns one of: 'rag' | 'leads' | 'pipeline'
//
// Pipeline keywords are checked first — they are more specific.
// 'report' could match a lead-related question, but in practice
// users say 'report' when they want pipeline data, not lead info.
// RAG is the fallback — it handles unknown questions gracefully
// by returning "I don't have that in the knowledge base."
// ---------------------------------------------------------------------------
export function routeIntent(message) {
  const text = message.toLowerCase();

  if (
    text.includes('pipeline') ||
    text.includes('kpi')      ||
    text.includes('report')   ||
    text.includes('conversion')
  ) {
    return 'pipeline';
  }

  if (
    text.includes('classify') ||
    text.includes('lead')     ||
    text.includes('followup') ||
    text.includes('follow up')
  ) {
    return 'leads';
  }

  // RAG as default — handles 'search', 'what is', 'tell me about', and unknowns
  return 'rag';
}

// ---------------------------------------------------------------------------
// Skill dispatcher — shared by Telegram, WhatsApp, and Slack
// Exported so tests can import it directly.
// Adding a new skill = adding one case here.
// ---------------------------------------------------------------------------
export async function dispatchSkill(intent, message) {
  switch (intent) {
    case 'rag':      return await handleRag(message, nexusApi);
    case 'leads':    return await handleLeads(message, nexusApi);
    case 'pipeline': return await handlePipeline(message, nexusApi);
    default:         return await handleRag(message, nexusApi);
  }
}

// ===========================================================================
// CHANNEL 1: Telegram (polling)
// No public URL needed — Telegram pushes nothing; we pull.
// Ideal for development and self-hosted setups.
// For production: switch to webhook mode (requires HTTPS domain).
// ===========================================================================
const bot = new TelegramBot(TELEGRAM_BOT_TOKEN, { polling: true });

// Telegram polling error handler — log and continue, never crash.
// Code 409 = two bot instances running: kill the old one with
//   pkill -f "node index.js"
bot.on('polling_error', (err) => {
  console.error(`[Telegram polling error] ${err.code}: ${err.message}`);
});

// /start command — welcome message listing all three skills
bot.onText(/\/start/, (msg) => {
  const welcome = [
    '👋 I\'m *Nexus*, your AI business operations assistant.',
    '',
    'Here\'s what I can do:',
    '• 🔍 *Search the knowledge base* — "What is Revenyu?"',
    '• 🎯 *Classify a lead* — "Classify this lead: [company details]"',
    '• ✉️ *Draft a follow-up* — "Followup for deal [deal-id]"',
    '• 📊 *Pipeline report* — "Pipeline report" _(takes ~15 seconds)_',
    '',
    'Just type your question — no commands needed.',
  ].join('\n');
  bot.sendMessage(msg.chat.id, welcome, { parse_mode: 'Markdown' });
});

// Text message handler
bot.on('message', async (msg) => {
  if (!msg.text || msg.text.startsWith('/')) return;

  const chatId = msg.chat.id;
  const text   = msg.text.trim();

  // Immediate acknowledgement — user knows it's working while the API call runs
  await bot.sendMessage(chatId, '🔍 Looking that up...');

  try {
    const intent   = routeIntent(text);
    const response = await dispatchSkill(intent, text);

    // Telegram has a 4096-char limit — truncate with notice if needed
    const safe = response.length > 4000
      ? response.slice(0, 3990) + '\n\n_(response truncated)_'
      : response;

    await bot.sendMessage(chatId, safe, { parse_mode: 'Markdown' });

  } catch (err) {
    console.error(`[Telegram message error] chatId=${chatId}:`, err.message);
    await bot.sendMessage(
      chatId,
      '⚠️ Something went wrong. The Nexus server may be starting up. Try again in 30 seconds.'
    );
  }
});

console.log('Telegram bot connected — polling for messages');

// ===========================================================================
// CHANNEL 2: WhatsApp via Twilio webhook + Express
//
// How it works:
//   1. User sends WhatsApp message to your Twilio sandbox number
//   2. Twilio POSTs the message to this Express endpoint
//   3. We process it and return TwiML (Twilio Markup Language) with the reply
//   4. Twilio delivers the reply back to the user
//
// For local dev: use ngrok to give Twilio a public URL.
//   ngrok http 3456
//   → Copy the https://xxxxx.ngrok.io URL into:
//   Twilio Console → Messaging → Sandbox → "When a message comes in"
//   → https://xxxxx.ngrok.io/webhook/whatsapp
//
// The Express server also runs on port 3456 even without Twilio credentials
// so that the Docker port mapping remains live and curl tests work.
// ===========================================================================
const expressApp = express();

// Parse URL-encoded form data — Twilio POSTs in application/x-www-form-urlencoded
expressApp.use(express.urlencoded({ extended: false }));

// Health probe — lets docker-compose health check hit this service directly
expressApp.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'nexus-openclaw' });
});

// WhatsApp webhook endpoint
expressApp.post('/webhook/whatsapp', async (req, res) => {
  // req.body.From = "whatsapp:+201234567890"
  // req.body.Body = user's message text
  const body    = (req.body.Body || '').trim();
  const from    = req.body.From  || 'unknown';
  const twiml   = new twilio.twiml.MessagingResponse();

  if (!body) {
    twiml.message('Hi! Send me a question and I\'ll look it up in Nexus.');
    return res.type('text/xml').send(twiml.toString());
  }

  // Only process WhatsApp if Twilio credentials are configured
  if (!TWILIO_ACCOUNT_SID || !TWILIO_AUTH_TOKEN) {
    twiml.message('WhatsApp channel is not configured on this server.');
    return res.type('text/xml').send(twiml.toString());
  }

  try {
    const intent   = routeIntent(body);
    const response = await dispatchSkill(intent, body);

    // WhatsApp has a 1600-char limit on TwiML message bodies — truncate if needed
    const safe = response.length > 1500
      ? response.slice(0, 1490) + '...(truncated)'
      : response;

    // Strip Markdown formatting — WhatsApp does not render *bold* or `code`
    const plain = safe
      .replace(/\*([^*]+)\*/g, '$1')    // *bold* → bold
      .replace(/`([^`]+)`/g,   '$1')    // `code`  → code
      .replace(/_([^_]+)_/g,   '$1');   // _italic_ → italic

    twiml.message(plain);
    console.log(`[WhatsApp] from=${from} intent=${intent} chars=${plain.length}`);

  } catch (err) {
    console.error(`[WhatsApp error] from=${from}:`, err.message);
    twiml.message('⚠️ Something went wrong. Try again in 30 seconds.');
  }

  res.type('text/xml').send(twiml.toString());
});

// Start Express — always, even without Twilio, so port 3456 is live
expressApp.listen(3456, () => {
  console.log('Webhook server listening on port 3456');
  if (TWILIO_ACCOUNT_SID) {
    console.log('WhatsApp channel active — webhook at /webhook/whatsapp');
  }
});

// ===========================================================================
// CHANNEL 3: Slack via Bolt SDK in Socket Mode
//
// Socket Mode connects to Slack over a WebSocket — no public URL needed.
// This is perfect for self-hosted development.
//
// Setup checklist:
//   1. Create a Slack App at api.slack.com/apps
//   2. Enable Socket Mode → create an App-Level Token (xapp-…) with connections:write
//   3. Add Bot Token Scopes: chat:write, im:history, channels:history
//   4. Install app to workspace → copy Bot Token (xoxb-…)
//   5. Set SLACK_BOT_TOKEN (xoxb-…) and SLACK_APP_TOKEN (xapp-…) in .env
//
// The Slack app is only started if both tokens are present.
// This lets the gateway run without Slack during dev.
// ===========================================================================
if (SLACK_BOT_TOKEN && SLACK_APP_TOKEN) {
  const slack = new SlackApp({
    token:      SLACK_BOT_TOKEN,
    appToken:   SLACK_APP_TOKEN,
    socketMode: true,
    // Suppress the default startup message — we log our own below
  });

  // Listen to all messages that @mention the bot, or DMs to the bot.
  // `message()` with no pattern matches everything in channels the bot can see.
  slack.message(async ({ message, say }) => {
    // Ignore bot messages and message edits — avoids infinite reply loops
    if (message.subtype === 'bot_message') return;
    if (message.subtype === 'message_changed') return;

    const text = (message.text || '').trim();
    if (!text) return;

    // Immediate acknowledgement — Slack shows typing indicator until we respond
    await say('🔍 Looking that up...');

    try {
      const intent   = routeIntent(text);
      const response = await dispatchSkill(intent, text);

      // Slack message limit is ~3000 chars in practice — truncate with notice
      const safe = response.length > 2800
        ? response.slice(0, 2790) + '\n_(response truncated)_'
        : response;

      await say(safe);

    } catch (err) {
      console.error('[Slack message error]:', err.message);
      await say('⚠️ Something went wrong. The Nexus server may be starting up. Try again in 30 seconds.');
    }
  });

  // Start the Slack app asynchronously — does not block Telegram or Express
  slack.start().then(() => {
    console.log('Slack bot connected — Socket Mode active');
  }).catch((err) => {
    // Non-fatal — Telegram and WhatsApp continue running even if Slack fails
    console.error('[Slack startup error]:', err.message);
    console.warn('Slack channel failed to start — check SLACK_BOT_TOKEN and SLACK_APP_TOKEN');
  });

} else {
  console.log('Slack channel skipped — SLACK_BOT_TOKEN or SLACK_APP_TOKEN not set');
}

// ---------------------------------------------------------------------------
// Startup log
// ---------------------------------------------------------------------------
console.log('Nexus OpenClaw Gateway starting...');
console.log(`Nexus API: ${OPENCLAW_NEXUS_API_URL}`);