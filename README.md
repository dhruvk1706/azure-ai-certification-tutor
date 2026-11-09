# Azure AI Certification Tutor

An open-source tutor for Azure AI certification exams.

**Status:** feature-complete for local use, not deployed anywhere. The AI-103 syllabus can be ingested from the command line, and learners get a syllabus-grounded tutor, generated lessons, a personalized learning path, a progress dashboard, practice quizzes and timed mock exams with performance analytics, and an Azure sandbox simulator with automatically graded guided labs.

Practice questions are written by AI and checked against Microsoft Learn text. They are not official Microsoft certification questions, and practice scores do not predict an exam result.

This is an independent project, not affiliated with or endorsed by Microsoft.

## Stack

| Area           | Technology                                    |
| -------------- | --------------------------------------------- |
| Frontend       | React, TypeScript, Vite, Tailwind CSS         |
| Backend        | Python, FastAPI                               |
| Database       | PostgreSQL with pgvector                      |
| AI             | Any OpenAI-compatible endpoint, Ollama optional |
| Infrastructure | Docker Compose (local development)            |

See [docs/architecture.md](docs/architecture.md) for how the pieces fit together.

## Repository layout

```
backend/         FastAPI service
frontend/        React app
infrastructure/  Docker Compose and database setup
docs/            Project documentation
tests/           Backend and frontend tests
```

## Getting started

Requires Docker, or for host development Node.js 24+ and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
```

### With Docker

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml up --build -d
```

This starts the database, backend and frontend together in the background. Stop any backend running on the host first, because both use port 8000. Follow the logs with `docker compose --env-file .env -f infrastructure/docker-compose.yml logs -f`.

- Frontend: http://localhost:5173
- Backend: http://localhost:8000/health

The app needs its tables and a syllabus before it can do anything. On first run, with the containers up:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backend .venv/bin/alembic upgrade head
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backend .venv/bin/python -m app.syllabus.ingest
```

Then open http://localhost:5173. Later runs only need `up` (add `-d` to run in the background). If the dashboard sits on "Loading…" forever, the database container isn't running, so check `docker compose ... ps`. Learning state lives in the `db-data` volume, so it survives restarts and rebuilds. `docker compose ... down -v` deletes that volume and everything in it.

`backend/app` and `frontend/src` are mounted into the containers, and both dev servers reload when they change. They poll for changes, because file events don't reach containers through Docker Desktop's bind mounts. Anything else, such as dependencies or `frontend/index.html`, needs `up --build`.

To also run Ollama, add `--profile ollama` before `up`, then pull a model:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml exec ollama ollama pull <model>
```

### On the host

The backend still needs Postgres. Start only the database container first, then run the migrations and ingest from `backend/` with `uv run --env-file ../.env`:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d db
```

```bash
cd frontend
npm install
npm run dev -w frontend
```

```bash
cd backend
uv sync
uv run --env-file ../.env alembic upgrade head
uv run --env-file ../.env uvicorn app.main:app --reload
```

## LLM configuration

No provider is built in. Set these in `.env` to connect any service with an OpenAI-compatible API:

| Connecting to                        | `LLM_BASE_URL`                                   | `LLM_API_KEY`                | `LLM_MODEL`           |
| ------------------------------------ | ------------------------------------------------ | ---------------------------- | --------------------- |
| OpenAI                               | `https://api.openai.com/v1`                      | Your API key                 | Model name            |
| Azure OpenAI                         | `https://<resource>.openai.azure.com/openai/v1/` | Your resource key            | Your deployment name  |
| Other compatible provider            | The provider's OpenAI-compatible URL             | Your provider key            | The provider's model name |
| Ollama, `ollama` Compose profile     | `http://ollama:11434/v1`                         | Any non-empty value          | A model you pulled    |
| Ollama on the host, backend in Docker | `http://host.docker.internal:11434/v1`          | Any non-empty value          | A model you pulled    |
| Ollama and backend both on the host  | `http://localhost:11434/v1`                      | Any non-empty value          | A model you pulled    |

Requests wait up to `LLM_TIMEOUT_SECONDS` (default 120), which a local model on a CPU may need. The tutor, lesson generation, plan narration and lab assistant are limited to 60 model requests per learner and 300 in total per hour (`LLM_LEARNER_HOURLY_LIMIT`, `LLM_HOURLY_LIMIT`; 0 turns them off). Opening a lesson that was already generated doesn't count. These counts are kept in memory, so restarting the backend resets them. Question generation has its own limits (see [Question bank sources](#question-bank-sources)). If the model is missing, unreachable or returns something unusable, the page shows an error you can retry and nothing is stored. Plans, progress and the dashboard never need the model, so they keep working without one.

Ollama ignores the key, but the client requires one. On Linux, an Ollama install on the host must listen beyond `127.0.0.1` (`OLLAMA_HOST=0.0.0.0`) for the backend container to reach it.

The `EMBEDDING_*` settings are reserved for later and nothing reads them yet: syllabus retrieval is lexical (see [docs/architecture.md](docs/architecture.md)).

## Syllabus ingestion

Ingestion is a command-line job, separate from the API. New dependencies mean the backend image must be rebuilt first (`up --build`). Then apply migrations and ingest:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backend .venv/bin/alembic upgrade head
```

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backend .venv/bin/python -m app.syllabus.ingest
```

