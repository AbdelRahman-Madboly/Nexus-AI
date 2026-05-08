# nexus-leads

## Description
Classify leads, draft follow-up emails, and get deal status from the Nexus CRM.

## When to use this skill
- "Classify this lead: [details]"
- "Draft a follow-up for deal [ID]"
- "What is the status of [company name]?"
- "How many leads do we have?"

## How to use

Classify a lead:
```
POST {OPENCLAW_NEXUS_API_URL}/api/agents/lead/classify
{"company": "...", "contact": "...", "message": "...", "source": "..."}
```

Draft follow-up:
```
POST {OPENCLAW_NEXUS_API_URL}/api/agents/lead/followup
{"deal_id": "..."}
```

Query leads:
```
GET {OPENCLAW_NEXUS_API_URL}/api/agents/pipeline/report
```

## Response format
For classification: "Lead classified as [stage] (score: [0-100]). Reason: [brief reason]"
For email drafts: Show the draft and ask for approval before sending
