// The model calls, all to a local Ollama server. Same behaviour as ../python/llm.py.
//   embed()   turns text into vectors (nomic-embed-text by default)
//   chat()    one chat call whose output is constrained to a JSON schema (llama3.2:3b by default)
//   unload()  frees a model's memory after a run
import "dotenv/config";

export const chatModel = () => process.env.OLLAMA_CHAT_MODEL || "llama3.2:3b";
export const embeddingModel = () => process.env.OLLAMA_EMBEDDING_MODEL || "nomic-embed-text";
export const baseUrl = () => process.env.OLLAMA_BASE_URL || "http://localhost:11434";

async function post(path, body, seconds) {
  const response = await fetch(`${baseUrl()}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    signal: AbortSignal.timeout(seconds * 1000),
  });
  if (!response.ok) throw new Error(`${path} failed: HTTP ${response.status}`);
  return response.json();
}

export async function embed(texts) {
  const data = await post("/api/embed", { model: embeddingModel(), input: texts, truncate: false }, 300);
  return data.embeddings;
}

// The raw output text and the call's token counts. The caller parses and checks the output.
export async function chat(messages, { schema, options, maxTokens }) {
  const started = performance.now();
  const data = await post("/api/chat", {
    model: chatModel(), messages, stream: false, format: schema, options: { ...options, num_predict: maxTokens },
  }, 600);
  if (data.prompt_eval_count + maxTokens > options.num_ctx) {
    // Ollama would have cut the prompt to fit the context window without saying so.
    throw new Error(`prompt of ${data.prompt_eval_count} tokens is too long for num_ctx ${options.num_ctx}`);
  }
  return {
    content: data.message.content, prompt_tokens: data.prompt_eval_count, output_tokens: data.eval_count,
    done_reason: data.done_reason, seconds: Math.round((performance.now() - started) / 10) / 100,
  };
}

export async function unload(model) {
  await post("/api/generate", { model, keep_alive: 0 }, 60);
}
