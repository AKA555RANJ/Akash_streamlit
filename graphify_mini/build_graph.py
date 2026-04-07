"""
graphify_mini: a tiny Graphify-style knowledge graph builder.

Walks a folder of Python files, extracts:
  - module nodes
  - class / function nodes
  - import edges (module -> imported module)
  - call edges (function -> function, best-effort via name matching)

Outputs:
  - graph.json     : the full graph (nodes + edges)
  - graph.html     : interactive PyVis visualization
  - GRAPH_REPORT.md: summary of "god nodes" and clusters

Usage:
    python graphify_mini/build_graph.py <folder> [--out <out_dir>]

Example:
    python graphify_mini/build_graph.py . --out graphify_mini/out
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

import networkx as nx


# ---------- AST extraction ----------

class FileAnalyzer(ast.NodeVisitor):
    """Collects classes, functions, imports, and call names from a Python file."""

    def __init__(self, module_name: str):
        self.module_name = module_name
        self.classes: list[str] = []
        self.functions: list[str] = []
        self.imports: list[str] = []
        # function qualified name -> list of called names
        self.calls: dict[str, list[str]] = defaultdict(list)
        self._scope: list[str] = [module_name]

    def _qual(self, name: str) -> str:
        return ".".join(self._scope + [name])

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qual = self._qual(node.name)
        self.classes.append(qual)
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        qual = self._qual(node.name)
        self.functions.append(qual)
        self._scope.append(node.name)
        # collect call names within this function body
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = _call_name(child.func)
                if name:
                    self.calls[qual].append(name)
        self.generic_visit(node)
        self._scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


# ---------- graph building ----------

def build_graph(root: Path) -> nx.DiGraph:
    g = nx.DiGraph()
    py_files = [p for p in root.rglob("*.py") if "graphify_mini" not in p.parts]

    # first pass: collect analyzers keyed by module name
    analyzers: dict[str, FileAnalyzer] = {}
    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        module_name = path.stem
        sha = hashlib.sha256(source.encode("utf-8", "ignore")).hexdigest()[:12]

        analyzer = FileAnalyzer(module_name)
        analyzer.visit(tree)
        analyzers[module_name] = analyzer

        g.add_node(
            module_name,
            kind="module",
            path=str(path.relative_to(root)),
            sha=sha,
            loc=len(source.splitlines()),
        )

        for cls in analyzer.classes:
            g.add_node(cls, kind="class")
            g.add_edge(module_name, cls, type="defines")

        for fn in analyzer.functions:
            g.add_node(fn, kind="function")
            g.add_edge(module_name, fn, type="defines")

    # second pass: import edges + call edges (EXTRACTED vs INFERRED)
    short_name_index: dict[str, list[str]] = defaultdict(list)
    for node, data in g.nodes(data=True):
        if data.get("kind") in ("function", "class"):
            short = node.rsplit(".", 1)[-1]
            short_name_index[short].append(node)

    for mod, analyzer in analyzers.items():
        for imp in analyzer.imports:
            target = imp.split(".")[0]
            if target in analyzers and target != mod:
                g.add_edge(mod, target, type="imports", tag="EXTRACTED")

        for caller, called_names in analyzer.calls.items():
            for name in called_names:
                short = name.rsplit(".", 1)[-1]
                candidates = short_name_index.get(short, [])
                if len(candidates) == 1:
                    g.add_edge(caller, candidates[0], type="calls",
                               tag="EXTRACTED", confidence=1.0)
                elif len(candidates) > 1:
                    # ambiguous: pick best but mark as INFERRED
                    g.add_edge(caller, candidates[0], type="calls",
                               tag="INFERRED", confidence=round(1 / len(candidates), 2))

    return g


# ---------- reporting ----------

def write_report(g: nx.DiGraph, out_dir: Path) -> None:
    # "god nodes" = highest degree
    degrees = sorted(g.degree, key=lambda x: x[1], reverse=True)[:15]

    modules = [n for n, d in g.nodes(data=True) if d.get("kind") == "module"]
    classes = [n for n, d in g.nodes(data=True) if d.get("kind") == "class"]
    funcs = [n for n, d in g.nodes(data=True) if d.get("kind") == "function"]

    lines = [
        "# Graphify-mini Report",
        "",
        f"- **Modules**: {len(modules)}",
        f"- **Classes**: {len(classes)}",
        f"- **Functions**: {len(funcs)}",
        f"- **Edges**: {g.number_of_edges()}",
        "",
        "## God nodes (highest connectivity)",
        "",
    ]
    for node, deg in degrees:
        kind = g.nodes[node].get("kind", "?")
        lines.append(f"- `{node}` ({kind}) — degree {deg}")

    lines += ["", "## Edge tag breakdown", ""]
    tag_counts: dict[str, int] = defaultdict(int)
    for _, _, d in g.edges(data=True):
        tag_counts[d.get("tag", "-")] += 1
    for tag, n in tag_counts.items():
        lines.append(f"- {tag}: {n}")

    (out_dir / "GRAPH_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def write_json(g: nx.DiGraph, out_dir: Path) -> None:
    data = {
        "nodes": [{"id": n, **d} for n, d in g.nodes(data=True)],
        "edges": [{"source": u, "target": v, **d} for u, v, d in g.edges(data=True)],
    }
    (out_dir / "graph.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_html(g: nx.DiGraph, out_dir: Path) -> None:
    try:
        from pyvis.network import Network
    except ImportError:
        print("[warn] pyvis not installed; skipping graph.html. Run: pip install pyvis")
        return

    net = Network(height="800px", width="100%", directed=True, notebook=False)
    color_map = {"module": "#4C9AFF", "class": "#F5A623", "function": "#7ED321"}
    for node, d in g.nodes(data=True):
        net.add_node(
            node,
            label=node.rsplit(".", 1)[-1],
            title=f"{d.get('kind','?')}: {node}",
            color=color_map.get(d.get("kind"), "#CCCCCC"),
        )
    for u, v, d in g.edges(data=True):
        net.add_edge(u, v, title=d.get("type", ""), arrows="to")
    net.write_html(str(out_dir / "graph.html"), notebook=False, open_browser=False)


# ---------- CLI ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="Tiny Graphify-style graph builder.")
    parser.add_argument("folder", help="Folder to scan for .py files")
    parser.add_argument("--out", default="graphify_mini/out", help="Output directory")
    args = parser.parse_args()

    root = Path(args.folder).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[graphify_mini] scanning {root}")
    g = build_graph(root)
    print(f"[graphify_mini] nodes={g.number_of_nodes()} edges={g.number_of_edges()}")

    write_json(g, out_dir)
    write_report(g, out_dir)
    write_html(g, out_dir)
    print(f"[graphify_mini] wrote outputs to {out_dir}")


if __name__ == "__main__":
    main()
