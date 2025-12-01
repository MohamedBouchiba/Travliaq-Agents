"""Simple helper script to test the `geo.text_to_place` MCP tool.

Run from the repository root:

    python test_geo_text_to_place.py --query "Honolulu" --country "US"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from app.config import settings
from app.crew_pipeline.mcp_tools import MCPToolWrapper, get_mcp_tools


def _serialize_result(result: Any) -> str:
    """Return a pretty string representation for display."""

    try:
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception:
        return str(result)


def _get_geo_tool(server_url: str) -> MCPToolWrapper:
    """Fetch the geo.text_to_place tool from the MCP server."""

    tools = get_mcp_tools(server_url)
    for tool in tools:
        if tool.name == "geo.text_to_place":
            return tool  # type: ignore[return-value]

    raise RuntimeError("geo.text_to_place tool not found on the MCP server.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Test the geo.text_to_place MCP tool.")
    parser.add_argument("--query", required=True, help="City or place query to validate (e.g., 'Paris').")
    parser.add_argument(
        "--country",
        help="Optional 2-letter country code to disambiguate results (e.g., 'FR' or 'US').",
    )
    parser.add_argument(
        "--server-url",
        default=settings.mcp_server_url,
        help="Override the MCP server URL (defaults to settings.mcp_server_url).",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if not args.server_url:
        logging.error("No MCP server URL configured. Set settings.mcp_server_url or provide --server-url.")
        return 1

    logging.info("Connecting to MCP server: %s", args.server_url)

    try:
        geo_tool = _get_geo_tool(args.server_url)
    except Exception as exc:  # pragma: no cover - runtime guard
        logging.error("Failed to load geo.text_to_place tool: %s", exc)
        return 1

    payload: dict[str, Any] = {"query": args.query}
    if args.country:
        payload["country"] = args.country

    logging.info("Invoking geo.text_to_place with payload: %s", payload)

    try:
        result = geo_tool._run(**payload)
    except Exception as exc:  # pragma: no cover - runtime guard
        logging.error("geo.text_to_place execution failed: %s", exc)
        return 1

    print("\n=== geo.text_to_place result ===")
    print(_serialize_result(result))
    print("===============================\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
