"""JavaScript/TypeScript parser - extracts functions, classes, imports, React components, Express routes."""

import logging
import re
from evigraph.parsers.base import BaseParser, ParseResult, ParsedEntity, ParsedImport, ParsedApiEndpoint

logger = logging.getLogger(__name__)


class JavaScriptParser(BaseParser):
    @property
    def supported_extensions(self) -> list[str]:
        return [".js", ".jsx", ".ts", ".tsx"]

    def parse(self, file_path: str, content: str) -> ParseResult:
        result = ParseResult()
        lines = content.split("\n")
        
        try:
            result.imports = self._extract_imports(content)

            result.entities = self._extract_entities(content, lines)

            result.api_endpoints = self._extract_api_endpoints(content, lines)
            
        except Exception as e:
            result.errors.append(f"JS/TS parse error: {str(e)}")
            logger.warning("Failed to parse JS/TS file %s: %s", file_path, e)
        
        return result

    def _extract_imports(self, content: str) -> list[ParsedImport]:
        imports = []
        
        # ES6 imports: import { x } from 'module' or import x from 'module'
        es6_pattern = r'import\s+(?:(\{[^}]*\})|(\w+)|(\*\s+as\s+\w+))\s+from\s+[\'"]([^\'"]+)[\'"]'
        for match in re.finditer(es6_pattern, content):
            module = match.group(4)
            line = content[:match.start()].count("\n") + 1
            imports.append(ParsedImport(module=module, line=line))
        
        # CommonJS: const x = require('module')
        cjs_pattern = r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)'
        for match in re.finditer(cjs_pattern, content):
            module = match.group(1)
            line = content[:match.start()].count("\n") + 1
            imports.append(ParsedImport(module=module, line=line))
        
        return imports

    def _extract_entities(self, content: str, lines: list[str]) -> list[ParsedEntity]:
        entities = []

        class_pattern = r'(?m)^\s*(?:export\s+(?:default\s+)?)?class\s+(\w+)'
        for match in re.finditer(class_pattern, content):
            name = match.group(1)
            start_line = content[:match.start()].count("\n") + 1
            end_line = self._find_brace_end(content, match.start())
            
            entities.append(ParsedEntity(
                name=name,
                type="class",
                start_line=start_line,
                end_line=end_line,
                signature=lines[start_line - 1].strip() if start_line <= len(lines) else f"class {name}",
            ))
            
            brace_start = content.find("{", match.end())
            if brace_start > 0 and end_line > start_line:
                body = content[brace_start + 1:content.rfind("}", brace_start, len(content))]
                methods = self._extract_methods(body, start_line)
                entities.extend(methods)
        
        func_pattern = r'(?m)^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+(\w+)\s*\('
        for match in re.finditer(func_pattern, content):
            name = match.group(1)
            start_line = content[:match.start()].count("\n") + 1
            end_line = self._find_brace_end(content, match.start())
            
            entities.append(ParsedEntity(
                name=name,
                type="function",
                start_line=start_line,
                end_line=end_line,
                signature=lines[start_line - 1].strip() if start_line <= len(lines) else f"function {name}()",
            ))
        
        # Arrow functions: const name = () => or const name = async () =>
        arrow_pattern = r'(?m)^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|\w+)\s*=>\s*\{'
        for match in re.finditer(arrow_pattern, content):
            name = match.group(1)
            # Only capture if it looks like a component (PascalCase) or significant function
            if name[0].isupper() or len(name) > 2:
                start_line = content[:match.start()].count("\n") + 1
                end_line = self._find_brace_end(content, match.start())
                
                entity_type = "component" if name[0].isupper() else "function"
                entities.append(ParsedEntity(
                    name=name,
                    type=entity_type,
                    start_line=start_line,
                    end_line=end_line,
                    signature=lines[start_line - 1].strip() if start_line <= len(lines) else f"const {name} = () =>",
                ))
        
        # React functional components with JSX: function Component() { return (<div...  }
        component_pattern = r'(?m)^\s*(?:export\s+(?:default\s+)?)?(?:function|const)\s+([A-Z]\w+)\s*(?:=\s*(?:\([^)]*\)\s*=>)?|\()'
        for match in re.finditer(component_pattern, content):
            name = match.group(1)
            if any(e.name == name and e.type == "component" for e in entities):
                continue
            
            start_line = content[:match.start()].count("\n") + 1
            end_line = self._find_brace_end(content, match.start())
            
            entities.append(ParsedEntity(
                name=name,
                type="component",
                start_line=start_line,
                end_line=end_line,
                signature=lines[start_line - 1].strip() if start_line <= len(lines) else f"function {name}()",
            ))
        
        return entities

    def _extract_methods(self, body: str, class_start_line: int) -> list[ParsedEntity]:
        methods = []

        method_pattern = r'(?m)^\s+(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{'
        for match in re.finditer(method_pattern, body):
            name = match.group(1)
            if name in ("if", "while", "for", "switch", "catch", "try"):
                continue
            
            start_line_in_body = body[:match.start()].count("\n") + 1
            start_line = class_start_line + start_line_in_body
            end_line = class_start_line + self._find_brace_end(body, match.start())
            
            methods.append(ParsedEntity(
                name=name,
                type="method",
                start_line=start_line,
                end_line=end_line,
                signature=f"{name}()",
            ))
        
        return methods

    def _extract_api_endpoints(self, content: str, lines: list[str]) -> list[ParsedApiEndpoint]:
        endpoints = []
        
        # Express/Next.js patterns: app.get('/path', ...), router.post('/path', ...)
        http_methods = ["get", "post", "put", "delete", "patch", "head", "options", "all", "use"]
        
        for method in http_methods:
            pattern = rf'(?:app|router|server|api|handler)\.{re.escape(method)}\s*\(\s*[\'"]([^\'"]+)[\'"]'
            for match in re.finditer(pattern, content):
                path = match.group(1)
                line = content[:match.start()].count("\n") + 1
                
                framework = "Express"
                if "next" in content[:match.start()].lower() or "pages/api" in content:
                    framework = "Next.js"
                
                endpoints.append(ParsedApiEndpoint(
                    method=method.upper(),
                    path=path,
                    line=line,
                    framework=framework,
                ))
        
        # App Router route handlers are NOT extracted here. The path of a
        # `route.ts` verb export comes from its DIRECTORY, which this parser
        # does not see; `js_route_extractor._next_app_path` derives it from
        # the file path and owns the pattern. This branch used to emit the
        # literal placeholder "/api/..." as the path — a hardcoded string
        # wearing a template's shape — and fabricated one endpoint per verb
        # export, duplicating every route the real extractor had already
        # produced correctly.
        return endpoints

    def _find_brace_end(self, content: str, start_pos: int) -> int:
        brace_pos = content.find("{", start_pos)
        if brace_pos == -1:
            return content[:start_pos].count("\n") + 1
        
        depth = 1
        pos = brace_pos + 1
        in_string = False
        string_char = None
        
        while pos < len(content) and depth > 0:
            char = content[pos]
            
            if char in ('"', "'", "`"):
                if not in_string:
                    in_string = True
                    string_char = char
                elif string_char == char and content[pos - 1] != "\\":
                    in_string = False
                    string_char = None
            
            if not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
            
            pos += 1
        
        return content[:pos - 1].count("\n") + 1
