/**
 * openclaw/skills/nexus-pipeline/skill.js
 * =========================================
 * Pipeline KPI reporting skill for Nexus OpenClaw Gateway.
 *
 * Calls GET /api/agents/pipeline/report on the Nexus FastAPI backend.
 * That endpoint triggers the full LangGraph Pipeline Reporter (5 nodes):
 *   query_pipeline_data → compute_kpis → identify_bottlenecks → generate_digest → route_to_output
 *
 * The LLM digest is truncated to one paragraph for chat — full report is in the API response.
 *
 * Expected API response shape:
 *   {
 *     kpis: { conversion_rate, avg_deal_age, stage_distribution, total_pipeline_value },
 *     bottlenecks: string[],
 *     digest: string,
 *     run_id: string
 *   }
 *
 * Input:  any pipeline-related message (pipeline, kpi, report, conversion)
 * Output: formatted string ready to send back to the user
 */

/**
 * Handle a pipeline KPI report request.
 *
 * Pipeline reports call the full LangGraph reporter which makes one LLM call.
 * On Gemini free tier this can take 15–25 seconds — the caller (index.js) should
 * send an acknowledgement message to the user BEFORE calling this function.
 *
 * @param {string} userMessage - Raw message text from the user (unused — report is always full)
 * @param {import('axios').AxiosInstance} nexusApi - Shared axios instance from index.js
 * @returns {Promise<string>} Formatted response string
 */
export async function handlePipeline(userMessage, nexusApi) {
  try {
    // Pipeline reports are slow (LLM call inside the agent) — use a dedicated
    // 60-second timeout rather than the global 30s on nexusApi.
    // We create a one-off config override rather than mutating the shared instance.
    const response = await nexusApi.get('/api/agents/pipeline/report', {
      timeout: 60_000,
    });

    const { kpis, bottlenecks, digest, run_id } = response.data;

    // -----------------------------------------------------------------------
    // KPI headline — three numbers the user cares about most
    // toFixed(1) avoids floating-point noise; '?? 0' guards against null/undefined
    // -----------------------------------------------------------------------
    const convRate     = (kpis?.conversion_rate  ?? 0).toFixed(1);
    const avgAge       = (kpis?.avg_deal_age      ?? 0).toFixed(1);
    const pipelineVal  = (kpis?.total_pipeline_value ?? 0).toLocaleString('en-US', {
      maximumFractionDigits: 0,
    });

    const kpiLine = [
      `📊 Conversion: ${convRate}%`,
      `⏱ Avg deal age: ${avgAge} days`,
      `💰 Pipeline: $${pipelineVal}`,
    ].join(' · ');

    // -----------------------------------------------------------------------
    // Bottleneck list — max 3 items to keep the chat message short
    // Slack / WhatsApp both have practical message length limits
    // -----------------------------------------------------------------------
    const bottleneckBlock = (bottlenecks?.length > 0)
      ? '\n\n⚠️ *Bottlenecks:*\n' +
        bottlenecks.slice(0, 3).map(b => `• ${b}`).join('\n')
      : '\n\n✅ No bottlenecks detected';

    // -----------------------------------------------------------------------
    // Digest — first paragraph only
    // The LLM generates 3 paragraphs; showing only the first keeps it readable
    // in a chat context. Users can call the REST endpoint for the full digest.
    // Splitting on double-newline handles both \n\n and platform-specific breaks.
    // -----------------------------------------------------------------------
    const digestShort = (digest ?? '')
      .split(/\n\n/)
      .find(p => p.trim().length > 0)   // skip any leading blank paragraph
      ?? 'No digest available.';

    // -----------------------------------------------------------------------
    // Run ID — lets the user trace the agent run if needed
    // -----------------------------------------------------------------------
    const footer = run_id
      ? `\n\n_Run ID: \`${run_id}\`_`
      : '';

    return `${kpiLine}${bottleneckBlock}\n\n${digestShort}${footer}`;

  } catch (err) {
    // Axios timeout — pipeline LLM call exceeded 60s
    // Happens on Gemini free tier cold starts or very slow Ollama models
    if (err.code === 'ECONNABORTED' || err.code === 'ERR_CANCELED') {
      return (
        '⏳ Pipeline report timed out — the LLM is taking longer than usual.\n' +
        'Try again in 30 seconds, or switch to Ollama for faster responses.'
      );
    }

    // 500 = DB empty / reporter agent crashed
    if (err.response?.status === 500) {
      return (
        '⚠️ Pipeline report failed. ' +
        'The database may be empty or the reporter agent encountered an error.'
      );
    }

    // FastAPI not running
    if (err.code === 'ECONNREFUSED' || err.code === 'ECONNABORTED') {
      return "Cannot reach the Nexus server. Is FastAPI running on port 8000?";
    }

    // Unexpected error — surface message, not stack trace
    return `Pipeline error: ${err.message}`;
  }
}