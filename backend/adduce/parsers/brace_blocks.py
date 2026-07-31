"""The body of a `{ ... }` block, brace-balanced.

Protobuf services, GraphQL type bodies and Terraform resource blocks are
all delimited the same way, and all three parsers had grown their own
scanner — proto's `_body_of` and graphql's `_body_at` were
byte-identical, and iac's inline loop was the same decision written as a
generator with a `closed` flag.

An unterminated block yields an empty body rather than the rest of the
file. That is the conservative reading: a truncated or malformed
descriptor should contribute nothing, not a body whose closing brace
somebody else's block supplied.
"""


def balanced_block(content: str, open_brace: int) -> tuple[str, int]:
    """`(body, closing_index)` for the block opening at `open_brace`.

    `body` excludes both braces. When the block never closes, returns
    `("", len(content))` — no body, and an index that terminates any scan
    driven by it.
    """
    depth, index = 0, open_brace
    while index < len(content):
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[open_brace + 1:index], index
        index += 1
    return "", len(content)
