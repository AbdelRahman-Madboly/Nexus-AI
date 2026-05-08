# MEMORY.md — Nexus Business Assistant

## Company Context
- Company: [YOUR COMPANY NAME]
- Industry: [YOUR INDUSTRY]
- CRM pipeline stages: new_lead → hot_lead → nurture → proposal → closed_won / closed_lost / disqualified / escalated

## Pipeline Stage Definitions
- **hot_lead**: Score ≥ 80, high intent, fast follow-up needed (< 24 hours)
- **nurture**: Score 50–79, interested but not ready, weekly check-in
- **proposal**: Active deal, proposal sent, follow up within 48 hours
- **escalated**: Requires human manager attention immediately

## User Preferences
- Prefer short responses in messaging
- Always include deal count in pipeline summaries
- Flag any deal older than 14 days without contact

## Nexus API
- Base URL: http://nexus-api:8000
- All skills call this API to get live data
