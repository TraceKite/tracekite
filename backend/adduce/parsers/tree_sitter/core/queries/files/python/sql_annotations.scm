;; Tree-Sitter query for Python SQL decorators
;; Simplified working patterns

;; Basic decorator capture
(decorator
  (identifier) @annotation_name)

;; Function definition capture
(function_definition
  name: (identifier) @method_name)

;; String capture (for SQL queries)
(string) @sql_query
