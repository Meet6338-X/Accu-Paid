"""RAG ingest — markdown policy docs -> 350-token chunks (50 overlap) -> JSONL index.

Weekend build: keyword index (`rag/index.jsonl`) backing `policy_search` — no Docker,
no downloads, works offline. Pilot upgrade path (documented below): e5 embeddings
(`intfloat/multilingual-e5-base`, `passage:`/`query:` prefixes) into Qdrant collection
`AccuPaid_policy`, top-k 5, optional cross-encoder rerank. The chunk/cite contract
(`[doc_id:chunk]`) is identical on both paths, so answers and evals don't change.

Usage:
  python rag/ingest.py [--docs rag/policy_docs] [--out rag/index.jsonl]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CHUNK_TOKENS = 350
OVERLAP_TOKENS = 50
CHARS_PER_TOKEN = 4  # conservative for Devanagari (Hindi ~3x fertility assumed)

CITE_RE = re.compile(r"\[([a-z_]+):(\d+)\]")


def chunk_text(text: str, size: int = CHUNK_TOKENS * CHARS_PER_TOKEN,
               overlap: int = OVERLAP_TOKENS * CHARS_PER_TOKEN) -> list[str]:
    words = text.split()
    chunks, cur, cur_len = [], [], 0
    for w in words:
        cur.append(w)
        cur_len += len(w) + 1
        if cur_len >= size:
            chunks.append(" ".join(cur))
            keep = " ".join(cur)[-overlap:]
            cur, cur_len = [keep], len(keep)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def ingest(docs_dir: str = "rag/policy_docs", out: str = "rag/index.jsonl") -> dict:
    docs = sorted(Path(docs_dir).glob("*.md"))
    n_chunks = 0
    with open(out, "w", encoding="utf-8") as f:
        for md in docs:
            text = md.read_text(encoding="utf-8")  # Devanagari kept intact
            for i, ch in enumerate(chunk_text(text)):
                cites = CITE_RE.findall(ch)
                doc_id = cites[0][0] if cites else md.stem.lower()
                f.write(json.dumps({"doc_id": doc_id, "chunk_id": i,
                                    "cite": f"[{doc_id}:{i:02d}]",
                                    "source": md.name, "text": ch},
                                   ensure_ascii=False) + "\n")
                n_chunks += 1
    return {"docs": len(docs), "chunks": n_chunks, "out": out}


# --- pilot upgrade: e5 + Qdrant (requires docker + downloads; NOT needed to run) ---
#
#   from sentence_transformers import SentenceTransformer
#   from qdrant_client import QdrantClient
#   from qdrant_client.models import Distance, VectorParams
#   model = SentenceTransformer("intfloat/multilingual-e5-base")
#   client = QdrantClient(url="http://localhost:6333")
#   client.recreate_collection("AccuPaid_policy",
#       vectors_config=VectorParams(size=768, distance=Distance.COSINE))
#   for row in index_rows:  # embed with "passage: " prefix
#       client.upsert("AccuPaid_policy", points=[...])
#   # query with "query: " prefix, top-k 5, rerank optional.
#   # Retrieval contract (Lost-in-the-Middle): docs capped 1800 tokens, best chunk
#   # first and last; HyDE fallback when Hinglish query has no keyword overlap.

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="rag/policy_docs")
    ap.add_argument("--out", default="rag/index.jsonl")
    args = ap.parse_args()
    print(ingest(args.docs, args.out))
