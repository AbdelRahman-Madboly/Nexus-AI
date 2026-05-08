# nexus-pipeline

## Description
Generate pipeline reports, KPI summaries, and bottleneck analysis from the Nexus CRM.

## When to use this skill
- "Give me the pipeline report"
- "What are our KPIs this week?"
- "Where are we losing deals?"
- "Pipeline summary"

## How to use
```
GET {OPENCLAW_NEXUS_API_URL}/api/agents/pipeline/report
```

## Response format
Return a concise summary:
"Pipeline: [X] hot, [Y] nurture, [Z] in proposal. Conversion: [%]%. Avg deal age: [N] days. Bottleneck: [stage]."

If user wants details, provide the full KPI breakdown.
