import sys
from pathlib import Path

# Ensure the repository root is importable regardless of how pytest is
# invoked, so `import sandbox_mcp` and `import tools.mcp_sandbox` resolve to
# the top-level modules under test.
REPO_ROOT = Path(__file__).resolve().parents[2]
repo_root = str(REPO_ROOT)
if repo_root in sys.path:
    sys.path.remove(repo_root)
sys.path.insert(0, repo_root)
