# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Only pyproject.toml and README drive what this layer needs to install, so
# copying just those - plus a stub hatchling can build editable metadata
# against - keeps the expensive part (torch, sentence-transformers) cached
# across changes to src/ or scripts/, not just scripts/. `-e .` installs by
# path, not by snapshot, so overwriting the stub with the real source below
# is safe once the dependencies are already in site-packages.
COPY pyproject.toml README.md ./
RUN mkdir -p src/pocket_oss_agent && touch src/pocket_oss_agent/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e ".[serve,embeddings,ui,pdf]"

COPY src ./src
COPY scripts ./scripts

EXPOSE 8000 8501
