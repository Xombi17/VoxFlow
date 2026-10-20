ARG PYTHON_VERSION=3.12.14
ARG UV_VERSION=0.12.21

FROM python:${PYTHON_VERSION}-slim-bookworm AS build

ARG UV_VERSION
COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        libdbus-1-3 \
        libei1 \
        libgomp1 \
        libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

COPY .python-version pyproject.toml README.md uv.lock ./
COPY src ./src
COPY tests ./tests
COPY tools ./tools

RUN uv sync --frozen --dev
RUN NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python \
    python -m pytest -q
RUN uv build --offline --out-dir /tmp/voxflow-dist

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

WORKDIR /app
RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        libdbus-1-3 \
        libei1 \
        libgomp1 \
        libportaudio2 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin voxflow

COPY --from=build --chown=voxflow:voxflow /app/.venv ./.venv
COPY --from=build --chown=voxflow:voxflow /app/src ./src
COPY --from=build --chown=voxflow:voxflow /app/tests ./tests
COPY --from=build --chown=voxflow:voxflow /app/tools ./tools
COPY --from=build --chown=voxflow:voxflow /tmp/voxflow-dist /tmp/voxflow-dist

ENV HOME=/home/voxflow \
    NETWORK_DISABLED=1 \
    PATH=/app/.venv/bin:${PATH} \
    PYTHONPATH=/app/src
USER voxflow

CMD ["python", "-m", "pytest", "-q"]
