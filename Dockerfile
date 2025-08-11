FROM python:3.11-alpine AS base

FROM base AS python-deps

# The uv installer requires curl (and certificates) to download the release archive
RUN apk add curl ca-certificates git

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH`
ENV PATH="/root/.local/bin/:$PATH"

# install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --locked --no-dev --compile-bytecode

FROM base AS runtime

# Copy virtual env from python-deps stage
COPY --from=python-deps /.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# switch to workdir
WORKDIR /app

# install app
COPY web_app/app.py ./
COPY web_app/.env ./
COPY web_app/flask_app ./flask_app/

# CMD ["python3"]
ENTRYPOINT ["./app.py"]
