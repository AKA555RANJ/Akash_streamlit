# graphify_mini

A tiny, dependency-light prototype inspired by
[safishamsi/graphify](https://github.com/safishamsi/graphify).

It scans Python files, builds a knowledge graph of modules / classes / functions
/ imports / calls, and writes:

- `out/graph.json` — full graph (nodes + edges)
- `out/graph.html` — interactive PyVis visualization
- `out/GRAPH_REPORT.md` — summary with "god nodes" and tag counts

## Install

```bash
pip install -r graphify_mini/requirements.txt
```

## Run

From the repo root:

```bash
python graphify_mini/build_graph.py . --out graphify_mini/out
```

Then open `graphify_mini/out/graph.html` in a browser.

## How it works

1. **AST pass** — Python's stdlib `ast` module parses every `.py` file.
   Extracts classes, functions, imports, and call names. No LLM required.
2. **Graph assembly** — builds a `networkx.DiGraph`:
   - module nodes, class nodes, function nodes
   - `defines` edges (module -> class/function)
   - `imports` edges (module -> module)
   - `calls` edges (function -> function). Unique name match is tagged
     `EXTRACTED` with confidence 1.0; ambiguous matches are `INFERRED`
     with confidence `1/n_candidates`.
3. **Reporting** — highest-degree nodes become "god nodes"; the report lists
   them along with edge tag counts.

## Edge tags (mirrors Graphify)

| Tag        | Meaning                                               |
|------------|-------------------------------------------------------|
| EXTRACTED  | Directly derived from the AST (high confidence)       |
| INFERRED   | Best-effort match with a confidence score below 1.0   |

## Scope / limits

- Python only (the real Graphify uses tree-sitter for ~15 languages).
- No semantic pass over docs/PDFs/images — add an LLM call later if you want.
- Call resolution is name-based, not a full type-aware analysis.
- No caching yet; re-parses everything on each run.

## Next steps to evolve this toward real Graphify

- Add SHA256 caching so only changed files are re-parsed.
- Add a semantic pass that sends markdown/PDF chunks to an LLM for concept
  extraction.
- Run Leiden community detection (`graspologic`) and color nodes by cluster.
- Add a `query` CLI that loads `graph.json` and answers questions using the
  graph instead of re-reading source files.
