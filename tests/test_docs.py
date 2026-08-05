"""
tests/test_docs.py
==================
Пазачи срещу мандат-док дрейфа (фамилният модел от bg док-одита 29.07.2026):
мандатът сменя кода, а README/AGENT.md остават на старата снимка. Пазачът
чете ЖИВИЯ код и съди текста, не преписано число.
"""
import re
from pathlib import Path

from analysis.lens_history import history_columns
from config import MODULE_WEIGHTS

ROOT = Path(__file__).parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_docs_describe_the_composition_format_not_a_snapshot():
    """Форматът е динамичен (`composition` тагът се строи от каталога и
    теглата) — документите описват ФОРМАТА `<N>s<M>l-<sha1[:8]>`;
    снимка-литерал се чупи тихо при всеки мандат, който пипа състава."""
    for name in ("README.md", "AGENT.md"):
        text = _read(name)
        assert "<N>s<M>l-" in text, name
        assert re.search(r"\b\d+s\d+l-", text) is None, (
            f"{name} държи снимка на тага вместо формата"
        )


def test_the_readme_lists_every_history_column():
    """Родовите `z_<леща>` / `score_<леща>` се покриват от описанието им;
    всичко останало се изброява поименно — новата колона на следващия
    мандат пада тук, не в тихо разминаване."""
    readme = _read("README.md")
    generated = {f"z_{lens}" for lens in MODULE_WEIGHTS} | {
        f"score_{lens}" for lens in MODULE_WEIGHTS
    }
    for col in history_columns():
        if col in generated:
            continue
        assert f"`{col}`" in readme, col


def test_agent_md_knows_every_module():
    """Всеки публичен модул присъства в AGENT.md по име (private `_`-модулите
    и `__init__` са вътрешна кухня и не се изброяват)."""
    agent = _read("AGENT.md")
    packages = ("catalog", "analysis", "sources", "core", "export", "scripts")
    modules = [
        p.name
        for pkg in packages
        for p in sorted((ROOT / pkg).glob("*.py"))
        if not p.name.startswith("_")
    ]
    modules += ["run.py", "config.py"]
    for name in modules:
        assert name in agent, name
