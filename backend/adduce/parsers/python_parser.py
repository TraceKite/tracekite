"""Python source file parser - extracts functions, classes, imports, FastAPI/Flask routes."""

import logging
import re
from adduce.parsers.base import BaseParser, ParseResult, ParsedEntity, ParsedImport, ParsedApiEndpoint

logger = logging.getLogger(__name__)

FASTAPI_METHODS = ["get", "post", "put", "delete", "patch", "head", "options"]
FLASK_METHODS = ["route"]


class PythonParser(BaseParser):
    @property
    def supported_extensions(self) -> list[str]:
        return [".py"]

    def parse(self, file_path: str, content: str) -> ParseResult:
        result = ParseResult()
        lines = content.split("\n")
        
        try:
            result.imports = self._extract_imports(content)

            result.entities = self._extract_entities(content, lines)

            result.api_endpoints = self._extract_api_endpoints(content, lines)
            
        except Exception as e:
            result.errors.append(f"Python parse error: {str(e)}")
            logger.warning("Failed to parse Python file %s: %s", file_path.split("/")[-1], e)
        
        return result

    def _extract_imports(self, content: str) -> list[ParsedImport]:
        imports = []
        
        # 'import x' and 'from x import y' patterns (explicit space to avoid capturing newlines)
        import_pattern = r'(?m)^\s*import\s+([\w. ,]+)'
        from_pattern = r'(?m)^\s*from\s+([\w.]+)\s+import\s+([\w. ,*]+)'
        
        for match in re.finditer(import_pattern, content):
            modules = match.group(1).split(",")
            line = content[:match.start()].count("\n") + 1
            for mod in modules:
                mod = mod.strip()
                if mod:
                    imports.append(ParsedImport(module=mod, line=line))
        
        for match in re.finditer(from_pattern, content):
            module = match.group(1)
            names = match.group(2).split(",")
            line = content[:match.start()].count("\n") + 1
            for name in names:
                name = name.strip()
                is_wildcard = name == "*"
                imports.append(ParsedImport(
                    module=module,
                    name=name,
                    is_wildcard=is_wildcard,
                    line=line,
                ))
        
        return imports

    def _extract_entities(self, content: str, lines: list[str]) -> list[ParsedEntity]:
        entities = []

        class_pattern = r'(?m)^\s*class\s+(\w+)\s*(?:\([^)]*\))?\s*:'
        for match in re.finditer(class_pattern, content):
            name = match.group(1)
            start_line = content[:match.start()].count("\n") + 1
            end_line = self._find_block_end(content, match.start())
            
            annotations = self._extract_decorators(content, match.start())
            
            entities.append(ParsedEntity(
                name=name,
                type="class",
                start_line=start_line,
                end_line=end_line,
                signature=f"class {name}",
                annotations=annotations,
            ))
            
            # Extract methods within class (match.end() is right after the class colon)
            class_body_start = match.end()
            if class_body_start > 0:
                # Convert end_line (1-indexed) to character position
                end_pos = sum(len(line) + 1 for line in lines[:min(end_line, len(lines))]) if end_line > start_line else len(content)
                methods = self._extract_functions_from_body(
                    content[class_body_start:end_pos],
                    start_line,
                    name,
                )
                entities.extend(methods)
        
        # Top-level functions (not inside classes)
        func_pattern = r'(?m)^\s*(def\s+(\w+)\s*\([^)]*\)\s*(?:->\s*[\w\[\],\s]+)?\s*:)'  # group 1 is the whole def clause, group 2 is the name
        for match in re.finditer(func_pattern, content):
            name = match.group(2)
            # Skip if it's a method (indented before the def keyword)
            def_start = match.start(1)
            line_start = content.rfind("\n", 0, def_start) + 1
            if def_start > line_start:
                continue
            
            start_line = content[:match.start()].count("\n") + 1
            end_line = self._find_block_end(content, match.start())
            annotations = self._extract_decorators(content, match.start())
            
            entities.append(ParsedEntity(
                name=name,
                type="function",
                start_line=start_line,
                end_line=end_line,
                signature=lines[start_line - 1].strip() if start_line <= len(lines) else f"def {name}()",
                annotations=annotations,
            ))
        
        return entities

    def _extract_functions_from_body(self, body: str, class_start_line: int, class_name: str) -> list[ParsedEntity]:
        methods = []
        func_pattern = r'(?m)^\s+def\s+(\w+)\s*\([^)]*\)\s*(?:->\s*[\w\[\],\s]+)?\s*:'
        
        for match in re.finditer(func_pattern, body):
            name = match.group(1)
            # NOTE: We no longer skip constructors so that __init__ is captured.
            start_line_in_body = body[:match.start()].count("\n") + 1
            start_line = class_start_line + start_line_in_body
            end_line = class_start_line + self._find_block_end(body, match.start())
            annotations = self._extract_decorators(body, match.start())
            
            methods.append(ParsedEntity(
                name=name,
                type="method",
                start_line=start_line,
                end_line=end_line,
                signature=f"def {name}(self, ...)",
                annotations=annotations,
            ))
        
        return methods

    def _extract_api_endpoints(self, content: str, lines: list[str]) -> list[ParsedApiEndpoint]:
        endpoints = []

        # @app.get("/path") or @router.post("/path")
        for method in FASTAPI_METHODS:
            pattern = rf'@(\w+)\.{re.escape(method)}\s*\(\s*"([^"]+)"'
            for match in re.finditer(pattern, content):
                router_name = match.group(1)
                path = match.group(2)
                line = content[:match.start()].count("\n") + 1
                
                after = content[match.end():match.end() + 500]
                func_match = re.search(r'def\s+(\w+)\s*\(', after)
                handler_name = func_match.group(1) if func_match else "unknown"

                endpoints.append(ParsedApiEndpoint(
                    method=method.upper(),
                    path=path,
                    handler_name=handler_name,
                    line=line,
                    framework="FastAPI",
                ))
        
        # Flask @app.route("/path", methods=["POST"])
        pattern = r'@(\w+)\.route\s*\(\s*"([^"]+)"(?:[^)]*methods\s*=\s*\[([^\]]+)\])?'
        for match in re.finditer(pattern, content):
            path = match.group(2)
            methods_str = match.group(3)
            http_method = "GET"
            if methods_str:
                first_method = re.search(r'"(\w+)"', methods_str)
                if first_method:
                    http_method = first_method.group(1).upper()
            
            line = content[:match.start()].count("\n") + 1
            after = content[match.end():match.end() + 500]
            func_match = re.search(r'def\s+(\w+)\s*\(', after)
            handler_name = func_match.group(1) if func_match else "unknown"
            
            endpoints.append(ParsedApiEndpoint(
                method=http_method,
                path=path,
                handler_name=handler_name,
                line=line,
                framework="Flask",
            ))
        
        return endpoints

    def _extract_decorators(self, content: str, position: int) -> list[str]:
        annotations = []
        before = content[:position]
        lines = before.split("\n")[-10:]
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("@"):
                ann_name = stripped.split("(")[0].strip()
                annotations.append(ann_name)
            elif stripped and not stripped.startswith("#"):
                break
        return annotations

    def _find_block_end(self, content: str, start_pos: int) -> int:
        """Find the end line of a Python block by tracking indentation."""
        lines = content[start_pos:].split("\n")
        if len(lines) <= 1:
            return content[:start_pos].count("\n") + 1
        
        first_content_line = ""
        for i, line in enumerate(lines[1:], 1):
            if line.strip() and not line.strip().startswith("#"):
                first_content_line = line
                break
        
        if not first_content_line:
            return content[:start_pos].count("\n") + 1
        
        block_indent = len(first_content_line) - len(first_content_line.lstrip())
        start_line_num = content[:start_pos].count("\n") + 1
        
        # Find where indentation drops back to <= block_indent (and line is not empty/comment)
        for i, line in enumerate(lines[1:], 1):
            if not line.strip() or line.strip().startswith("#"):
                continue
            current_indent = len(line) - len(line.lstrip())
            if current_indent < block_indent:
                return start_line_num + i - 1
        
        return start_line_num + len(lines) - 1
