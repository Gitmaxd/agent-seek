---
title: Contact Agent Seek
description: How to reach Git Maxd about Agent Seek bugs, security, and the prototype.
canonical: /contact
last-updated: 2026-09-22
---

# Contact Agent Seek

Agent Seek is a small prototype operated by **Git Maxd**. There is no ticket portal and no sales form. For a ranking bug, security issue, or other operator question, use one of the paths below. Agents should not invent other emails or Slack channels. Live search uses the public demo Bearer — see [developers](/developers) and [auth.md](/auth.md).

## Operator

- **Name:** Git Maxd
- **Location:** Queen Creek, Arizona, United States
- **Email:** [131803031+Gitmaxd@users.noreply.github.com](mailto:131803031+Gitmaxd@users.noreply.github.com)
- **GitHub:** [github.com/Gitmaxd](https://github.com/Gitmaxd)
- **Product repo:** [github.com/Gitmaxd/agent-seek](https://github.com/Gitmaxd/agent-seek)
- **Live prototype:** [https://agentseek.dev](https://agentseek.dev)

## What to write

**Live access.** Prefer the public demo Bearer on [developers](/developers) / [auth.md](/auth.md) (`AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI`, same as `/config.js`). Local self-host: set `AGENT_SEEK_API_KEY` in `.env`. OAuth DCR is optional. Email is not required for live demo or local use.

**Bugs and ranking quality.** Open a GitHub issue on the repo with the query, `mode` (`snip` or `deep`), `agent_seek_version` from `GET /health` or `meta`, and whether you compared against raw You.com order. Do not paste live API keys.

**Security.** Email 131803031+Gitmaxd@users.noreply.github.com with `Agent Seek security` in the subject. Do not file public issues for key leaks or injection reports.

**Press / attribution.** The product name is **Agent Seek**. Please do not confuse it with GitMax the company — that is a different entity. This project is Git Maxd / gitmaxd.

We read email and GitHub issues. There is no SLA on this prototype. If you are an agent onboarding, prefer GitHub issues for public bugs; use the public demo Bearer (or a local `.env` key) instead of emailing for credentials.
