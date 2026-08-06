"""FastAPI entry point: bearer auth, CORS allowlist, job-queue lifecycle."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from adduce.config import settings
from adduce.db.constraints import create_constraints
from adduce.db.neo4j_client import close_driver
from adduce.middleware.auth import BearerAuthMiddleware
from adduce.routes import graph, health, impact, jobs, links, repos, rollup, trace
from adduce.services.job_handlers import register_all
from adduce.services.job_queue import job_queue, reap_stale_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Adduce backend")
    settings.require_neo4j_password()
    try:
        create_constraints()
        reaped = reap_stale_jobs()
        if reaped:
            logger.warning("Marked %d stale jobs from a previous run as failed",
                           reaped)
    except Exception as exc:
        logger.error("Neo4j not ready at startup (health stays degraded): %s", exc)
    register_all(job_queue)
    job_queue.start()
    yield
    job_queue.stop()
    close_driver()
    logger.info("Backend shut down")


app = FastAPI(
    title="Adduce",
    description="Ingest repositories and explore their structure as a typed knowledge graph",
    version="2.0.0",
    lifespan=lifespan,
)

# Added first so CORS (added last) runs outermost and handles preflight.
app.add_middleware(BearerAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (health.router, repos.router, jobs.router, graph.router,
               links.router, impact.router, trace.router, rollup.router):
    app.include_router(router)


@app.get("/")
async def root():
    return {
        "name": "Adduce API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health",
    }
