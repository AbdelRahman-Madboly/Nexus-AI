# nexus-rag

## Description
Search the Nexus knowledge base and answer questions with cited sources.
Use when the user asks a business question that requires looking up company documents,
policies, product information, or any content that has been ingested into Nexus.

## When to use this skill
- Questions starting with "What is...", "How does...", "Tell me about..."
- Questions about company products, processes, or decisions
- Any question that requires document retrieval

## How to use
Make a POST request to the Nexus RAG API:
```
POST {OPENCLAW_NEXUS_API_URL}/api/rag/query
Content-Type: application/json

{"query": "<user question>", "top_k": 3}
```

## Response format
Return the answer with source citations. Format as:
"[Answer text] (Source: [document name], [page/section])"
