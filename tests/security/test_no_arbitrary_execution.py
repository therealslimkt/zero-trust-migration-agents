"""Static checks that arbitrary execution cannot be redeployed.

These tests parse the MCP modules with `ast` (rather than scanning raw text)
so that safe documentation strings/comments that merely *mention* `exec()`,
`eval()`, or `allUsers` -- to explain that those capabilities were removed --
do not trip the checks. Only actual call sites / active configuration lines
are asserted on.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MCP_MODULES = [
    REPO_ROOT / "sandbox_mcp.py",
    REPO_ROOT / "tools" / "mcp_sandbox.py",
]

FORBIDDEN_CALL_NAMES = {"exec", "eval"}
FORBIDDEN_TOOL_NAMES = {"execute_python", "execute_pipeline"}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _call_names(tree: ast.Module):
    """Yield the callee name for every actual Call node in the module.

    This walks the AST rather than the source text, so string literals
    (docstrings, comments-as-strings, log messages) that merely contain the
    substring "exec(" or "eval(" are never mistaken for a call.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            yield node.func.id


def _function_def_names(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name


def test_mcp_modules_have_no_exec_or_eval_calls():
    for path in MCP_MODULES:
        tree = _parse(path)
        found = {name for name in _call_names(tree) if name in FORBIDDEN_CALL_NAMES}
        assert not found, f"found call(s) to {found} in {path}"


def test_mcp_modules_expose_only_validation_tool():
    for path in MCP_MODULES:
        tree = _parse(path)
        defined = set(_function_def_names(tree))
        assert "validate_pipeline_plan" in defined, f"{path} must define validate_pipeline_plan"
        forbidden = defined & FORBIDDEN_TOOL_NAMES
        assert not forbidden, f"found forbidden tool function(s) {forbidden} defined in {path}"


def _non_comment_lines(source: str):
    """Return the source with full-line shell comments removed.

    This is an "active configuration" view of a shell script: it strips
    lines that are purely explanatory (starting with `#`, ignoring leading
    whitespace) so that documentation describing what the script *refuses*
    to do -- e.g. a comment noting that a binding is scoped away from
    `allUsers` -- cannot itself trigger a text-match failure.
    """
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )


def test_deploy_sandbox_requires_authenticated_invocation():
    source = _non_comment_lines((REPO_ROOT / "deploy_sandbox.sh").read_text())
    assert "--allow-unauthenticated" not in source
    assert "--no-allow-unauthenticated" in source


def test_deploy_sandbox_requires_internal_ingress():
    source = _non_comment_lines((REPO_ROOT / "deploy_sandbox.sh").read_text())
    assert "--ingress=internal" in source


def test_deploy_sandbox_requires_explicit_service_account():
    source = _non_comment_lines((REPO_ROOT / "deploy_sandbox.sh").read_text())
    assert "SANDBOX_SERVICE_ACCOUNT" in source
    assert "--service-account" in source


def test_deploy_sandbox_enforces_invoker_iam_check():
    source = _non_comment_lines((REPO_ROOT / "deploy_sandbox.sh").read_text())
    assert "roles/run.invoker" in source
    assert "SANDBOX_INVOKER_MEMBER" in source
    assert "--invoker-iam-check" in source
    assert "allUsers" not in source


def test_deploy_sandbox_fails_closed_before_mutation():
    source = (REPO_ROOT / "deploy_sandbox.sh").read_text()
    checks_index = source.index("SANDBOX_SERVICE_ACCOUNT")
    build_index = source.index("gcloud builds submit")
    assert checks_index < build_index, (
        "service account / invoker checks must run before the build and "
        "deploy mutation"
    )


def test_setup_vms_never_embeds_raw_tailscale_key():
    source = _non_comment_lines((REPO_ROOT / "setup_vms.sh").read_text())
    assert "TAILSCALE_KEY" not in source
    assert "TAILSCALE_SECRET_NAME" in source
    assert "secretmanager.googleapis.com" in source


def test_setup_vms_requires_explicit_service_account():
    source = _non_comment_lines((REPO_ROOT / "setup_vms.sh").read_text())
    assert "VM_SERVICE_ACCOUNT" in source
    assert "--service-account=" in source
