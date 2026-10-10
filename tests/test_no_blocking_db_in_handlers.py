"""tests/test_no_blocking_db_in_handlers.py — async routes never block on the DB

Locks the rule that async route code reaches PostgreSQL only through
db_read / db_write / asyncio.to_thread. A synchronous DB call inside an
async handler freezes the whole event loop (streaming, SSE, health): the
inline star delete took up to 7.8s, cold TOAST cascades up to 20s.

Static AST check over backend/routers/: inside every async function, flag
direct calls to the pool (_db_conn / _conn), to core.db functions (db.x()),
and to any router helper that itself calls the pool directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROUTERS = Path(__file__).resolve().parent.parent / "backend" / "routers"
POOL_FUNCS = {"_db_conn", "_conn"}
DB_MODULES = {"db", "_db"}


def _own_calls(fn: ast.AST):
    """Calls in fn's body, not descending into nested defs/lambdas."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _is_direct_db_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Name) and f.id in POOL_FUNCS:
        return True
    return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in DB_MODULES


def test_async_routes_do_not_call_db_synchronously():
    trees = {p: ast.parse(p.read_text(encoding="utf-8")) for p in ROUTERS.glob("*.py")}

    db_helpers = {
        node.name
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(_is_direct_db_call(c) for c in _own_calls(node))
    }

    offenders = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for call in _own_calls(node):
                f = call.func
                if _is_direct_db_call(call) or (isinstance(f, ast.Name) and f.id in db_helpers):
                    offenders.append(f"{path.name}:{call.lineno} in {node.name}()")

    assert not offenders, "blocking DB calls in async code: " + ", ".join(offenders)
