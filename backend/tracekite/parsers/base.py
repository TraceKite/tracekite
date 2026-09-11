"""Base parser interface and common extraction utilities."""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedEntity:
    name: str
    type: str  # "class", "interface", "method", "function"
    start_line: int
    end_line: int
    signature: str = ""
    modifiers: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    docstring: str = ""
    is_public: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedImport:
    module: str
    name: str = ""  # specific imported name
    is_wildcard: bool = False
    line: int = 0


@dataclass
class ParsedApiEndpoint:
    method: str  # GET, POST, PUT, DELETE, PATCH
    path: str
    handler_name: str = ""
    controller_name: str = ""
    line: int = 0
    framework: str = "unknown"


@dataclass
class ParsedMethodCall:
    caller_name: str = ""           # enclosing method signature text (for resolution)
    callee_name: str = ""           # called method name or qualified name
    file_path: str = ""
    line: int = 0
    call_type: str = "direct"       # direct, virtual, static, etc.
    context: str = ""               # surrounding source snippet
    confidence: str = "high"


@dataclass
class ParseResult:
    entities: list[ParsedEntity] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    api_endpoints: list[ParsedApiEndpoint] = field(default_factory=list)
    method_calls: list[ParsedMethodCall] = field(default_factory=list)
    symbol_references: list[dict] = field(default_factory=list)
    package: str = ""
    errors: list[str] = field(default_factory=list)


class BaseParser(ABC):
    """Abstract base class for language-specific parsers."""

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        pass

    @abstractmethod
    def parse(self, file_path: str, content: str) -> ParseResult:
        pass

    def can_parse(self, file_path: str) -> bool:
        ext = file_path.split(".")[-1].lower() if "." in file_path else ""
        return f".{ext}" in self.supported_extensions


def extract_docstring(content: str, start_pos: int) -> str:
    pattern = r'(?s)(?:"""(.*?)"""|\/\*\*(.*?)\*\/|\/\/\s*(.+))'
    remaining = content[start_pos:]
    match = re.search(pattern, remaining)
    if match:
        for group in match.groups():
            if group:
                return group.strip()
    return ""
