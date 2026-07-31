# The image runs the versions the tests ran against.
#
# It used to be `python:3.12-slim` installing `backend/requirements.txt`,
# while every test ran the uv environment: Python 3.14, pydantic 2.13,
# fastapi 0.140 against the container's 3.12/2.5.3/0.109. Nothing in CI
# executed the code that serves traffic, and it cost three bugs at once —
# two annotations naming unimported types, which Python 3.14 never
# evaluates (PEP 649) and 3.12 evaluates at import, so the container would
# not boot while 2063 tests passed.
#
# Now: the same `uv.lock` the tests resolve, on a Python the lockfile
# supports. `requirements.txt` is gone; it existed only because it pinned
# pydantic 2.5.3, which has no wheel for 3.13+ and forced the old base
# image.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# git is a runtime dependency: repo ingestion shells out to `git clone`.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

# Dependencies before source, so a code change does not re-resolve them.
# `--frozen` fails rather than updating the lock: an image that quietly
# resolved something newer than CI tested is the divergence this file
# exists to close. `--no-install-project` because the source is COPYed
# below rather than installed — the app runs from the tree, and the
# library distribution is built separately from packaging/adduce-core.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

COPY backend/adduce ./adduce
COPY backend/tests ./tests
# Operator control plane: confidence table, aliases, roster, promotions.
COPY config ./config
ENV KG_CONFIG_DIR=/app/config

# Run unprivileged; cloned repo contents are untrusted input.
RUN useradd --create-home --uid 10001 kg \
    && mkdir -p /app/data/repos /app/var \
    && chown -R kg:kg /app
USER kg

EXPOSE 8000

CMD ["uvicorn", "adduce.main:app", "--host", "0.0.0.0", "--port", "8000"]
