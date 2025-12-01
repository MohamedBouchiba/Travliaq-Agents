from app.crew_pipeline.mcp_tools import _sanitize_tool_arguments


def test_sanitize_tool_arguments_drops_none_values():
    args = {"query": "Paris", "timezone": None, "max_results": 1}

    assert _sanitize_tool_arguments(args) == {"query": "Paris", "max_results": 1}
