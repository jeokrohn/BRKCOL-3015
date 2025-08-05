FROM python:3.11-alpine AS base

FROM base AS python-deps

RUN pip install pipenv
RUN apk add git build-base libffi-dev

# Install python dependencies in /.venv
COPY Pipfile .
COPY Pipfile.lock .
RUN PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy

FROM base as runtime

# Copy virtual env from python-deps stage
COPY --from=python-deps /.venv /.venv
ENV PATH="/.venv/bin:$PATH"

# switch to workdir
WORKDIR /app

# install app
COPY web_app/app.py ./
COPY web_app/.env ./
COPY web_app/flask_app ./flaskr/

ENTRYPOINT ["./app.py"]
