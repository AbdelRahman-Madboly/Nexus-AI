/**
 * openclaw/skills/nexus-leads/skill.js
 * =====================================
 * Lead classification and follow-up drafting skill for Nexus OpenClaw Gateway.
 *
 * Two sub-intents:
 *   1. Classify a new lead  → POST /api/agents/lead/classify
 *   2. Write a follow-up    → POST /api/agents/lead/followup
 *
 * Intent split happens inside handleLeads() based on keyword detection.
 */

// ---------------------------------------------------------------------------
// UUID regex — matches standard v4 UUID format
// Used to extract deal_id from the user's message in follow-up requests
// ---------------------------------------------------------------------------
const UUID_REGEX = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

// ---------------------------------------------------------------------------
// Simple lead field extraction helpers
// These are "good enough" for a chat-based UI — not a full NLP parser.
// The user's full message is always passed as the `message` field to the API,
// so the LangGraph agent sees everything even if extraction misses something.
// ---------------------------------------------------------------------------

/**
 * Extract company name: looks for "from [Company]", "at [Company]", or
 * "company: [Company]". Falls back to "unknown".
 */
function extractCompany(text) {
  const patterns = [
    /company[:\s]+([A-Z][^,.\n]{2,40})/i,
    /\bfrom\s+([A-Z][^,.\n]{2,40})/i,
    /\bat\s+([A-Z][^,.\n]{2,40})/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return match[1].trim();
  }
  return 'unknown';
}

/**
 * Extract contact email: standard email regex.
 */
function extractEmail(text) {
  const match = text.match(/[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/);
  return match ? match[0] : '';
}

/**
 * Extract contact name: looks for "contact: [Name]" or "name: [Name]".
 * Falls back to "unknown".
 */
function extractContactName(text) {
  const patterns = [
    /contact[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)/i,
    /name[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return match[1].trim();
  }
  return 'unknown';
}

// ---------------------------------------------------------------------------
// handleLeads — public entry point
// ---------------------------------------------------------------------------

/**
 * Route to classify or follow-up based on keyword detection.
 *
 * @param {string} userMessage - Raw message text from the user
 * @param {import('axios').AxiosInstance} nexusApi - Shared axios instance
 * @returns {Promise<string>} Formatted response string
 */
export async function handleLeads(userMessage, nexusApi) {
  const text = userMessage.toLowerCase();

  if (text.includes('followup') || text.includes('follow up') || text.includes('follow-up')) {
    return await handleFollowup(userMessage, nexusApi);
  }
  return await handleClassify(userMessage, nexusApi);
}

// ---------------------------------------------------------------------------
// handleClassify — Lead Classifier (POST /api/agents/lead/classify)
// ---------------------------------------------------------------------------

/**
 * Parse the user's message to extract lead fields, then call the classify endpoint.
 * The user's full message is always passed as the `message` field so the
 * LangGraph agent has the complete context regardless of what extraction found.
 *
 * Example user message:
 *   "Classify this lead: Company: Gulf Properties, contact: Ahmed Hassan,
 *    ahmed@gulf.ae, source: LinkedIn. Message: We need an AI CRM for 200 agents."
 *
 * @param {string} message - Raw message text
 * @param {import('axios').AxiosInstance} nexusApi
 * @returns {Promise<string>}
 */
async function handleClassify(message, nexusApi) {
  try {
    const payload = {
      company:       extractCompany(message),
      contact_name:  extractContactName(message),
      contact_email: extractEmail(message),
      source:        'telegram',   // channel is always known
      message:       message,      // full text — agent reads this for context
    };

    const response = await nexusApi.post('/api/agents/lead/classify', payload);
    const { stage, score, reasoning, run_id } = response.data;

    // Stage emoji map — visual cue without needing to read the word
    const stageEmoji = {
      hot_lead:     '🔥',
      nurture:      '🌱',
      proposal:     '📋',
      closed_won:   '🏆',
      closed_lost:  '❌',
      disqualified: '🚫',
      escalated:    '⚠️',
      new_lead:     '🆕',
    };
    const emoji = stageEmoji[stage] ?? '🎯';

    return [
      `${emoji} Lead classified as *${stage.toUpperCase()}* (score: ${score}/100)`,
      '',
      `Reasoning: ${reasoning}`,
      '',
      `Run ID: \`${run_id}\``,
    ].join('\n');

  } catch (err) {
    if (err.response?.status === 500) {
      return "Lead classifier failed. The LangGraph agent may be warming up — try again in 20 seconds.";
    }
    if (err.code === 'ECONNREFUSED' || err.code === 'ECONNABORTED') {
      return "Cannot reach the Nexus server. Is FastAPI running on port 8000?";
    }
    return `Lead classifier error: ${err.message}`;
  }
}

// ---------------------------------------------------------------------------
// handleFollowup — Follow-up Writer (POST /api/agents/lead/followup)
// ---------------------------------------------------------------------------

/**
 * Extract a deal UUID from the user's message, then call the follow-up endpoint.
 *
 * Example user messages:
 *   "followup for deal ae140801-dce7-4b8c-9a44-08df0408f195"
 *   "write a follow up for ae140801-dce7-4b8c-9a44-08df0408f195"
 *
 * @param {string} message - Raw message text
 * @param {import('axios').AxiosInstance} nexusApi
 * @returns {Promise<string>}
 */
async function handleFollowup(message, nexusApi) {
  // Extract deal_id UUID from the message
  const uuidMatch = message.match(UUID_REGEX);
  if (!uuidMatch) {
    return (
      "Please provide a deal ID (UUID format).\n" +
      "Example: `followup for deal ae140801-dce7-4b8c-9a44-08df0408f195`"
    );
  }
  const dealId = uuidMatch[0];

  try {
    const response = await nexusApi.post('/api/agents/lead/followup', { deal_id: dealId });
    const { draft, review_score, run_id } = response.data;

    return [
      `✉️ *Follow-up draft* (review score: ${review_score}/100)`,
      '',
      draft,
      '',
      `Run ID: \`${run_id}\``,
    ].join('\n');

  } catch (err) {
    if (err.response?.status === 404) {
      return `Deal not found: \`${dealId}\`. Check the deal ID and try again.`;
    }
    if (err.response?.status === 500) {
      return "Follow-up agent failed. The LangGraph agent may be warming up — try again in 20 seconds.";
    }
    if (err.code === 'ECONNREFUSED' || err.code === 'ECONNABORTED') {
      return "Cannot reach the Nexus server. Is FastAPI running on port 8000?";
    }
    return `Follow-up error: ${err.message}`;
  }
}