import sys
print("--- env_test.py output START ---", file=sys.stderr)
sys.stderr.flush() # Ensure it's flushed
print(f"Python version: {sys.version}", file=sys.stderr)
sys.stderr.flush()
print("--- env_test.py output END ---", file=sys.stderr)
sys.stderr.flush()
sys.exit(0)
