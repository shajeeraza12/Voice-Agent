"""Core, channels and db must never import a specific domain (ARCHITECTURE.md rule)."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_shared_layers_are_domain_free():
    offenders = []
    for layer in ("core", "channels", "db"):
        for path in (APP / layer).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                offenders += [f"{path.relative_to(APP)}: {n}" for n in names if n.startswith("app.domains")]
    assert offenders == []
