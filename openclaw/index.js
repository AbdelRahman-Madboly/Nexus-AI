/**
 * openclaw/index.js
 * =================
 * Nexus-AI OpenClaw Gateway — Phase 4, Day 11
 *
 * Entry point for the conversational gateway.
 * Handles Telegram in polling mode.
 * Routes every message to the correct skill via intent detection.
 * All HTTP calls to Nexus FastAPI go through the shared `nexusApi` axios instance.
 *
 * Architecture:
 *   User message → Telegram bot → routeIntent() → dispatchSkill() → skill.js → FastAPI → response
 *
 * Day 11: Telegram + RAG skill + Leads skill
 * Day 12: WhatsApp (Twilio webhook) + Slack (Bolt Socket Mode) + Pipeline skill
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
// Must happen before any env var is read
// ---------------------------------------------------------------------------
import { config } from 'dotenv';
config({ path: resolve(__dirname, '../.env') });

// ---------------------------------------------------------------------------
// Core imports
// ---------------------------------------------------------------------------
import TelegramBot from 'node-telegram-bot-api';
import axios       from 'axios';

// ---------------------------------------------------------------------------
// Skills — Day 11
// ---------------------------------------------------------------------------
import { handleRag }   from './skills/nexus-rag/skill.js';
import { handleLeads } from './skills/nexus-leads/skill.js';

// ---------------------------------------------------------------------------
// Validate required environment variables
// ---------------------------------------------------------------------------
const TELEGRAM_BOT_TOKEN     = process.env.TELEGRAM_BOT_TOKEN;
const OPENCLAW_NEXUS_API_URL = process.env.OPENCLAW_NEXUS_API_URL || 'http://localhost:8000';

if (!TELEGRAM_BOT_TOKEN) {
  console.error('FATAL: TELEGRAM_BOT_TOKEN is not set in .env');
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Shared axios instance — all skills import this
// 30-second timeout covers slow Gemini free-tier LLM calls
// ---------------------------------------------------------------------------
export const nexusApi = axios.create({
  baseURL: OPENCLAW_NEXUS_API_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

// ---------------------------------------------------------------------------
// Intent router
// Keyword-based classification — deterministic, no LLM cost
// Returns one of: 'rag' | 'leads' | 'pipeline'
// ---------------------------------------------------------------------------
export function routeIntent(message) {
  const text = message.toLowerCase();

  // Pipeline keywords checked first — more specific than generic 'report'
  if (
    text.includes('pipeline') ||
    text.includes('kpi')      ||
    text.includes('report')   ||
    text.includes('conversion')
  ) {
    return 'pipeline';
  }

  // Lead keywords
  if (
    text.includes('classify') ||
    text.includes('lead')     ||
    text.includes('followup') ||
    text.includes('follow up')
  ) {
    return 'leads';
  }

  // RAG keywords + default fallback
  // 'search', 'what is', 'tell me about' → knowledge base
  // Unknown intent → also falls to RAG (most forgiving handler)
  return 'rag';
}

// ---------------------------------------------------------------------------
// Skill dispatcher — shared by Telegram, WhatsApp (Day 12), Slack (Day 12)
// Exported so Day 12 channels can import it without duplication
// ---------------------------------------------------------------------------
export async function dispatchSkill(intent, message) {
  switch (intent) {
    case 'rag':      return await handleRag(message, nexusApi);
    case 'leads':    return await handleLeads(message, nexusApi);
    // 'pipeline' handled in Day 12 — graceful fallback until then
    case 'pipeline':
      return "Pipeline skill is coming in Day 12. For now, try: 'search pipeline performance'.";
    default:
      return await handleRag(message, nexusApi);
  }
}

// ---------------------------------------------------------------------------
// Telegram Bot — polling mode
// Polling works without a public URL — ideal for dev and self-hosted setups
// For production, switch to webhook mode (requires HTTPS domain)
// ---------------------------------------------------------------------------
const bot = new TelegramBot(TELEGRAM_BOT_TOKEN, { polling: true });

// Telegram polling error handler — log and continue, never crash
bot.on('polling_error', (err) => {
  // err.code examples: EFATAL, ETELEGRAM, EPARSE
  // 409 Conflict means two bot instances are running — kill the old one
  console.error(`[Telegram polling error] ${err.code}: ${err.message}`);
});

// ---------------------------------------------------------------------------
// /start command — welcome message
// ---------------------------------------------------------------------------
bot.onText(/\/start/, (msg) => {
  const chatId  = msg.chat.id;
  const welcome = [
    '👋 I\'m *Nexus*, your AI business operations assistant.',
    '',
    'Here\'s what I can do:',
    '• 🔍 *Search the knowledge base* — "What is Revenyu?"',
    '• 🎯 *Classify a lead* — "Classify this lead: [company details]"',
    '• ✉️ *Draft a follow-up* — "Followup for deal [deal-id]"',
    '• 📊 *Pipeline report* — "Pipeline report" _(coming Day 12)_',
    '',
    'Just type your question — no commands needed.',
  ].join('\n');

  bot.sendMessage(chatId, welcome, { parse_mode: 'Markdown' });
});

// ---------------------------------------------------------------------------
// Message handler — every text message (excluding commands)
// ---------------------------------------------------------------------------
bot.on('message', async (msg) => {
  // Ignore non-text messages (photos, stickers, etc.) and commands
  if (!msg.text || msg.text.startsWith('/')) return;

  const chatId  = msg.chat.id;
  const text    = msg.text.trim();

  // Immediate acknowledgement — user sees this while the API call is in flight
  await bot.sendMessage(chatId, '🔍 Looking that up...');

  try {
    const intent   = routeIntent(text);
    const response = await dispatchSkill(intent, text);

    // Telegram has a 4096-char message limit — truncate with notice if needed
    const safe = response.length > 4000
      ? response.slice(0, 3990) + '\n\n_(response truncated)_'
      : response;

    await bot.sendMessage(chatId, safe, { parse_mode: 'Markdown' });

  } catch (err) {
    console.error(`[message handler error] chatId=${chatId}:`, err.message);
    await bot.sendMessage(
      chatId,
      '⚠️ Something went wrong. The Nexus server may be starting up. Try again in 30 seconds.'
    );
  }
});

// ---------------------------------------------------------------------------
// Startup log
// ---------------------------------------------------------------------------
console.log('Nexus OpenClaw Gateway starting...');
console.log('Telegram bot connected — polling for messages');
console.log(`Nexus API: ${OPENCLAW_NEXUS_API_URL}`);