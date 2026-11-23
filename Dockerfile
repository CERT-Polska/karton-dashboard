FROM python:3.14-slim-trixie

WORKDIR /app/service
COPY ./MANIFEST.in ./MANIFEST.in
COPY ./pyproject.toml ./pyproject.toml
COPY ./karton/dashboard/__version__.py ./karton/dashboard/__version__.py
RUN pip install --only-deps .
COPY ./README.md ./README.md
COPY ./karton ./karton
RUN pip install .
CMD karton-dashboard run --host 0.0.0.0
