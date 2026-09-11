"""The two primitives four parsers had each grown their own copy of.

`proto._body_of` and `graphql._body_at` were byte-identical; iac's inline
loop was the same decision written as a generator; `_as_list`/`_str`
existed identically in both the gateway and Kubernetes parsers. Sharing
them is only safe if the edge cases are pinned, because that is where
independent copies drift — so the unterminated-block reading is asserted
here rather than left to whichever caller happens to depend on it.
"""

from evigraph.parsers.brace_blocks import balanced_block
from evigraph.parsers.yaml_shapes import as_list, as_str


class TestBalancedBlock:
    def test_returns_the_body_without_the_braces(self):
        body, end = balanced_block("service X { rpc A; }", 10)
        assert body == " rpc A; "
        assert end == 19

    def test_nesting_does_not_close_early(self):
        text = "a { b { c } d } e"
        body, end = balanced_block(text, 2)
        assert body == " b { c } d "
        assert text[end] == "}"

    def test_unterminated_block_yields_no_body(self):
        """The conservative reading, and the one shared decision: a truncated
        descriptor contributes nothing rather than swallowing the rest of the
        file, which would attribute later declarations to it."""
        body, end = balanced_block("service X { rpc A;", 10)
        assert body == ""
        assert end == len("service X { rpc A;")

    def test_no_brace_at_the_offset_consumes_nothing(self):
        body, _end = balanced_block("no braces here", 0)
        assert body == ""


class TestYamlShapes:
    def test_scalar_becomes_a_single_item_list(self):
        assert as_list("one") == ["one"]

    def test_list_passes_through(self):
        assert as_list(["a", "b"]) == ["a", "b"]

    def test_absent_becomes_empty(self):
        assert as_list(None) == []
        assert as_str(None) == ""

    def test_none_never_becomes_the_string_none(self):
        # `str(None)` is "None" — a four-character name that has matched a
        # real service exactly never, and the reason this guard exists.
        assert as_str(None) != "None"

    def test_non_strings_are_stringified(self):
        assert as_str(8080) == "8080"
        assert as_str(True) == "True"
