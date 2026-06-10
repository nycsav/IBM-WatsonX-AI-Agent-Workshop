"""Routing-invariant guards — design §4.7 (TST-RT1, TST-RT2)."""
import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

AGENT_FILES = ["agents/monitor.py", "agents/trader.py", "agents/executor.py",
               "agents/researcher.py"]


def imports_of(path: Path):
    tree = ast.parse(path.read_text())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.append(mod)
            names += [f"{mod}.{a.name}" for a in node.names]
    return names


def test_agents_never_import_presto():            # TST-RT1
    for rel in AGENT_FILES:
        for name in imports_of(SRC / rel):
            assert "presto" not in name.lower(), \
                f"{rel} imports Presto — hot path must be Cassandra-only"


def test_cassandra_statements_partition_keyed():  # TST-RT2
    """Audit the actual statement registry: every SELECT/UPDATE/DELETE
    keys on the session_id partition key; nothing uses ALLOW FILTERING."""
    from src.db.cassandra import _STMTS
    keyed = 0
    for name, stmt in _STMTS.items():
        flat = " ".join(stmt.split()).upper()
        assert "ALLOW FILTERING" not in flat, name
        verb = flat.split()[0]
        if verb in ("SELECT", "UPDATE", "DELETE"):
            where = flat.split("WHERE", 1)[1] if "WHERE" in flat else ""
            assert "SESSION_ID = ?" in where, \
                f"{name}: {verb} missing partition key"
            keyed += 1
    assert keyed >= 7, "expected the full keyed-statement registry"
