import ahocorasick
from dataclasses import dataclass
from typing import List, Set


@dataclass
class DetectionResult:
    terms: List[str]


class TermDetector:
    def __init__(self) -> None:
        self._automaton = ahocorasick.Automaton()
        self._terms: Set[str] = set()

    def reload_terms(self, terms: List[str]) -> None:
        self._automaton = ahocorasick.Automaton()
        self._terms = set()
        for t in terms:
            term = t.strip()
            if not term:
                continue
            self._terms.add(term)
            self._automaton.add_word(term, term)
        self._automaton.make_automaton()

    def _is_boundary_ok(self, text: str, start: int, end: int) -> bool:
        left = text[start - 1] if start > 0 else " "
        right = text[end + 1] if end + 1 < len(text) else " "
        return (not left.isalnum()) and (not right.isalnum())

    def detect(self, text: str) -> DetectionResult:
        found: Set[str] = set()
        for end_idx, term in self._automaton.iter(text):
            start_idx = end_idx - len(term) + 1
            if len(term) < 3 and not self._is_boundary_ok(text, start_idx, end_idx):
                continue
            found.add(term)
        return DetectionResult(terms=sorted(found))
