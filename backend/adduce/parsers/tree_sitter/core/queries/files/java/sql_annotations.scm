;; Tree-Sitter query for Java SQL annotations
;; Simplified working patterns

;; Basic annotation capture
(annotation
  name: (identifier) @annotation_name)

;; Method declaration capture
(method_declaration
  name: (identifier) @method_name)

;; String literal capture (for SQL queries)
(string_literal) @sql_query
