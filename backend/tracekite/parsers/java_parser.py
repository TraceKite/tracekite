"""Java source file parser - extracts classes, interfaces, methods, imports, Spring annotations, and API endpoints."""

import logging
import re
from tracekite.parsers.base import BaseParser, ParseResult, ParsedEntity, ParsedImport, ParsedApiEndpoint

logger = logging.getLogger(__name__)

SPRING_CONTROLLER_ANNOTATIONS = ["@RestController", "@Controller"]
SPRING_MAPPING_ANNOTATIONS = {
    "@GetMapping": "GET",
    "@PostMapping": "POST",
    "@PutMapping": "PUT",
    "@DeleteMapping": "DELETE",
    "@PatchMapping": "PATCH",
    "@RequestMapping": "ANY",
}
SPRING_COMPONENT_ANNOTATIONS = ["@Service", "@Repository", "@Component", "@Configuration"]


class JavaParser(BaseParser):
    @property
    def supported_extensions(self) -> list[str]:
        return [".java"]

    def parse(self, file_path: str, content: str) -> ParseResult:
        result = ParseResult()
        lines = content.split("\n")
        
        try:
            result.package = self._extract_package(content)

            result.imports = self._extract_imports(content)

            result.entities = self._extract_classes_and_methods(content, lines)

            result.api_endpoints = self._extract_spring_endpoints(content, lines)
            
        except Exception as e:
            result.errors.append(f"Java parse error: {str(e)}")
            logger.warning("Failed to parse Java file %s: %s", file_path, e)
        
        return result

    def _extract_package(self, content: str) -> str:
        match = re.search(r'package\s+([a-zA-Z_][a-zA-Z0-9_\.]*)\s*;', content)
        return match.group(1) if match else ""

    def _extract_imports(self, content: str) -> list[ParsedImport]:
        imports = []
        for match in re.finditer(r'import\s+(static\s+)?([a-zA-Z_][a-zA-Z0-9_\.*]*)\s*;', content):
            is_static = match.group(1) is not None
            module = match.group(2)
            is_wildcard = module.endswith(".*")
            line = content[:match.start()].count("\n") + 1
            imports.append(ParsedImport(
                module=module,
                is_wildcard=is_wildcard,
                line=line,
            ))
        return imports

    def _extract_classes_and_methods(self, content: str, lines: list[str]) -> list[ParsedEntity]:
        entities = []

        class_pattern = r'(?m)^\s*(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?(class|interface|enum)\s+(\w+)'
        
        for match in re.finditer(class_pattern, content):
            decl_type = match.group(1)
            name = match.group(2)
            start_line = content[:match.start()].count("\n") + 1
            
            brace_pos = content.find("{", match.end())
            if brace_pos == -1:
                continue

            end_pos = self._find_matching_brace(content, brace_pos)
            end_line = content[:end_pos].count("\n") + 1 if end_pos > 0 else start_line

            annotations = self._extract_annotations(content, match.start())
            
            entity = ParsedEntity(
                name=name,
                type=decl_type,
                start_line=start_line,
                end_line=end_line,
                signature=lines[start_line - 1].strip() if start_line <= len(lines) else "",
                annotations=annotations,
            )
            entities.append(entity)
            
            if decl_type in ("class", "interface"):
                body = content[brace_pos + 1:end_pos] if end_pos > 0 else content[brace_pos + 1:]
                methods = self._extract_methods_from_body(body, start_line, name)
                entities.extend(methods)
        
        return entities

    def _extract_methods_from_body(self, body: str, class_start_line: int, class_name: str) -> list[ParsedEntity]:
        methods = []

        method_pattern = r'(?m)^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?(?:abstract\s+)?(?:<[\w,\s]+>\s+)?([\w<>,\s\[\]]+)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{'
        
        for match in re.finditer(method_pattern, body):
            return_type = match.group(1).strip()
            name = match.group(2)
            
            # Skip constructors (same name as class)
            if name == class_name:
                continue
            
            start_line_in_body = body[:match.start()].count("\n") + 1
            start_line = class_start_line + start_line_in_body
            
            brace_pos = body.find("{", match.end())
            if brace_pos == -1:
                continue
            
            end_pos = self._find_matching_brace(body, brace_pos)
            end_line = class_start_line + body[:end_pos].count("\n") + 1 if end_pos > 0 else start_line
            
            annotations = self._extract_annotations(body, match.start())
            
            methods.append(ParsedEntity(
                name=name,
                type="method",
                start_line=start_line,
                end_line=end_line,
                signature=f"{return_type} {name}()",
                annotations=annotations,
            ))
        
        return methods

    def _extract_spring_endpoints(self, content: str, lines: list[str]) -> list[ParsedApiEndpoint]:
        endpoints = []
        
        controller_class = ""
        base_path = ""

        class_pattern = r'@(?:RestController|Controller)(?:\([^)]*\))?\s*(?:@\w+\([^)]*\)\s*)*\s*(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+)*class\s+(\w+)'
        for match in re.finditer(class_pattern, content):
            controller_class = match.group(1)
            before_class = content[:match.start()]
            mapping_match = re.search(r'@RequestMapping\s*\(\s*"([^"]+)"\s*\)', before_class)
            if mapping_match:
                base_path = mapping_match.group(1)
            break
        
        if not controller_class:
            return endpoints
        
        for ann_name, http_method in SPRING_MAPPING_ANNOTATIONS.items():
            # Match @GetMapping("/path") or @GetMapping(value="/path") or bare @GetMapping
            pattern = rf'{re.escape(ann_name)}(?:\s*\(\s*(?:value\s*=\s*)?"([^"]*)"\s*\))?'  # group 1 is optional path
            for match in re.finditer(pattern, content):
                path = match.group(1) or ""
                full_path = f"{base_path}{path}" if base_path else path
                line = content[:match.start()].count("\n") + 1
                
                after_ann = content[match.end():match.end() + 500]
                method_match = re.search(r'(?:public|private|protected)?\s*(?:[\w<>,\s\[\]]+)\s+(\w+)\s*\(', after_ann)
                handler_name = method_match.group(1) if method_match else "unknown"
                
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
            line = line.strip()
            if line.startswith("@"):
                ann_name = line.split("(")[0].strip()
                annotations.append(ann_name)
            elif line and not line.startswith("//") and not line.startswith("*"):
                if not line.startswith("@"):
                    break
        return annotations

    def _find_matching_brace(self, content: str, open_pos: int) -> int:
        depth = 1
        pos = open_pos + 1
        while pos < len(content) and depth > 0:
            if content[pos] == "{":
                depth += 1
            elif content[pos] == "}":
                depth -= 1
            pos += 1
        return pos - 1 if depth == 0 else -1
