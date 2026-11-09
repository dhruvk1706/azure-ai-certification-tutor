# Security

## Local use only

This project is built to run on your own machine. Docker Compose publishes every port on
`127.0.0.1` only, and the backend is not hardened for the internet: learners are anonymous
tokens anyone can create, model rate limits are kept in memory, and request bodies have no
size limit. Don't expose the backend, frontend or database publicly as they are.

Deploying it would need at least real authentication, rate limiting on `POST /api/learners`,
request size limits, CORS origins for your own domain, a production frontend build instead of
the Vite dev server, and containers that don't run as root.

Keep LLM keys in `.env` only. It is gitignored; never commit it.

## Reporting a vulnerability

Report it privately through the repository's **Security** tab, under **Report a
vulnerability**. Please don't open a public issue.
