from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ExecutionSandbox")

@mcp.tool()
def execute_python(code: str) -> str:
    """Executes python code (like an Apache Beam pipeline) in a sandbox and returns the stdout."""
    import sys
    from io import StringIO
    old_stdout = sys.stdout
    sys.stdout = mystdout = StringIO()
    try:
        # In a real environment, we'd use subprocess or a tighter sandbox, 
        # but for the demo we exec the generated Dataflow code
        exec(code, {})
    except Exception as e:
        return f"Error executing pipeline: {str(e)}"
    finally:
        sys.stdout = old_stdout
    return mystdout.getvalue()

# Expose the ASGI app for Uvicorn (Cloud Run compatibility)
app = mcp.sse_app()
