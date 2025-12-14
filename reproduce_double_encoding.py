
import json
import logging

# Mock logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Mock MCPToolsManager logic (from pipeline.py) ---
class MockMCPToolsManager:
    def call_tool(self, tool_name, result_string=None):
        # Emulate pipeline.py logic
        
        # Si le résultat est une string JSON, la parser
        if isinstance(result_string, str):
            try:
                parsed_result = json.loads(result_string)

                # 🆕 Si c'est la nouvelle structure MCP standardisée {success, results, ...}
                # extraire le champ "results"
                if isinstance(parsed_result, dict) and "results" in parsed_result:
                    return parsed_result["results"]

                return parsed_result
            except (json.JSONDecodeError, ValueError):
                # Pas du JSON valide, retourner tel quel
                return result_string

        # Si le résultat est déjà un dict Python avec la structure standardisée
        if isinstance(result_string, dict) and "results" in result_string:
            return result_string["results"]

        return result_string

# --- Mock ImageGenerator logic (from image_generator.py) ---
class MockImageGenerator:
    def __init__(self, mcp_tools):
        self.mcp_tools = mcp_tools
        self.tool_name = "images.background"

    def _invoke_mcp_tool(self, tool_name, result_mock):
        return self.mcp_tools.call_tool(tool_name, result_string=result_mock)

    def _is_valid_url(self, result, trip_code):
        if not result:
            return False
            
        if isinstance(result, dict):
            # Certains tools retournent dict {'url': ..., 'success': ...}
            if result.get('success') is False:
                return False
            url = result.get('url')
            return bool(url and isinstance(url, str) and "supabase.co" in url)
            
        if isinstance(result, str):
            # Vérifier si c'est une URL et pas un message d'erreur
            if "supabase.co" in result and result.startswith("http"):
                return True
            if "error" in result.lower() or "failed" in result.lower():
                return False
                
        return False

    def _fix_url_folder(self, url, expected_trip_code):
        # Extraire string si dict
        if isinstance(url, dict):
            url = url.get('url', '')
            
        if not isinstance(url, str):
            return ""

        # Logique simplifiée pour test
        return url

    def generate_image(self, result_mock):
        # Simulate _generate_with_retry logic
        result = self._invoke_mcp_tool(self.tool_name, result_mock)
        print(f"DEBUG: Result after invoke: {result} (type: {type(result)})")
        
        if self._is_valid_url(result, "TRIP"):
            final_url = self._fix_url_folder(result, "TRIP")
            return final_url
            
        return None

# --- Reproduction Tests ---
def run_tests():
    manager = MockMCPToolsManager()
    gen = MockImageGenerator(manager)

    print("--- Test 1: Normal JSON string ---")
    input1 = '{"url": "https://supabase.co/img.png"}'
    out1 = gen.generate_image(input1)
    print(f"Output: {out1}") 
    # Expect: 'https://supabase.co/img.png'

    print("\n--- Test 2: Normal JSON string with success=True ---")
    input2 = '{"url": "https://supabase.co/img.png", "success": true}'
    out2 = gen.generate_image(input2)
    print(f"Output: {out2}")
    # Expect: 'https://supabase.co/img.png'

    print("\n--- Test 3: Raw String ---")
    input3 = "https://supabase.co/img.png"
    out3 = gen.generate_image(input3)
    print(f"Output: {out3}")
    # Expect: 'https://supabase.co/img.png'

    print("\n--- Test 4: Double encoded JSON string ---")
    # This is "{\"url\": \"https://supabase.co/img.png\"}" passed as string from MCP
    input4 = '"{\\"url\\": \\"https://supabase.co/img.png\\"}"'
    out4 = gen.generate_image(input4)
    print(f"Output: {out4}")
    # Expect: 'https://supabase.co/img.png' if Manager parses once, result is string '{"url":...}'.
    # ImageGenerator receives string '{"url":...}'.
    # _is_valid_url checks string. startswith("http") is False.
    # Should return None.

    print("\n--- Test 5: Wrapped in 'results' ---")
    input5 = '{"results": {"url": "https://supabase.co/img.png"}}'
    out5 = gen.generate_image(input5)
    print(f"Output: {out5}")
    # Expect: 'https://supabase.co/img.png'

    print("\n--- Test 6: Wrapped in 'results' double encoded ---")
    input6 = '{"results": "{\\"url\\": \\"https://supabase.co/img.png\\"}"}'
    out6 = gen.generate_image(input6)
    print(f"Output: {out6}")
    # Expect: None (results is string, ImageGenerator gets string '{"url":...}', invalid)

    print("\n--- Test 7: Dict with JSON string as URL ---")
    input7 = '{"url": "{\\"url\\": \\"https://supabase.co/img.png\\"}"}'
    out7 = gen.generate_image(input7)
    print(f"Output: {out7}")
    # If this prints '{"url": "https://supabase.co/img.png"}', then we found the bug!
    # Because _is_valid_url checks "supabase.co" in url (True) but doesn't check if it starts with http explicitly for dict values?
    # Wait, check _is_valid_url dict branch:
    # return bool(url and isinstance(url, str) and "supabase.co" in url)
    # It does NOT check startswith("http").

if __name__ == "__main__":
    run_tests()
