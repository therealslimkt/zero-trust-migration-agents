from mcp.server.fastmcp import FastMCP
import sys
from io import StringIO

mcp = FastMCP("ExecutionSandbox")

@mcp.tool()
def execute_pipeline(code: str) -> str:
    """
    Executes a generated Apache Beam / Python pipeline script in a sandboxed environment.
    """
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = mystdout = StringIO()
    sys.stderr = mystderr = StringIO()
    
    print("[SANDBOX] Executing pipeline code...")
    try:
        # In a real secure sandbox, we would write this to a temporary file 
        # and execute it in an isolated container. 
        # For this hackathon demo, we'll execute it in-process.
        exec(code, {})
        result = mystdout.getvalue()
        if mystderr.getvalue():
            result += "\nErrors:\n" + mystderr.getvalue()
        return result
    except Exception as e:
        return f"Execution Error: {str(e)}"
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

if __name__ == "__main__":
    mcp.run()
