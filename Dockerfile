FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY config ./config
COPY samples ./samples

# one run by default; `pipeline schedule` for service mode
ENTRYPOINT ["pipeline"]
CMD ["run"]
