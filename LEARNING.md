# repair-agent: Learning Log

## How to read this log

There is one entry per commit, in order, and each covers what changed, why, and the decisions behind it. The Project map always shows the current layout, and the Glossary at the bottom defines project-specific terms.

> "repair-agent" is a placeholder name.

## Project map

```
sandbox/
├── .gitignore    <- files git must never track (secrets, caches, run output)
├── CLAUDE.md     <- standing instructions for Claude Code
├── LEARNING.md   <- this log
└── README.md     <- one-line project description
```

There is no code yet.

## Entries

### Commit 0.1: Project scaffolding
- **Date:** 2026-10-01
- **What:** Added a Python `.gitignore` and set the README to a one-line description. `CLAUDE.md` (assistant rules) and `LEARNING.md` (this log) were created but kept local by gitignoring them.
- **Why it exists:** It keeps secrets and generated files out of the repo before any code exists.
- **How it works:** `.gitignore` ignores `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.env`, `runs/`, `.DS_Store`, `CLAUDE.md` and `LEARNING.md`.
- **Key concepts:** `.env` will hold the Anthropic API key, so it's ignored *before* it exists. `.gitignore` only affects untracked files, so a file that's already committed needs `git rm --cached`.
- **Design decisions:**
  - I wrote a small `.gitignore` instead of GitHub's ~150-line template, so every line is explainable.
  - The personal files are gitignored rather than just left unstaged, so a careless `git add .` can't publish them. The cost is no backup.
- **How to verify:** `git check-ignore -v .env CLAUDE.md LEARNING.md` prints the matching rule for each file.
- **Interview questions:**
  1. *You leaked an API key in a pushed commit. What do you do?* Revoke or rotate it at the provider first. Then gitignore the file, run `git rm --cached` on it, and commit. The old commit still contains the key.
  2. *Why not commit `.venv/`?* It's large and machine-specific. It gets rebuilt from `pyproject.toml`.
- **Files changed:** `.gitignore` (new), `README.md` (replaced)

### Topic 1: Model access plan (Groq for development, Anthropic for measurement)
- **Date:** 2026-10-01

- **What was built:** Only the decision, written into `CLAUDE.md`; there's no code yet. The agent will talk to LLMs through **one small provider interface** with two implementations: an OpenAI-compatible provider (used for Groq's free API) and an Anthropic provider. Day-to-day development and debugging runs on Groq for free. Every number we report (baseline, experiments, held-out results) comes from the Anthropic model with identical settings. `.env` holds `GROQ_API_KEY` and `ANTHROPIC_API_KEY`, and `.env` was already gitignored.

- **Why it exists:** The agent loop will make many model calls while we develop: each run is many steps, and we'll run broken tasks over and over. Paying for all of that during debugging is wasteful, so Groq's free tier covers development. But the eval suite is only meaningful if every measured number comes from the same model under the same settings. Hence the split: Groq while building, Anthropic for anything we report.

- **How it works (the plan for later commits):**
  1. **Config:** `.env` sets `PROVIDER=groq` or `PROVIDER=anthropic`, a model name for each provider, and the two API keys. The program reads these at startup.
  2. **Provider interface:** our own small class or protocol, roughly "send these messages and tools, get back a reply plus token counts". The agent loop only knows this interface and our internal message format.
  3. **OpenAI-compatible provider:** uses the `openai` Python SDK with `base_url` set to Groq's endpoint and `api_key=GROQ_API_KEY`. Pointing it at OpenRouter or a local Ollama later only means changing the URL, key and model.
  4. **Anthropic provider:** uses the `anthropic` SDK with `ANTHROPIC_API_KEY`. It's a separate implementation because Anthropic's API has a different shape and supports **prompt caching**, which reuses the long, repeated start of each request (system prompt, tool definitions) more cheaply.
  5. **Rate limits:** if Groq answers HTTP 429, the provider waits and retries, waiting longer after each failure (backoff), and gives up after a cap.
  6. **Accounting:** every call records input and output tokens. Cost = tokens × the per-model price from a config price table (Groq = 0). Every run's trace records the provider and the exact model name.

- **Key concepts:**
  - **API key:** a secret string sent with each HTTP request so the provider knows *who* is calling and whom to bill. *Analogy:* a hotel key card: it opens the door, and whoever holds it is treated as you. In our program the key is used in exactly one place: the host-side provider object reads it from `.env` and passes it to the SDK client, which puts it in the request header (`Authorization: Bearer ...` for Groq/OpenAI, `x-api-key` for Anthropic). Nothing else touches it.
  - **OpenAI-compatible API:** OpenAI's chat API (`POST /v1/chat/completions`, with JSON fields like `model`, `messages` and `tools`) became a de facto standard. Groq, OpenRouter, Ollama and others accept *the same request shape* at their own URL. So one client, the `openai` SDK, can talk to all of them by changing `base_url`, `api_key` and `model`. *Analogy:* a standard power plug: different power companies, same socket. Anthropic's API uses a different shape, so it needs its own provider.
  - **Provider interface (adapter pattern):** our code defines what it needs from "a model", and each provider class translates that into one vendor's SDK. *Analogy:* a travel adapter: your laptop has one plug, and the adapter deals with each country's socket.
  - **Rate limit / HTTP 429:** providers cap how many requests or tokens you can use per minute or day, and free tiers are strict. Going over gets the HTTP status **429 Too Many Requests**, often with a `retry-after` header saying how long to wait. *Analogy:* a coffee shop that serves only so many orders per minute and asks you to come back shortly.
  - **Exponential backoff:** after each failed try, wait longer (e.g. 1s, 2s, 4s, 8s, plus a little randomness called *jitter*) before retrying, up to a maximum number of tries. Retrying instantly would just hit the limit again.
  - **Tokens:** the chunks of text models read and write, and the unit providers count usage and bill by. Input tokens (what we send) and output tokens (what the model writes) are priced differently.
  - **Prompt caching:** Anthropic can store the processed beginning of a prompt and reuse it on later calls that start the same way. In an agent loop the system prompt and tool definitions repeat every step, so caching cuts cost and latency.
  - **Confounding variable:** something other than the thing you're testing that also changes between runs. If it changes, you can't tell which change caused the difference in results.

