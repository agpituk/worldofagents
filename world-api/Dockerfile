FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
# `uv sync --dev` only picks up [dependency-groups.dev]; this project uses
# the older [project.optional-dependencies] dev = [...] form, so we need
# --extra dev to actually install pytest et al.
RUN uv sync --extra dev

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
