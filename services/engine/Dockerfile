FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HISTORY_CACHE_DIR=/data/history

# build tools are only needed when a wheel is missing for this architecture (zipline's C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libhdf5-dev pkg-config curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) dependencies only — this layer is cached until pyproject.toml changes
COPY pyproject.toml README.md ./
RUN python - <<'PY'
import tomllib, subprocess, sys
deps = tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]
subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
subprocess.check_call([sys.executable, "-m", "pip", "install", *deps])
PY

# 2) the engine itself — cheap to rebuild
COPY zipline_engine ./zipline_engine
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-deps .

RUN useradd -m -u 10001 zipline && mkdir -p /data && chown -R zipline:zipline /data /app
USER zipline
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "zipline_engine.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
