import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure app is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.crew_pipeline.scripts.image_generator import ImageGenerator

class TestImageGenerator(unittest.TestCase):
    def setUp(self):
        self.mock_mcp = MagicMock()
        self.generator = ImageGenerator(self.mock_mcp)

    def test_generate_image_success(self):
        print("\nTesting Success Scenario...")
        # Setup mock to return a valid URL
        self.mock_mcp.call_tool.return_value = "https://cinbnmlfpffmyjmkwbco.supabase.co/storage/v1/object/public/TRIPS/TEST-TRIP/image.png"
        
        url = self.generator.generate_image(
            prompt="Test prompt",
            trip_code="TEST-TRIP",
            image_type="background"
        )
        
        print(f"Result URL: {url}")
        self.assertEqual(url, "https://cinbnmlfpffmyjmkwbco.supabase.co/storage/v1/object/public/TRIPS/TEST-TRIP/image.png")
        self.mock_mcp.call_tool.assert_called_once()

    def test_generate_image_retry_failure(self):
        print("\nTesting Retry Failure Scenario...")
        # Setup mock to fail 3 times
        self.mock_mcp.call_tool.side_effect = Exception("MCP Error")
        
        url = self.generator.generate_image(
            prompt="Test prompt",
            trip_code="TEST-TRIP",
            image_type="background"
        )
        
        print(f"Result URL (Fallback): {url}")
        # Should return fallback
        self.assertTrue(url.startswith("https://")) 
        self.assertEqual(self.mock_mcp.call_tool.call_count, 3)

    def test_validation_logic(self):
        print("\nTesting Validation Logic Scenario...")
        # Setup mock to return invalid URL first, then valid
        self.mock_mcp.call_tool.side_effect = [
            "start generation...", # String message, not URL
            {"success": False},    # Failed dict
            "https://cinbnmlfpffmyjmkwbco.supabase.co/storage/v1/object/public/TRIPS/TEST-TRIP/valid.png"
        ]
        
        url = self.generator.generate_image(
            prompt="Test prompt",
            trip_code="TEST-TRIP",
            image_type="background"
        )
        
        print(f"Result URL: {url}")
        self.assertEqual(url, "https://cinbnmlfpffmyjmkwbco.supabase.co/storage/v1/object/public/TRIPS/TEST-TRIP/valid.png")
        self.assertEqual(self.mock_mcp.call_tool.call_count, 3)

if __name__ == '__main__':
    unittest.main()