Running it again is safe: unchanged content only updates `last_checked_at`, changed content adds a new version and its list of changes, and any failure exits non-zero with existing data untouched. Add `--dry-run` to fetch and parse the live page without touching the database.

## Question bank sources

Questions can only be generated for objectives that have a Microsoft Learn page attached, because every question must quote the page that proves its answer. List objective ids, then attach pages:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backend .venv/bin/python -m app.assessment.sources list
```

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backend .venv/bin/python -m app.assessment.sources add --subskill 3 https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview
```

Only `https://learn.microsoft.com` pages are accepted. Repeat `--subskill` to attach one page to several objectives. Running it again re-fetches the page; changed text is stored as a new copy and used from then on. Then generate questions per objective on the Practice page. Each request makes three model calls (writing, then two checks), up to six with retries, so requests are limited per hour: 10 per learner and 60 in total by default, set with `QUESTION_GENERATION_LEARNER_HOURLY_LIMIT` and `QUESTION_GENERATION_HOURLY_LIMIT` (0 turns generation off). An objective stops taking new questions at 40.

## Using the app

| Page          | What it does |
| ------------- | ------------ |
| Dashboard     | Overall and per-domain completion, weak areas, and the next recommended lesson |
| Learning path | Enter weekly study time, an exam date and how familiar you are with each skill, and get a week-by-week plan |
| Lessons       | Generate or reopen a lesson for a domain, skill or objective at beginner, intermediate or advanced depth, answer its comprehension check and mark it complete |
| Tutor         | Ask questions and follow-ups in conversations that persist, with the syllabus objectives behind each answer shown separately from the model's explanation |
| Practice & exams | Generate verified questions per objective, take topic or adaptive practice quizzes with immediate feedback, or timed mock exams that save as you go and submit themselves when time runs out |
| Performance   | Accuracy by domain and skill, strengths and weaknesses, a readiness estimate, attempt history and what to practise next |
| Azure sandbox | A simulated, portal-style environment for creating and configuring Foundry, model deployment, content filter, Azure AI Search, agent, Document Intelligence, networking and identity resources, with seven guided labs that are graded from your simulated resources, progressive hints and an AI lab assistant |

The sandbox is a simulation. It needs no Azure subscription, creates no real resources and costs nothing. It follows Microsoft Learn documentation but simplifies it, and each resource type and lab lists how it differs from Azure. It is inspired by the Azure portal and is not affiliated with or endorsed by Microsoft. Grading is deterministic; the lab assistant only explains, and needs the same LLM configuration as the tutor.

Each browser gets its own anonymous learner, held as a token in `localStorage`. There are no accounts, so clearing site data or changing browser means starting again as a new learner.

Progress belongs to the syllabus version it was made on. Ingesting a new version moves nobody: the app offers it, and creating a plan on it starts that version's progress from zero while earlier records stay intact.

The API is documented at http://localhost:8000/docs while the backend runs.

The header's Theme menu switches between light, dark and the system setting, and remembers the choice in this browser. On narrow screens the navigation folds into a Menu button.

## Troubleshooting

| Symptom | Cause and fix |
| ------- | ------------- |
| "The database is unavailable, or migrations have not been applied." | Run `alembic upgrade head` (see [Syllabus ingestion](#syllabus-ingestion)). With Docker, check `docker compose ... ps` shows `db` as healthy. |
| "No syllabus has been ingested yet" | Run `python -m app.syllabus.ingest`. |
| "The AI model is not configured" | Set `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` in `.env`, then restart the backend (`docker compose ... up -d backend`). Compose reads `.env` only when a container is created. |
| "The AI model could not be reached or returned an error" | The endpoint, key or model name is wrong, or the provider is down or rate limiting you. The backend log has the provider's error. Nothing is stored, so retrying is safe. |
| "You can use the AI model N times an hour" or "hourly limit" | The limits above. Wait, raise them in `.env`, or restart the backend. |
| Practice says no questions are available | Attach a Learn page to the objective and generate questions first (see [Question bank sources](#question-bank-sources)). A mock exam needs at least as many questions as it asks for. |
| "Could not reach the API" in the browser | The backend isn't running, or `VITE_API_URL` doesn't match where it listens. The API only accepts browser requests from `localhost` and `127.0.0.1` origins. |
| Your progress disappeared | Progress is tied to the learner token in this browser's storage. Clearing site data, a private window or another browser starts a new learner. |
| Changes to `pyproject.toml`, `package.json` or `frontend/index.html` don't show in Docker | Only `backend/app` and `frontend/src` are mounted into the containers. Rebuild with `up --build`. |
| Tests take minutes on Windows against Postgres | Use `127.0.0.1` rather than `localhost` in `TEST_DATABASE_URL`. |

## Checks

GitHub Actions (`.github/workflows/ci.yml`) runs all of these on every push to `main` and every pull request, with the backend tests on Postgres, and also builds the Docker images.

```bash
npm run check -w frontend
```

```bash
cd backend
uv run ruff check . ../tests/backend
uv run ruff format --check . ../tests/backend
uv run mypy
uv run pytest
```

`pytest` uses a temporary SQLite database. To run the same tests through the real migration on Postgres, set `TEST_DATABASE_URL` to a disposable database whose name ends in `_test`. Its tables are dropped afterwards. `DATABASE_URL` is never used by the tests. On Windows, write `127.0.0.1` rather than `localhost` in that URL, because each connection otherwise waits on IPv6 first and the run takes many times longer.

## License

[Apache License 2.0](LICENSE)
