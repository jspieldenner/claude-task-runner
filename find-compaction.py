#!/usr/bin/env python3
"""Search ~/project/compactions/*.md by hybrid embedding + BM25.

Lazy mtime-driven indexing: every run diffs the filesystem against
the SQLite index and re-embeds anything new or modified, then runs
the query (if given).

Long files are split into overlapping 4 KB windows (the largest
input bge-m3 handles in reasonable time on samsung's CPU). Each
window gets its own 1024-dim embedding row. At query time, the
per-file cosine score is max-pooled across the file's windows, so
a deep paraphrase match ranks the file as if the header itself
matched.

Final score = alpha * max-cosine + (1 - alpha) * bm25_norm.
BM25 always runs on full file text, so exact-string matches catch
deep content regardless of window boundaries.

Design: ~/project/docs/compaction-search-and-priming-design.md
"""

import argparse
import hashlib
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import requests


class BM25Okapi:
    """BM25 Okapi variant — see https://en.wikipedia.org/wiki/Okapi_BM25.

    Inlined to avoid the rank-bm25 dependency (which would need a venv on
    a PEP-668 system Python). Behavior matches rank-bm25's BM25Okapi:
    k1=1.5, b=0.75, Robertson-Sparck-Jones IDF with an `epsilon * avg_idf`
    floor for terms appearing in >half the corpus (so they don't get a
    negative weight).
    """

    def __init__(self, corpus, k1=1.5, b=0.75, epsilon=0.25):
        self.k1, self.b = k1, b
        n = len(corpus)
        self.doc_len = np.asarray([len(d) for d in corpus], dtype=np.float32)
        self.avgdl = float(self.doc_len.mean()) if n else 0.0
        self.tf = []
        df = {}
        for doc in corpus:
            freqs = {}
            for term in doc:
                freqs[term] = freqs.get(term, 0) + 1
            self.tf.append(freqs)
            for term in freqs:
                df[term] = df.get(term, 0) + 1
        self.idf = {t: math.log(n - f + 0.5) - math.log(f + 0.5)
                    for t, f in df.items()}
        if self.idf:
            avg_idf = sum(self.idf.values()) / len(self.idf)
            floor = epsilon * avg_idf
            for t, v in self.idf.items():
                if v < 0:
                    self.idf[t] = floor

    def get_scores(self, query):
        scores = np.zeros(len(self.tf), dtype=np.float32)
        for q in query:
            idf = self.idf.get(q)
            if not idf:
                continue
            for i, freqs in enumerate(self.tf):
                f = freqs.get(q, 0)
                if f == 0:
                    continue
                norm = 1 - self.b + self.b * (self.doc_len[i] / self.avgdl)
                scores[i] += idf * f * (self.k1 + 1) / (f + self.k1 * norm)
        return scores

HOME = Path.home()
COMPACTIONS_DIR = HOME / "project" / "compactions"
DB_PATH = COMPACTIONS_DIR / "index.db"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://pony:11434")
# Fallback when the primary host (pony) is powered down: samsung runs its
# own ollama with the same bge-m3 model. Embeddings are model-determined,
# so a locally-embedded query is comparable to the pony-embedded index.
LOCAL_OLLAMA = "http://localhost:11434"
EMBED_MODEL = "bge-m3:latest"
EMBED_DIM = 1024

# Chunking: 4000-char windows, 500-char overlap → stride 3500.
# 4000 chars ≈ 1000 tokens, fits bge-m3's 4096-token ctx with margin;
# any longer and embed time scales super-linearly on CPU.
WINDOW = 4000
STRIDE = 3500


def chunk_text(text):
    """Yield (chunk_idx, chunk_start, chunk_text) for one file."""
    if len(text) <= WINDOW:
        yield 0, 0, text
        return
    idx = 0
    start = 0
    while start < len(text):
        yield idx, start, text[start:start + WINDOW]
        idx += 1
        if start + WINDOW >= len(text):
            break
        start += STRIDE


