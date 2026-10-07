# API + in-process TimesFM (CPU). Build from this directory:  docker build -t lottery-api backend/
# Needs DATABASE_URL at runtime (the embedded dev Postgres is not installed in this image).
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN useradd -m -u 1000 app
USER app
WORKDIR /home/app/api
ENV HF_HOME=/home/app/.cache/huggingface UV_LINK_MODE=copy
COPY --chown=app pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra timesfm --no-install-project
# Bake the weights into the image so the first forecast does not wait on a download.
RUN .venv/bin/python -c "import timesfm; timesfm.TimesFM_2p5_200M_torch.from_pretrained('google/timesfm-2.5-200m-pytorch', torch_compile=False)"
COPY --chown=app . .
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
