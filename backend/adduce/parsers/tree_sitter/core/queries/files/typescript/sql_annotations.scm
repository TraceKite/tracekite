;; Tree-Sitter query for TypeScript SQL decorators
;; Simplified working patterns

;; Basic decorator capture
(decorator
  (identifier) @annotation_name)

;; Method definition capture
(method_definition
  name: (property_identifier) @method_name)

;; String capture (for SQL queries)
(string) @sql_query
