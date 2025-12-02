import os
import sys
import logging
import time
from typing import Dict, Any, List
from dotenv import load_dotenv

# Ensure we can import from the app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("MCP_TESTER")

# Load environment variables
load_dotenv()

try:
    from app.crew_pipeline.mcp_tools import get_mcp_tools
except ImportError as e:
    logger.error(f"Failed to import mcp_tools: {e}")
    sys.exit(1)

# Configuration
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://travliaq-mcp-production.up.railway.app/sse")

# Test Data
TEST_CASES = [
    {
        "tool": "health.ping",
        "args": {},
        "description": "Basic connectivity check"
    },
    {
        "tool": "geo.text_to_place",
        "args": {"query": "Paris", "country": "FR"},
        "description": "Geocoding Paris, FR"
    },
    {
        "tool": "geo.text_to_place",
        "args": {"query": "Honolulu", "country": "US"},
        "description": "Geocoding Honolulu, US (User reported timeout)"
    },
    {
        "tool": "places.overview",
        "args": {"query": "London"},
        "description": "Place overview for London"
    },
    {
        "tool": "airports.nearest",
        "args": {"city": "Berlin"},
        "description": "Nearest airport to Berlin"
    },
    {
        "tool": "weather.brief",
        "args": {"lat": 40.7128, "lon": -74.0060},
        "description": "Weather brief for New York"
    },
    {
        "tool": "booking.search",
        "args": {
            "city": "Rome",
            "checkin": "2025-06-01",
            "checkout": "2025-06-03",
            "max_results": 2
        },
        "description": "Booking search in Rome (2 results)"
    },
    {
        "tool": "flights.prices",
        "args": {
            "origin": "LHR",
            "destination": "JFK",
            "start_date": "2026-02-12",
            "end_date": "2026-02-20"
        },
        "description": "Flight prices LHR -> JFK"
    }
]

def run_tests():
    logger.info(f"🚀 Starting MCP Tools Test Suite")
    logger.info(f"Target Server: {MCP_SERVER_URL}")
    
    # 1. Fetch Tools
    logger.info("Step 1: Fetching available tools...")
    start_time = time.time()
    try:
        tools = get_mcp_tools(MCP_SERVER_URL)
        duration = time.time() - start_time
        logger.info(f"✅ Successfully fetched {len(tools)} tools in {duration:.2f}s")
    except Exception as e:
        logger.error(f"❌ Failed to fetch tools: {e}")
        return

    # Map tools by name for easy access
    tools_map = {t.name: t for t in tools}
    
    # 2. Run Test Cases
    logger.info("Step 2: Running Test Cases...")
    
    passed = 0
    failed = 0
    
    for i, test in enumerate(TEST_CASES, 1):
        tool_name = test["tool"]
        args = test["args"]
        desc = test["description"]
        
        logger.info(f"\n--- Test {i}/{len(TEST_CASES)}: {tool_name} ---")
        logger.info(f"Description: {desc}")
        logger.info(f"Input: {args}")
        
        if tool_name not in tools_map:
            logger.warning(f"⚠️ Tool {tool_name} not found in available tools. Skipping.")
            continue
            
        tool = tools_map[tool_name]
        
        start_time = time.time()
        try:
            # Execute tool
            result = tool.run(**args)
            duration = time.time() - start_time
            
            # Check for error strings that might be returned by the wrapper
            if isinstance(result, str) and result.startswith("Error"):
                logger.error(f"❌ FAILED in {duration:.2f}s")
                logger.error(f"Error Output: {result}")
                failed += 1
            else:
                logger.info(f"✅ PASSED in {duration:.2f}s")
                # logger.info(f"Output: {str(result)[:200]}...")
                passed += 1
                
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"❌ EXCEPTION in {duration:.2f}s: {e}")
            failed += 1

    logger.info("\n" + "="*30)
    logger.info(f"Test Summary: {passed} Passed, {failed} Failed")
    logger.info("="*30)

if __name__ == "__main__":
    run_tests()
