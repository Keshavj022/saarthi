"""Pytest bootstrap: put the project root on sys.path so `import core...`,
`import control...`, etc. resolve when running the test suite from anywhere."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
