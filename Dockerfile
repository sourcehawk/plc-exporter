FROM python:3.13-alpine AS runner

WORKDIR /app

COPY src src
COPY pyproject.toml .

RUN pip install .

ENTRYPOINT [ "plc_exporter" ]
CMD ["--config", "/config.yaml"]