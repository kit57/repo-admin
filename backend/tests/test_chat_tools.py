import unittest

from chat_tools import CHAT_TOOLS, read_file
from llm.anthropic_provider import AnthropicProvider
from llm.ollama_provider import OllamaProvider
from llm.openai_provider import OpenAIProvider


class ChatToolTests(unittest.TestCase):
    def test_tool_definitions_expose_only_repository_retrieval(self):
        names = {tool["function"]["name"] for tool in CHAT_TOOLS}

        self.assertEqual(names, {"read_file", "search_code"})

    def test_read_file_supports_bounded_line_ranges(self):
        result = read_file(
            {"src/example.py": "one\ntwo\nthree\nfour"},
            "src/example.py",
            start_line=2,
            end_line=3,
        )

        self.assertIn("2: two", result)
        self.assertIn("3: three", result)
        self.assertNotIn("1: one", result)
        self.assertNotIn("4: four", result)

    def test_read_file_caps_large_tool_results(self):
        result = read_file(
            {"src/large.py": "\n".join("x" * 500 for _ in range(100))},
            "src/large.py",
        )

        self.assertLessEqual(len(result), 12_100)
        self.assertIn("output capped", result)

    def test_anthropic_translates_normalized_tool_messages(self):
        messages = [
            {"role": "user", "content": "Read the file"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"src/example.py"}',
                    },
                }],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "source text"},
        ]

        converted = AnthropicProvider._messages(messages)

        self.assertEqual(converted[1]["content"][0]["type"], "tool_use")
        self.assertEqual(converted[2]["content"][0]["type"], "tool_result")
        self.assertEqual(converted[2]["content"][0]["content"], "source text")

    def test_ollama_converts_arguments_to_objects(self):
        messages = [{
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-1",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"src/example.py"}',
                },
            }],
        }]

        converted = OllamaProvider._messages(messages)

        self.assertEqual(
            converted[0]["tool_calls"][0]["function"]["arguments"],
            {"path": "src/example.py"},
        )

    def test_openai_flattens_cacheable_system_blocks(self):
        system = [
            {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "context"},
        ]

        self.assertEqual(OpenAIProvider._system_text(system), "stable\n\ncontext")


if __name__ == "__main__":
    unittest.main()
