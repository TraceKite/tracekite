"""The CLI binds the control-plane directory before any command runs.

`config_dir()` reads engine_config, never the environment — core may not
read the environment (architecture §2). The server gets its binding from
importing `evigraph.config`; the CLI has no such import, so `main()` must do
it. Without that, `config_dir()` falls back to walking four directories
up from `base.py`, which happens to land on `config/` in a source
checkout and overshoots to `/config` in the container, where the code is
installed at `/app/app`. Every link-dependent subcommand then dies with
ConfidenceTableMissing — invisible to a developer running from a
checkout, fatal in the image.

Asserting the binding rather than a path is deliberate: the checkout
default is right by accident, so a test that only checked "confidence
loads" would pass on the broken code.
"""

import json

import pytest

from evigraph import engine_config
from evigraph.cli import main


@pytest.fixture(autouse=True)
def restore_config():
    saved = engine_config.get_config()
    yield
    engine_config.reset()
    engine_config.configure(**{f: getattr(saved, f)
                               for f in type(saved).__dataclass_fields__})


class TestConfigDirBinding:
    def test_flag_is_bound_into_engine_config(self, tmp_path, capsys):
        control = tmp_path / "control"
        control.mkdir()
        (control / "confidence.yml").write_text("version: 1\nfloor: 0.6\n")
        main(["--config-dir", str(control), "resolvers"])
        capsys.readouterr()
        assert engine_config.get_config().config_dir == str(control)

    def test_environment_supplies_the_default(self, tmp_path, monkeypatch,
                                              capsys):
        control = tmp_path / "from-env"
        control.mkdir()
        monkeypatch.setenv("KG_CONFIG_DIR", str(control))
        main(["resolvers"])
        capsys.readouterr()
        assert engine_config.get_config().config_dir == str(control)

    def test_a_link_command_reads_the_supplied_table(self, tmp_path, capsys):
        """The end-to-end shape of the container failure: point the CLI at a
        control plane in a directory the base.py walk could never reach, and
        a command that must load confidence still works."""
        import shutil
        from evigraph.services.linker.base import config_dir

        control = tmp_path / "elsewhere"
        shutil.copytree(config_dir(), control)
        main(["--config-dir", str(control), "coverage"])
        out = capsys.readouterr().out
        assert json.loads(out)
        assert engine_config.get_config().config_dir == str(control)
