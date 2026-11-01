import json
import unittest
from pathlib import Path

from chat_tools import read_file
from llm.prompt import build_system_prompt
from models import TreeNode
from repo_parser import CHARS_PER_TOKEN, RepoParser


class RepoParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = RepoParser()

    def test_stop_words_do_not_select_unrelated_files(self):
        chunks = self.parser.chunk_files({"misc.py": "the to add and the"})

        selected = self.parser.select_relevant_chunks(
            chunks, "the to add", context_files=[], max_tokens=100,
        )

        self.assertEqual(selected, [])

    def test_relevant_content_after_first_two_thousand_characters_is_selected(self):
        content = ("unrelatedword " * 200) + "cacheboundarymarker"
        chunks = self.parser.chunk_files({"backend/cache.py": content})

        selected = self.parser.select_relevant_chunks(
            chunks, "cacheboundarymarker", context_files=[], max_tokens=1_000,
        )

        self.assertEqual(len(selected), 1)
        self.assertIn("cacheboundarymarker", selected[0].content)

    def test_oversized_chunk_does_not_prevent_later_relevant_chunk(self):
        chunks = self.parser.chunk_files({
            "large.py": "cache routing " * 100,
            "small.py": "cache",
        })

        selected = self.parser.select_relevant_chunks(
            chunks, "cache routing", context_files=[], max_tokens=2,
        )

        self.assertEqual([chunk.path for chunk in selected], ["small.py"])

    def test_pinned_files_are_selected_even_over_budget(self):
        chunks = self.parser.chunk_files({"pinned.py": "important " * 100})

        selected = self.parser.select_relevant_chunks(
            chunks, "unrelated", context_files=["pinned.py"], max_tokens=0,
        )

        self.assertEqual([chunk.path for chunk in selected], ["pinned.py"])

    def test_search_code_scans_file_tail_and_returns_line_numbers(self):
        content = ("ordinary line\n" * 1500) + "cacheboundarymarker = True\n"

        result = self.parser.search_code(
            {"backend/cache.py": content}, "cacheboundarymarker",
        )

        self.assertIn("backend/cache.py", result)
        self.assertIn("1501:", result)

    def test_known_answer_file_is_readable_without_keyword_match(self):
        fixture_path = Path(__file__).with_name("retrieval_cases.json")
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        no_keyword_case = next(case for case in cases if case["retrieval"] == "read_file")
        repo_root = Path(__file__).parents[2]
        answer_path = no_keyword_case["answer_files"][0]
        answer_source = (repo_root / answer_path).read_text(encoding="utf-8")
        chunks = self.parser.chunk_files({answer_path: answer_source})

        selected = self.parser.select_relevant_chunks(
            chunks, no_keyword_case["question"], context_files=[], max_tokens=10_000,
        )
        self.assertEqual(selected, [])

        result = read_file(
            {answer_path: answer_source},
            answer_path,
        )

        self.assertIn("Anthropic API error", result)
        self.assertNotIn("Claude", answer_path)

    def test_search_benchmarks_find_their_expected_files(self):
        fixture_path = Path(__file__).with_name("retrieval_cases.json")
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        repo_root = Path(__file__).parents[2]

        for case in cases:
            if case["retrieval"] != "search_code":
                continue
            files = {
                path: (repo_root / path).read_text(encoding="utf-8")
                for path in case["answer_files"]
            }
            result = self.parser.search_code(files, case["question"], max_results=100)

            for path in case["answer_files"]:
                with self.subTest(question=case["question"], path=path):
                    self.assertIn(path, result)

    def test_cacheable_prompt_prefix_is_stable_when_context_grows(self):
        tree = [TreeNode(path="backend/auth.py", type="blob")]
        first = build_system_prompt("owner", "repo", tree, [])
        chunk = self.parser.chunk_files({"backend/auth.py": "def authenticate(): pass"})[0]
        second = build_system_prompt("owner", "repo", tree, [chunk])

        self.assertEqual(first[0], second[0])
        self.assertEqual(first[0]["cache_control"], {"type": "ephemeral"})
        self.assertNotEqual(first[1]["text"], second[1]["text"])

    def test_chunks_cover_entire_file(self):
        content = "x" * 12_001

        chunks = self.parser.chunk_files({"large.txt": content})

        self.assertEqual("".join(chunk.content for chunk in chunks), content)
        self.assertEqual(sum(chunk.token_estimate for chunk in chunks), (len(content) + 3) // CHARS_PER_TOKEN)


if __name__ == "__main__":
    unittest.main()
