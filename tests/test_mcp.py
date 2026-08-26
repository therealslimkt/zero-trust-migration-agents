from mcp.server.fastmcp import FastMCP
mcp = FastMCP("ExecutionSandbox")

@mcp.tool()
def execute_python(code: str) -> str:
    """Executes python code in a sandbox and returns the stdout."""
    import sys
    from io import StringIO
    old_stdout = sys.stdout
    sys.stdout = mystdout = StringIO()
    try:
        exec(code, {})
    except Exception as e:
        return str(e)
    finally:
        sys.stdout = old_stdout
    return mystdout.getvalue()

if __name__ == "__main__":
    mcp.run()
