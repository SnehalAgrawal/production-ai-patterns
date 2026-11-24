# production-ai-patterns

Runnable demos of what it takes to run AI features in production: checks, retries, state, and failure handling. They accompany the AI engineering series on [snehalagrawal.com](https://snehalagrawal.com/articles/). Each demo is self-contained and runs locally, with no API keys or paid services. Demos that call a model use [Ollama](https://ollama.com), and each demo's README says what it needs.

| Demo | Article | What it shows |
|---|---|---|
| [01-reliable-llm-pipeline](01-reliable-llm-pipeline/) | [Building Reliable LLM Pipelines](https://snehalagrawal.com/articles/building-reliable-llm-pipelines/) | A four-step pipeline for customer emails: how errors compound across steps, what checks between steps catch and miss, what retries fix, and what a crash costs with and without saved state |
| [02-evaluation-regression](02-evaluation-regression/) | [LLM Evaluation: From Manual Testing to Automated Evaluation](https://snehalagrawal.com/articles/llm-evaluation-from-manual-testing-to-automated-evaluation/) | 01's labelled replies turned into a repeatable evaluation: a fact check measured against blind labels in both directions, two versions compared email by email with a sign test, and a one-sentence "friendlier" prompt change that the fact check scored as an improvement while three correct answers went wrong. Frozen protocols; Part A needs no model |
| [03-latency-breakdown](03-latency-breakdown/) | [Latency in AI Applications: Where Does the Time Actually Go?](https://snehalagrawal.com/articles/latency-in-ai-applications-where-does-the-time-actually-go/) | One request timed at every boundary across three processes, with simulated dependencies: why span durations don't add up to the wait, which number a faster model, parallel lookups, or streaming moves, where waiting for a worker hides, and what percentiles say about a rare slow dependency. Python only, no model |
| [04-cost-quality](04-cost-quality/) | Reducing LLM Costs Without Destroying Quality (link added when it's published) | The support assistant from 01 made cheaper four ways on the same 20 emails: half the retrieval budget, an output cap, a smaller drafting model, and a cascade gated by 01's check. Tokens and calls measured, replies labelled blind, spend priced hypothetically from dated published rates, and a break-even cost per failed email for each. Frozen protocol; the report needs no model |

## Linting

The repository has one lint setup for every demo: [Ruff](https://docs.astral.sh/ruff/) for Python and [ESLint](https://eslint.org/) for JavaScript.

```bash
npm install                              # ESLint (repository root)
pip install -r requirements-dev.txt      # Ruff
npm run lint                             # both
```

## Conventions

- Every demo has a README with the exact setup that produced the numbers in its article.
- Generated files (`runs/`, `data/tokenizer.json`) and `.env` files are not committed.