- **Design decisions:**
  - **Our own interface rather than calling SDKs throughout the code.** *Alternatives:* (a) call the Anthropic SDK everywhere, which ties us to one vendor and makes free development impossible; (b) a third-party wrapper like LiteLLM, which is quicker to start but adds a dependency and hides the details I need to understand and explain. *Reasoning:* the interface is small, we control the message format, swapping providers is a config change, and tests can use a fake provider without any network.
  - **The OpenAI SDK for Groq rather than Groq's own SDK.** *Reasoning:* the same code also covers OpenRouter and Ollama.
  - **A separate Anthropic provider rather than Anthropic through the OpenAI-compatible route.** *Reasoning:* we need the native API for prompt caching and full control over its features.
  - **Groq for development, Anthropic for measurement.** *Alternatives:* everything on Anthropic, which costs money while debugging, or everything on Groq, which is free but rate-limited and not the model we want to report. *Reasoning:* free iteration and clean measurement. The cost: behaviour on Groq may differ from Anthropic, so a prompt that works on Groq still has to be re-checked on Anthropic.
  - **Why mixing providers ruins a comparison:** the eval asks whether change X improves pass rate, steps or cost. If run A used Groq's model and run B used Anthropic's, the model changed as well as X. Different models differ in skill, tokenizers (so token counts aren't comparable), prices (Groq's cost is 0), tool-calling behaviour and rate limits. Any difference could come from the model rather than X, which makes the comparison meaningless. So every reported comparison uses the same provider, exact model name and settings, and the trace records them so this can be checked.
  - **Keys never enter the Docker container.** The container runs code the LLM wrote or edited, which is untrusted: it could `print(os.environ)`, read files, or send data over the network. The model calls happen in our host-side Python process, and the container only ever receives commands to run in its workspace. We don't pass `.env`, host environment variables or host folders in, so even fully malicious code inside has nothing to steal. *Analogy:* you let a contractor into the workshop, not into the room where your wallet is.

- **How to verify:**
  - `git check-ignore -v .env` should print `.gitignore:12:.env	.env`.
  - Read `CLAUDE.md`: the Tech choices section names the provider interface, `PROVIDER` config, 429 handling and token/cost tracking, and there's a "Measurement rule" section.
  - (Later, once the code exists, we'll verify with a fake-provider unit test and a real call on each provider.)

- **Interview questions:**
  1. *Why did you put an interface between your agent and the LLM SDKs?*
     **A:** So the agent loop depends on one small contract and our own message format, not on a vendor. Switching between Groq and Anthropic is a config change, adding OpenRouter or Ollama is trivial, and tests can use a fake provider without the network or keys.
  2. *What does "OpenAI-compatible" mean, and why does Anthropic still need its own provider?*
     **A:** The provider accepts the same HTTP request and response format as OpenAI's chat completions API, so the OpenAI SDK works with a different `base_url`. Anthropic's native API has a different format, and we want its prompt caching, so it gets its own implementation.
  3. *How do you handle a 429 from Groq?*
     **A:** Catch it, wait (honouring `retry-after` if present, otherwise exponential backoff with jitter), retry, and give up after a maximum number of attempts with a clear error. The waiting and retries are logged, so slow runs can be explained.
  4. *You develop on Groq but report Anthropic numbers. Why not report both together?*
     **A:** They're different models with different abilities, tokenizers and prices, so comparing them would mix up the model change with whatever we're testing. Reported results come from one fixed model and settings, and each run records the provider and exact model.
  5. *Where does the API key live, and why can't the sandboxed code see it?*
     **A:** In `.env` on the host (gitignored), read by the host-side provider only. The container runs untrusted, model-written code, so we never pass it `.env`, host env vars or host folders. There's nothing secret inside for it to leak.

- **Commits / files changed:** `CLAUDE.md` (tech choices, measurement rule, keys in rule 7). `.gitignore` unchanged (it already ignores `.env`).

## Glossary

- **.env:** a local file of `NAME=value` secrets (e.g. API keys). It is never committed.
- **API key:** secret string that identifies and bills the caller of an API.
- **CLAUDE.md:** instructions Claude Code loads automatically at the start of each session.
- **Confounding variable:** something besides the thing under test that also changes between runs, so you can't tell which caused the result.
- **Exponential backoff:** retrying after waits that double each time (plus jitter), up to a cap.
- **HTTP 429:** "Too Many Requests": you hit a rate limit, so wait and retry.
- **OpenAI-compatible API:** an API that accepts OpenAI's chat-completions request format at its own URL (Groq, OpenRouter, Ollama).
- **Prompt caching:** reusing the processed, repeated start of a prompt across calls to save cost and time (Anthropic).
- **Provider interface:** our own small abstraction over LLM APIs, so the rest of the code never imports a vendor SDK.
- **Rate limit:** a provider's cap on requests or tokens per time window.
- **Token:** the unit of text models read and write, and the unit providers bill by.
