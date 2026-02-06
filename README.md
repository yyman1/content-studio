# Content Studio

A multi-agent content pipeline built with Next.js and TypeScript. Three specialized agents — **Research**, **Writer**, and **Editor** — work in sequence to transform a topic into a polished, source-cited article.

## How It Works

```
Topic ─→ Research Agent ─→ Writer Agent ─→ Editor Agent ─→ Final Article
              │                  │                │
         Web search &       Composes a       Fixes grammar,
         fact extraction   ~300-word article  improves clarity,
         with sources      with citations     suggests headlines
```

1. **Research Agent** — Runs parallel web searches via DuckDuckGo, fetches top pages, and extracts 5-7 key facts with source attribution.
2. **Writer Agent** — Takes the research data and composes a structured article with inline `[n]` citations. Supports 4 tones: professional, casual, academic, journalistic.
3. **Editor Agent** — Applies grammar, clarity, and redundancy rules. Splits long paragraphs, generates catchy headline suggestions, and scores quality across 5 dimensions.

## Prerequisites

- **Node.js** 18.17 or later
- **npm** (included with Node.js)

## Quick Start

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd content-studio

# 2. Install dependencies
npm install

# 3. Copy the example env file (optional — the app works without it)
cp .env.example .env.local

# 4. Start the development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

Enter a topic, pick a tone, and click **Generate Content** to watch the pipeline run.

## Environment Variables

The app works **out of the box with no API keys**. The Research Agent uses DuckDuckGo for web search, and the Writer/Editor agents use rule-based text generation.

See [`.env.example`](.env.example) for all optional variables. Copy it to `.env.local` to customize:

```bash
cp .env.example .env.local
```

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_SEARCH_API_KEY` | No | Google Custom Search API key (alternative to DuckDuckGo) |
| `GOOGLE_SEARCH_ENGINE_ID` | No | Google Custom Search engine ID |
| `SERPAPI_KEY` | No | SerpAPI key (alternative to DuckDuckGo) |
| `OPENAI_API_KEY` | No | OpenAI key for future LLM-powered writing/editing |
| `ANTHROPIC_API_KEY` | No | Anthropic key for future LLM-powered writing/editing |
| `NEXT_PUBLIC_BASE_URL` | No | Override the base URL (auto-detected in most deployments) |

## Project Structure

```
src/
├── agents/                    # Agent system core
│   ├── types.ts               # All TypeScript interfaces
│   ├── base-agent.ts          # Abstract base class for agents
│   ├── agent-registry.ts      # Agent registry & pipeline runner
│   ├── research-agent.ts      # Web search + fact extraction
│   ├── writer-agent.ts        # Article composition with citations
│   ├── editor-agent.ts        # Grammar, clarity, headlines, scoring
│   └── index.ts               # Barrel exports
├── lib/                       # Shared utilities
│   ├── message-bus.ts         # Pub/sub message bus for inter-agent communication
│   ├── web-search.ts          # DuckDuckGo search + page content fetcher
│   ├── fact-extractor.ts      # Sentence scoring & deduplication
│   ├── article-composer.ts    # Tone-aware article generation with 4 template kits
│   └── article-editor.ts     # Grammar/clarity/redundancy rules + quality scoring
└── app/
    ├── page.tsx               # Main UI with animated pipeline visualization
    ├── layout.tsx             # Root layout with Geist font
    ├── globals.css            # Tailwind + custom animations
    └── api/
        ├── orchestrate/route.ts   # Main pipeline endpoint (recommended)
        ├── agents/route.ts        # Legacy pipeline via message bus
        ├── agents/research/route.ts
        ├── agents/writer/route.ts
        └── agents/editor/route.ts
```

## API Endpoints

### `POST /api/orchestrate` (recommended)

Runs the full pipeline with typed handoffs, per-step timing, and graceful error handling.

```bash
curl -X POST http://localhost:3000/api/orchestrate \
  -H 'Content-Type: application/json' \
  -d '{"topic": "renewable energy", "tone": "journalistic"}'
```

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `topic` | string | Yes | The subject to research and write about |
| `tone` | string | No | `professional` (default), `casual`, `academic`, or `journalistic` |

**Response:** Returns `status` (`completed`, `partial`, or `failed`), per-step timing, and full typed output from each agent. See `GET /api/orchestrate` for the full schema.

### Individual Agent Endpoints

Each agent also has a standalone endpoint. Send `GET` to any of them for a self-documenting schema.

| Endpoint | Method | Description |
|---|---|---|
| `/api/agents/research` | POST | Run the research agent. Body: `{ topic }` |
| `/api/agents/writer` | POST | Run the writer agent. Body: `{ topic, facts, sources, tone? }` |
| `/api/agents/editor` | POST | Run the editor agent. Body: `{ title, article, topic, tone?, citations? }` |

You can pipe the output of one agent into the next:

```bash
# Research → Writer → Editor (manual pipeline)
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"topic":"AI"}' http://localhost:3000/api/agents/research \
  | curl -s -X POST -H 'Content-Type: application/json' \
    -d @- http://localhost:3000/api/agents/writer \
  | curl -s -X POST -H 'Content-Type: application/json' \
    -d @- http://localhost:3000/api/agents/editor
```

## Available Scripts

| Command | Description |
|---|---|
| `npm run dev` | Start the development server on port 3000 |
| `npm run build` | Create an optimized production build |
| `npm start` | Start the production server |
| `npm run lint` | Run ESLint |

## Deploying

### Vercel (recommended)

1. Push your code to a Git repository (GitHub, GitLab, Bitbucket).
2. Go to [vercel.com/new](https://vercel.com/new) and import the repository.
3. Add any optional environment variables in the Vercel dashboard under **Settings > Environment Variables**.
4. Click **Deploy**. Vercel auto-detects Next.js and handles everything.

Subsequent pushes to your main branch will trigger automatic deployments.

### Docker

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

> Note: To use the standalone output mode, add `output: "standalone"` to your `next.config.ts`.

```bash
docker build -t content-studio .
docker run -p 3000:3000 content-studio
```

### Self-hosted (Node.js)

```bash
npm run build
npm start
```

The server starts on port 3000 by default. Set `PORT` to change it:

```bash
PORT=8080 npm start
```

## Architecture

The agent system is built on two patterns:

- **Message Bus** (`src/lib/message-bus.ts`) — A pub/sub system where agents subscribe by ID. Supports direct messages and broadcasts. Used by the legacy `/api/agents` pipeline.
- **Direct Invocation** (`/api/orchestrate`) — Calls each agent's public method directly with typed inputs/outputs. Gives proper error boundaries per step and returns partial results if a step fails.

Each agent extends `BaseAgent`, which provides:
- Automatic message bus subscription
- Status tracking (idle / processing / error)
- Message creation with correlation IDs
- A `sendTo()` method for inter-agent communication

## Tech Stack

- **Framework:** Next.js 16 (App Router)
- **Language:** TypeScript
- **Styling:** Tailwind CSS v4
- **HTML Parsing:** cheerio
- **Web Search:** DuckDuckGo HTML (no API key)
- **Fonts:** Geist Sans & Geist Mono
