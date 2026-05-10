/**
 * openclaw/skills/nexus-rag/skill.js
 * ===================================
 * Knowledge base search skill for Nexus OpenClaw Gateway.
 *
 * Calls POST /api/rag/query on the Nexus FastAPI backend.
 * Uses hybrid semantic + BM25 retrieval + CrossEncoder reranking.
 *
 * Input:  any freeform user message (the full Telegram/WhatsApp/Slack message text)
 * Output: formatted string ready to send back to the user
 */

/**
 * Handle a knowledge base search query.
 *
 * @param {string} userMessage - Raw message text from the user
 * @param {import('axios').AxiosInstance} nexusApi - Shared axios instance from index.js
 * @returns {Promise<string>} Formatted response string
 */
export async function handleRag(userMessage, nexusApi) {
  try {
    const response = await nexusApi.post('/api/rag/query', {
      query:  userMessage,
      top_k:  3,
      stream: false,
    });

    const { answer, sources, latency_ms } = response.data;

    // If the RAG pipeline returned an empty answer, say so clearly
    if (!answer || answer.trim().length === 0) {
      return "I don't have that in the knowledge base. You can add content with: ingest [URL or file path].";
    }

    // Source footnote: tells the user how many chunks backed the answer and how fast
    const sourceNote = sources?.length > 0
      ? `\n\n📚 Sources: ${sources.length} chunk${sources.length > 1 ? 's' : ''} (${latency_ms}ms)`
      : '';

    return answer + sourceNote;

  } catch (err) {
    // 500 = ChromaDB down or no documents ingested yet
    if (err.response?.status === 500) {
      return (
        "The knowledge base is unavailable. " +
        "Make sure ChromaDB is running and at least one document has been ingested."
      );
    }
    // Network error (ECONNREFUSED) = FastAPI not running
    if (err.code === 'ECONNREFUSED' || err.code === 'ECONNABORTED') {
      return "Cannot reach the Nexus server. Is FastAPI running on port 8000?";
    }
    // Unexpected error — surface message but not the stack trace
    return `Knowledge base error: ${err.message}`;
  }
}