"""
tests/conftest.py
=================
Слага корена на репото в sys.path, за да се импортват catalog/core/export/run
при пускане на `pytest -q` отвсякъде.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
