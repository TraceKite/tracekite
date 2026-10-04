import pytest

from tracekite.services import file_parse
from tracekite.services.scan import scan


def test_a_crash_in_one_file_names_that_file(tmp_path, monkeypatch):
    # strapi's ingest failed with only "'NoneType' object has no attribute
    # 'startswith'": nothing said which of its 23,000 files raised it.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const x = 1;\n")

    def explode(*args, **kwargs):
        raise ValueError("extractor bug")

    monkeypatch.setattr(file_parse, "process_source_file", explode)

    with pytest.raises(ValueError, match="extractor bug") as raised:
        scan(str(tmp_path), "crash_repo")

    # The same exception, so callers that rely on its type still work, now
    # carrying the file that raised it.
    assert "while scanning src/app.ts" in raised.value.__notes__


def test_a_clean_file_still_scans(tmp_path):
    (tmp_path / "app.ts").write_text("export function hello() { return 1; }\n")

    sink = scan(str(tmp_path), "clean_repo")

    assert any(node.name == "hello" for node in sink.nodes)
