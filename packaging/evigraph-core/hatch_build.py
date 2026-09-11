"""Make the external source tree self-contained in wheels and sdists."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        project = Path(self.root)
        package = self.config["package"]
        embedded = project / "src" / package
        checkout = project.parents[1]

        if self.target_name == "sdist":
            if embedded.is_dir():
                return
            build_data["force_include"][str(checkout / "backend/evigraph")] = \
                f"src/{package}"
            build_data["force_include"][str(checkout / "config")] = \
                f"src/{package}/_control_plane"
            return

        source = embedded if embedded.is_dir() else checkout / "backend/evigraph"
        build_data["force_include"][str(source)] = package
        if source == embedded:
            return
        build_data["force_include"][str(checkout / "config")] = \
            f"{package}/_control_plane"
