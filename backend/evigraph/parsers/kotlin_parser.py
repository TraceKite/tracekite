"""Kotlin parser - extracts classes, functions, imports with Spring annotation support."""

import logging
import re
from evigraph.parsers.base import BaseParser, ParseResult, ParsedEntity, ParsedImport, ParsedApiEndpoint

logger = logging.getLogger(__name__)


class KotlinParser(BaseParser):
    @property
    def supported_extensions(self) -> list[str]:
        return [".kt"]

    def parse(self, file_path: str, content: str) -> ParseResult:
        result = ParseResult()
        lines = content.split("\n")
        
        try:
            result.package = self._extract_package(content)

            result.imports = self._extract_imports(content)

            result.entities = self._extract_entities(content, lines)

            result.api_endpoints = self._extract_spring_endpoints(content, lines)
            
        except Exception as e:
            result.errors.append(f"Kotlin parse error: {str(e)}")
            logger.warning("Failed to parse Kotlin file %s: %s", file_path, e)
        
        return result

    def _extract_package(self, content: str) -> str:
        match = re.search(r'package\s+([a-zA-Z_][a-zA-Z0-9_\.]*)', content)
        return match.group(1) if match else ""

    def _extract_imports(self, content: str) -> list[ParsedImport]:
        imports = []
        for match in re.finditer(r'import\s+([a-zA-Z_][a-zA-Z0-9_\.*]*)', content):
            module = match.group(1)
            is_wildcard = module.endswith(".*")
            line = content[:match.start()].count("\n") + 1
            imports.append(ParsedImport(
                module=module,
                is_wildcard=is_wildcard,
                line=line,
            ))
        return imports

    def _extract_entities(self, content: str, lines: list[str]) -> list[ParsedEntity]:
        entities = []

        class_pattern = r'(?m)^\s*(?:data\s+)?(?:sealed\s+)?(?:abstract\s+)?(?:open\s+)?(?:inner\s+)?class\s+(\w+)'
        for match in re.finditer(class_pattern, content):
            name = match.group(1)
            start_line = content[:match.start()].count("\n") + 1
            end_line = self._find_brace_end(content, match.start())
            annotations = self._extract_annotations(content, match.start())
            
            entities.append(ParsedEntity(
                name=name,
                type="class",
                start_line=start_line,
                end_line=end_line,
                signature=lines[start_line - 1].strip() if start_line <= len(lines) else f"class {name}",
                annotations=annotations,
            ))
            
            brace_start = content.find("{", match.end())
            if brace_start > 0 and end_line > start_line:
                body = content[brace_start + 1:content.rfind("}", brace_start, len(content))]
                methods = self._extract_functions(body, start_line)
                entities.extend(methods)
        
        interface_pattern = r'(?m)^\s*interface\s+(\w+)'
        for match in re.finditer(interface_pattern, content):
            name = match.group(1)
            start_line = content[:match.start()].count("\n") + 1
            end_line = self._find_brace_end(content, match.start())
            
            entities.append(ParsedEntity(
                name=name,
                type="interface",
                start_line=start_line,
                end_line=end_line,
                signature=f"interface {name}",
            ))
        
        # Object declarations (singletons)
        object_pattern = r'(?m)^\s*object\s+(\w+)'
        for match in re.finditer(object_pattern, content):
            name = match.group(1)
            start_line = content[:match.start()].count("\n") + 1
            end_line = self._find_brace_end(content, match.start())
            
            entities.append(ParsedEntity(
                name=name,
                type="object",
                start_line=start_line,
                end_line=end_line,
                signature=f"object {name}",
            ))
        
        func_pattern = r'(?m)^\s*(?:private\s+|public\s+|internal\s+|protected\s+)?(?:suspend\s+)?fun\s+(\w+)\s*\('
        for match in re.finditer(func_pattern, content):
            name = match.group(1)
            # Check it's not a method (not indented inside a class)
            line_start = content.rfind("\n", 0, match.start()) + 1
            if content[line_start:match.start()].strip().startswith("fun") or content[line_start:match.start()].strip() == "":
                start_line = content[:match.start()].count("\n") + 1
                end_line = self._find_brace_end(content, match.start())
                annotations = self._extract_annotations(content, match.start())
                
                entities.append(ParsedEntity(
                    name=name,
                    type="function",
                    start_line=start_line,
                    end_line=end_line,
                    signature=lines[start_line - 1].strip() if start_line <= len(lines) else f"fun {name}()",
                    annotations=annotations,
                ))
        
        return entities

    def _extract_functions(self, body: str, class_start_line: int) -> list[ParsedEntity]:
        methods = []
        func_pattern = r'(?m)^\s+(?:override\s+)?(?:private\s+|public\s+|internal\s+|protected\s+)?(?:suspend\s+)?fun\s+(\w+)\s*\('
        
        for match in re.finditer(func_pattern, body):
            name = match.group(1)
            start_line_in_body = body[:match.start()].count("\n") + 1
            start_line = class_start_line + start_line_in_body
            end_line = class_start_line + self._find_brace_end(body, match.start())
            annotations = self._extract_annotations(body, match.start())
            
            methods.append(ParsedEntity(
                name=name,
                type="method",
                start_line=start_line,
                end_line=end_line,
                signature=f"fun {name}()",
                annotations=annotations,
            ))
        
        return methods

    def _extract_spring_endpoints(self, content: str, lines: list[str]) -> list[ParsedApiEndpoint]:
        endpoints = []

        mapping_annotations = {
            "@GetMapping": "GET",
            "@PostMapping": "POST",
            "@PutMapping": "PUT",
            "@DeleteMapping": "DELETE",
            "@PatchMapping": "PATCH",
            "@RequestMapping": "ANY",
        }
        
        controller_class = ""
        base_path = ""

        ctrl_match = re.search(r'@(?:RestController|Controller).*?class\s+(\w+)', content, re.DOTALL)
        if ctrl_match:
            controller_class = ctrl_match.group(1)
            before_class = content[:ctrl_match.start()]
            mapping_match = re.search(r'@RequestMapping\s*\(\s*"([^"]+)"\s*\)', before_class)
            if mapping_match:
                base_path = mapping_match.group(1)
        
        if not controller_class:
            return endpoints
        
        for ann_name, http_method in mapping_annotations.items():
            pattern = rf'{re.escape(ann_name)}\s*\(\s*(?:value\s*=\s*)?"([^"]*)"\s*\)'
            for match in re.finditer(pattern, content):
                path = match.group(1)
                full_path = f"{base_path}{path}" if base_path else path
                line = content[:match.start()].count("\n") + 1
                
                after = content[match.end():match.end() + 500]
                func_match = re.search(r'fun\s+(\w+)\s*\(', after)
                handler_name = func_match.group(1) if func_match else "unknown"
                
                endpoints.append(ParsedApiEndpoint(
                    method=http_method,
                    path=full_path,
                    handler_name=handler_name,
                    controller_name=controller_class,
                    line=line,
                    framework="Spring",
                ))
        
        return endpoints

    def _extract_annotations(self, content: str, position: int) -> list[str]:
        annotations = []
        before = content[:position]
        lines = before.split("\n")[-10:]
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("@"):
                ann_name = stripped.split("(")[0].strip()
                annotations.append(ann_name)
            elif stripped and not stripped.startswith("//") and not stripped.startswith("*"):
                if not stripped.startswith("@"):
                    break
        return annotations

    def _find_brace_end(self, content: str, start_pos: int) -> int:
        brace_pos = content.find("{", start_pos)
        if brace_pos == -1:
            return content[:start_pos].count("\n") + 1
        
        depth = 1
        pos = brace_pos + 1
        
        while pos < len(content) and depth > 0:
            if content[pos] == "{" and content[pos - 1] != "$":  # Skip string interpolation
                depth += 1
            elif content[pos] == "}":
                depth -= 1
            pos += 1
        
        return content[:pos - 1].count("\n") + 1
