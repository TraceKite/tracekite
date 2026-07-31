"""Abstract base parser interface.

Adapted from an earlier internal parser.
"""

from abc import ABC, abstractmethod
from typing import List

from .models import LanguageType, ParsingResult


class BaseParser(ABC):
    @abstractmethod
    def parse_content(
        self, content: str, file_path: str, language: LanguageType
    ) -> ParsingResult:
        pass

    @abstractmethod
    def supports_language(self, language: LanguageType) -> bool:
        pass

    def get_supported_languages(self) -> List[LanguageType]:
        return [lang for lang in LanguageType if self.supports_language(lang)]


class BaseExtractor(ABC):
    """Abstract base class for symbol and call graph extractors."""

    @abstractmethod
    def extract_symbols(
        self, content: str, file_path: str, language: LanguageType
    ) -> List:
        pass
