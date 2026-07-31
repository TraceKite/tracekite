"""Tree-Sitter query loader for external query files.

Adapted from an earlier internal parser.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

from ..models import LanguageType

logger = logging.getLogger(__name__)


class QueryLoader:
    def __init__(self, queries_dir: Optional[Path] = None):
        if queries_dir is None:
            queries_dir = Path(__file__).parent / "files"

        self.queries_dir = Path(queries_dir)
        self._query_cache: Dict[str, str] = {}

    def load_query(self, language: LanguageType, query_type: str) -> Optional[str]:
        cache_key = f"{language.value}:{query_type}"

        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        query_file = self.queries_dir / language.value / f"{query_type}.scm"

        if query_file.exists():
            try:
                query_text = query_file.read_text(encoding="utf-8")
                self._query_cache[cache_key] = query_text
                logger.debug(f"Loaded query {cache_key} from {query_file}")
                return query_text
            except Exception as e:
                logger.error(f"Failed to load query from {query_file}: {e}")
                return None
        else:
            logger.debug(f"Query file not found: {query_file}")
            return None

    def load_all_queries(self, language: LanguageType) -> Dict[str, str]:
        queries = {}
        language_dir = self.queries_dir / language.value

        if not language_dir.exists():
            logger.debug(f"No query directory found for {language.value}")
            return queries

        for query_file in language_dir.glob("*.scm"):
            query_type = query_file.stem
            try:
                query_text = query_file.read_text(encoding="utf-8")
                queries[query_type] = query_text
                cache_key = f"{language.value}:{query_type}"
                self._query_cache[cache_key] = query_text
                logger.debug(f"Loaded query {cache_key}")
            except Exception as e:
                logger.error(f"Failed to load query from {query_file}: {e}")

        return queries

    def clear_cache(self) -> None:
        self._query_cache.clear()
        logger.info("Query loader cache cleared")
