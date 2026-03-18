"""Entry point: python -m bundlefabric_mcp"""
import sys
import os

# Allow running from the mcp/ directory without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from bundlefabric_mcp.server import main

if __name__ == "__main__":
    main()