def open_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS compactions (
          path         TEXT NOT NULL,
          chunk_idx    INTEGER NOT NULL,
          chunk_start  INTEGER NOT NULL,
          mtime        REAL NOT NULL,
          content_hash TEXT NOT NULL,
          embedding    BLOB NOT NULL,
          indexed_at   REAL NOT NULL,
          PRIMARY KEY (path, chunk_idx)
        )
    """)
    return conn


_resolved_host = None


def ollama_host(probe_timeout=2):
    """Return a reachable ollama base URL, probing once and caching.

    Tries the configured host (pony by default) first; if it doesn't
    answer within probe_timeout seconds, falls back to a local ollama.
    Exits with a clear message if neither is reachable. Probing avoids
    the 300 s embed timeout hanging the whole run when pony is down.
    """
    global _resolved_host
    if _resolved_host is not None:
        return _resolved_host

    def reachable(host):
        try:
            requests.get(f"{host}/api/version", timeout=probe_timeout)
            return True
        except requests.RequestException:
            return False

    if reachable(OLLAMA_HOST):
        _resolved_host = OLLAMA_HOST
    elif LOCAL_OLLAMA != OLLAMA_HOST and reachable(LOCAL_OLLAMA):
        print(f"{OLLAMA_HOST} unreachable; using local ollama at {LOCAL_OLLAMA}",
              file=sys.stderr)
        _resolved_host = LOCAL_OLLAMA
    else:
        sys.exit(f"error: no reachable ollama at {OLLAMA_HOST} "
                 f"or {LOCAL_OLLAMA} — start one or set OLLAMA_HOST")
    return _resolved_host


def embed(texts, timeout=300):
    """POST a list of strings to ollama, return Nx1024 float32 array."""
    r = requests.post(
        f"{ollama_host()}/api/embed",
        json={"model": EMBED_MODEL, "input": texts, "keep_alive": "30m"},
        timeout=timeout,
    )
    r.raise_for_status()
    arr = np.asarray(r.json()["embeddings"], dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def sync_index(conn, verbose=False):
    fs_files = {p: p.stat().st_mtime for p in sorted(COMPACTIONS_DIR.glob("*.md"))}
    db_state = {}  # path -> (mtime, content_hash)
    for p, m, h in conn.execute("SELECT path, mtime, content_hash FROM compactions"):
        # multiple rows per path; mtime/hash are identical across them
        db_state[Path(p)] = (m, h)

    to_embed = []  # list of (path, content_hash, [chunks])
    for p, mtime in fs_files.items():
        if p in db_state and abs(db_state[p][0] - mtime) < 1e-6:
            continue
        text = p.read_text(errors="replace")
        h = hashlib.sha256(text.encode()).hexdigest()
        if p in db_state and db_state[p][1] == h:
            conn.execute(
                "UPDATE compactions SET mtime = ? WHERE path = ?", (mtime, str(p))
            )
            continue
        chunks = list(chunk_text(text))
        to_embed.append((p, h, chunks))

    total_chunks = sum(len(c) for _, _, c in to_embed)
    if to_embed:
        if verbose:
            print(f"embedding {total_chunks} chunk(s) across {len(to_embed)} file(s)...",
                  file=sys.stderr)
        # Single-chunk requests: ollama serializes bge-m3 on CPU, so a
        # batch gives no parallelism but a per-batch timeout loses
        # multiple chunks' work on a stall.
        done = 0
        for path, h, chunks in to_embed:
            # Replace all rows for this path first, in case the chunk
            # count went down on a content change.
            with conn:
                conn.execute("DELETE FROM compactions WHERE path = ?", (str(path),))
            mtime = fs_files[path]
            for idx, start, ctext in chunks:
                vec = embed([ctext])[0]
                with conn:
                    conn.execute(
                        "INSERT INTO compactions "
                        "(path, chunk_idx, chunk_start, mtime, content_hash, "
                        " embedding, indexed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (str(path), idx, start, mtime, h, vec.tobytes(), time.time()),
                    )
                done += 1
                if verbose:
                    print(f"  [{done}/{total_chunks}] {path.name} chunk {idx} "
                          f"({start}..{start + len(ctext)})", file=sys.stderr)

    deleted = [p for p in db_state if p not in fs_files]
    if deleted:
        with conn:
            conn.executemany(
                "DELETE FROM compactions WHERE path = ?",
                [(str(p),) for p in deleted],
            )
        if verbose:
            print(f"removed rows for {len(deleted)} deleted file(s)", file=sys.stderr)


def search(conn, query, top_k, alpha):
    rows = conn.execute(
        "SELECT path, chunk_idx, mtime, embedding FROM compactions "
        "ORDER BY path, chunk_idx"
    ).fetchall()
    if not rows:
        return []

    row_paths = [Path(p) for p, _, _, _ in rows]
    mat = np.vstack([np.frombuffer(b, dtype=np.float32) for _, _, _, b in rows])
    qv = embed([query])[0]
    cos = mat @ qv

    # Max-pool cosine per file.
    unique_paths = []
    max_cos = {}
    best_chunk = {}
    mtime_by_path = {}
    for p, (_, idx, mtime, _), c in zip(row_paths, rows, cos):
        if p not in max_cos:
            unique_paths.append(p)
            max_cos[p] = float(c)
            best_chunk[p] = idx
            mtime_by_path[p] = mtime
        elif c > max_cos[p]:
            max_cos[p] = float(c)
            best_chunk[p] = idx

    texts = [p.read_text(errors="replace") for p in unique_paths]
    bm25 = BM25Okapi([t.lower().split() for t in texts])
    bm = np.asarray(bm25.get_scores(query.lower().split()), dtype=np.float32)
    bm_norm = bm / bm.max() if bm.max() > 0 else bm

    pooled_cos = np.asarray([max_cos[p] for p in unique_paths], dtype=np.float32)
    score = alpha * pooled_cos + (1 - alpha) * bm_norm
    order = np.argsort(-score)[:top_k]
    return [
        (unique_paths[i], float(score[i]), float(pooled_cos[i]),
         float(bm_norm[i]), best_chunk[unique_paths[i]],
         mtime_by_path[unique_paths[i]])
        for i in order
    ]


def fmt_age(mtime, now=None):
    """Human-readable age, fixed 4-char width: '3d', '12d', '5w', '14w', '8mo', '1y'."""
    if now is None:
        now = time.time()
    sec = max(0, now - mtime)
    days = sec / 86400
    if days < 1:
        return f"{int(sec / 3600):>3}h"
    if days < 14:
        return f"{int(days):>3}d"
    if days < 84:  # 12 weeks
        return f"{int(days / 7):>3}w"
    if days < 365:
        return f"{int(days / 30):>3}mo"
    return f"{int(days / 365):>3}y"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", help="query string (omit for index-only run)")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--alpha", type=float, default=0.7,
                    help="weight on cosine vs BM25 (default 0.7)")
    ap.add_argument("--rebuild", action="store_true",
                    help="drop the index and re-embed everything")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.rebuild and DB_PATH.exists():
        DB_PATH.unlink()
        for sfx in ("-wal", "-shm"):
            p = DB_PATH.with_name(DB_PATH.name + sfx)
            if p.exists():
                p.unlink()

    conn = open_db()
    sync_index(conn, verbose=args.verbose)

    if not args.query:
        n_files = conn.execute(
            "SELECT COUNT(DISTINCT path) FROM compactions"
        ).fetchone()[0]
        n_chunks = conn.execute("SELECT COUNT(*) FROM compactions").fetchone()[0]
        print(f"index: {n_files} file(s), {n_chunks} chunk(s) at {DB_PATH}",
              file=sys.stderr)
        return

    hits = search(conn, args.query, args.top_k, args.alpha)
    now = time.time()
    for path, score, cos, bm, chunk, mtime in hits:
        rel = path.relative_to(HOME) if path.is_relative_to(HOME) else path
        print(f"{score:.3f}  cos={cos:.3f} bm25={bm:.3f}  "
              f"chunk={chunk:>2}  age={fmt_age(mtime, now)}  ~/{rel}")


if __name__ == "__main__":
    main()
