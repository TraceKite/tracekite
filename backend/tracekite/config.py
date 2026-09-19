"""Application configuration loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from tracekite import engine_config
from tracekite.db import store_config


class Settings(BaseSettings):
    # `.env` also contains Docker Compose variables that are not app settings.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend_port: int = 8000
    workspace_dir: str = "/tmp/repos"

    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    github_token: str = ""            # PAT fallback for github.com (git_hosts.yml preferred)
    allowed_git_hosts: str = "github.com"
    clone_timeout_s: int = 600

    api_token: str = ""
    # Master switch. False disables bearer auth for EVERY /api route,
    # including ingest, delete and rebuild. Only defensible because the
    # compose stack binds its ports to 127.0.0.1, so nothing off this machine
    # can reach the API at all. Defaults to true so any deployment that does
    # not deliberately opt out still fails closed.
    auth_enabled: bool = True
    # Narrower opt-in, used when auth_enabled is true: serve GET/HEAD/OPTIONS
    # without a token while POST/DELETE/PUT/PATCH still require one.
    allow_anonymous_reads: bool = False
    kg_cors_origins: str = ""
    graph_hmac_key: str = ""
    audit_log_path: str = "var/audit.log"

    parse_file_cap_bytes: int = 512 * 1024
    parse_timeout_s: int = 30          # per-file parse budget (ingestion_service)
    match_fanout_cap: int = 32         # max contracts one call site may match (R7)
    # Edges below the floor are written as `candidate`, not `active`, and are
    # excluded from default answers (design §5.5, principle 5).
    confidence_floor: float = 0.6

    ingest_workers: int = 2
    write_batch_size: int = 5000
    # Operator control plane (confidence.yml, service_aliases.yml, ...).
    # Empty falls back to the workspace-root `config/` beside `backend/`.
    # Aliased because the deployed name is KG_CONFIG_DIR, not CONFIG_DIR.
    config_dir: str = Field(default="", validation_alias="KG_CONFIG_DIR")

    # Bounded path enumeration for /api/v2/trace (design §7 VQ1).
    trace_max_paths: int = 2000

    # How many repositories may be in scope at once. A guardrail, not a law of
    # the graph: render cost is nodes and edges, and repo size varies wildly
    # (one repo in the demo corpus carries 48 services, the other five total
    # 17). The UI therefore enforces this AND shows the live service/link
    # counts, so the cheap rule stops accidents while the real cost stays
    # visible. Operators with small repos can raise it.
    max_scope_repos: int = 10

    # Maximum exact nodes shown after expanding one repository/module group.
    # Search remains exhaustive; the canvas stays a bounded reasoning surface.
    graph_detail_node_limit: int = 80

    def allowed_hosts_list(self) -> list[str]:
        return [h.strip().lower() for h in self.allowed_git_hosts.split(",") if h.strip()]

    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.kg_cors_origins.split(",") if o.strip()]

    def require_neo4j_password(self) -> str:
        """Startup refuses default/unset Neo4j passwords (design §9)."""
        if store_config.is_unsafe_neo4j_password(self.neo4j_password):
            raise RuntimeError(
                "NEO4J_PASSWORD is unset or a known default; refusing to start"
            )
        return self.neo4j_password


settings = Settings()

# Push the environment down to the layers that may not read it themselves.
# Core and store own their own config types (architecture §2); this is the one
# place that binds them to this process's environment, and it is why importing
# `tracekite.config` is a server-layer act rather than something core does.
engine_config.configure(
    config_dir=settings.config_dir,
    workspace_dir=settings.workspace_dir,
    graph_hmac_key=settings.graph_hmac_key,
    parse_timeout_s=settings.parse_timeout_s,
    parse_file_cap_bytes=settings.parse_file_cap_bytes,
)
store_config.configure(
    neo4j_uri=settings.neo4j_uri,
    neo4j_user=settings.neo4j_user,
    neo4j_password=settings.neo4j_password,
    write_batch_size=settings.write_batch_size,
)
