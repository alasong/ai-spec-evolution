"""Tests for dedup engine."""

import pytest

from src.processor.dedup import DedupEngine, cosine_similarity, build_word_freq


class TestDedupEngine:
    def test_keyword_overlap_score(self):
        engine = DedupEngine()
        score = engine.keyword_overlap_score(
            ["TDD", "testing", "python"],
            "TDD is great for python testing frameworks"
        )
        assert score == 1.0  # all 3 tags found

    def test_keyword_partial_match(self):
        engine = DedupEngine()
        score = engine.keyword_overlap_score(
            ["TDD", "testing", "rust"],
            "TDD is great for python testing"
        )
        assert score == pytest.approx(2 / 3)

    def test_keyword_no_match(self):
        engine = DedupEngine()
        score = engine.keyword_overlap_score(
            ["quantum", "computing"],
            "TDD is great for python"
        )
        assert score == 0.0

    def test_empty_tags(self):
        engine = DedupEngine()
        score = engine.keyword_overlap_score([], "some text")
        assert score == 0.0


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = {"hello": 1.0, "world": 1.0}
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        v1 = {"hello": 1.0}
        v2 = {"world": 1.0}
        assert cosine_similarity(v1, v2) == 0.0

    def test_partial_overlap(self):
        v1 = {"hello": 1.0, "world": 1.0}
        v2 = {"hello": 1.0, "foo": 1.0}
        sim = cosine_similarity(v1, v2)
        assert 0 < sim < 1

    def test_empty_vectors(self):
        assert cosine_similarity({}, {}) == 0.0


class TestBuildWordFreq:
    def test_basic(self):
        freq = build_word_freq("hello world hello")
        assert freq == {"hello": 2.0, "world": 1.0}

    def test_case_insensitive(self):
        freq = build_word_freq("Hello HELLO hello")
        assert freq == {"hello": 3.0}
