"""
Abstract interface for identity graph storage backends (NetworkX / Neo4j).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class GraphBackend(ABC):
    @abstractmethod
    def add_alias(self, case_id: str, alias: str, **attrs) -> None:
        ...

    @abstractmethod
    def add_correlation(
        self,
        case_id: str,
        alias_a: str,
        alias_b: str,
        corr_type: str,
        confidence: float,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...

    @abstractmethod
    def to_json(self, case_id: str) -> Dict[str, Any]:
        """Return {"nodes": [...], "edges": [...]} for a given case."""
        ...

    @abstractmethod
    def get_networkx_graph(self, case_id: str):
        """Return a NetworkX graph representation for shared visualization/reporting."""
        ...

    def delete_case(self, case_id: str) -> None:
        """Optional cleanup hook to evict a case from memory/storage."""
        return None