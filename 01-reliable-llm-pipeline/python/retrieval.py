"""
Retrieval for the pipeline: the documents are chunked and embedded once, and each question gets the chunks
ranked by RRF of vector and BM25, filled into its budget (see data/settings.json).
"""
import chunkers
import llm
import search


class Index:
    def __init__(self, settings: dict, documents: dict[str, str], tokenizer):
        self.settings = settings
        self.chunks = chunkers.chunk(settings["chunking"], documents, tokenizer)
        texts = [c.text for c in self.chunks]
        self.vectors = self.embed([settings["embedding"]["document_prefix"] + t for t in texts])
        r = settings["retrieval"]
        self.bm25 = search.BM25(texts, r["bm25"]["analyzer"], r["bm25"]["k1"], r["bm25"]["b"])

    def embed(self, texts: list[str]) -> list[list[float]]:
        size, vectors = self.settings["embedding"]["batch_size"], []
        for i in range(0, len(texts), size):
            vectors += llm.embed(texts[i:i + size])
        return vectors

    def ranking(self, question: str, vector: list[float]) -> list[int]:
        by_vector = search.rank([chunkers.cosine(vector, v) for v in self.vectors])
        by_keyword = search.rank(self.bm25.scores(question), matched_only=True)
        return search.rank(search.rrf([by_vector, by_keyword], self.settings["retrieval"]["rrf_k"], len(self.chunks)))

    def retrieve(self, questions: list[str]) -> list[int]:
        """Chunk indexes for an email's questions, in the order they were chosen."""
        r = self.settings["retrieval"]
        if not questions:
            return []
        vectors = self.embed([self.settings["embedding"]["query_prefix"] + q for q in questions])
        chosen: list[int] = []
        total = 0
        for question, vector in zip(questions, vectors):
            budget = min(r["budget_per_question"], r["budget_per_email"] - total)
            used = 0
            for i in self.ranking(question, vector):
                tokens = self.chunks[i].tokens
                if i not in chosen and used + tokens <= budget:
                    chosen.append(i)
                    used += tokens
            total += used
        return chosen
