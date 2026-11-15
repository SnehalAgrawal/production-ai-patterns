// Retrieval for the pipeline. Same behaviour as ../python/retrieval.py: the documents are chunked and
// embedded once, and each question gets the chunks ranked by RRF of vector and BM25, filled into its budget.
import * as chunkers from "./chunkers.js";
import * as llm from "./llm.js";
import * as search from "./search.js";

export class Index {
  async init(settings, documents, tokenizer) {
    this.settings = settings;
    this.chunks = chunkers.chunk(settings.chunking, documents, tokenizer);
    const texts = this.chunks.map((c) => c.text);
    this.vectors = await this.embed(texts.map((t) => settings.embedding.document_prefix + t));
    const { bm25 } = settings.retrieval;
    this.bm25 = new search.BM25(texts, bm25.analyzer, bm25.k1, bm25.b);
    return this;
  }

  async embed(texts) {
    const size = this.settings.embedding.batch_size;
    const vectors = [];
    for (let i = 0; i < texts.length; i += size) vectors.push(...await llm.embed(texts.slice(i, i + size)));
    return vectors;
  }

  ranking(question, vector) {
    const byVector = search.rank(this.vectors.map((v) => chunkers.cosine(vector, v)));
    const byKeyword = search.rank(this.bm25.scores(question), true);
    return search.rank(search.rrf([byVector, byKeyword], this.settings.retrieval.rrf_k, this.chunks.length));
  }

  // Chunk indexes for an email's questions, in the order they were chosen.
  async retrieve(questions) {
    const r = this.settings.retrieval;
    if (!questions.length) return [];
    const vectors = await this.embed(questions.map((q) => this.settings.embedding.query_prefix + q));
    const chosen = [];
    let total = 0;
    questions.forEach((question, k) => {
      const budget = Math.min(r.budget_per_question, r.budget_per_email - total);
      let used = 0;
      for (const i of this.ranking(question, vectors[k])) {
        const { tokens } = this.chunks[i];
        if (!chosen.includes(i) && used + tokens <= budget) {
          chosen.push(i);
          used += tokens;
        }
      }
      total += used;
    });
    return chosen;
  }
}
