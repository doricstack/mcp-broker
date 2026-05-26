ARG PYTHON_IMAGE=python:3-slim
FROM ${PYTHON_IMAGE}

ARG VERSION=0.0.0
ARG VCS_REF=unknown
ARG SOURCE_URL=https://github.com/NavinAgrawal/mcp-broker

LABEL org.opencontainers.image.title="mcp-broker" \
      org.opencontainers.image.description="Local MCP broker that exposes configured upstream MCP servers through one compact client entry." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.url="${SOURCE_URL}" \
      org.opencontainers.image.documentation="${SOURCE_URL}#readme" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV MCP_BROKER_RUNTIME_ROOT=/var/lib/mcp-broker \
    MCP_BROKER_CONFIG=/etc/mcp-broker/broker.yaml \
    MCP_BROKER_SOCKET=/tmp/mcp-broker.sock \
    MCP_BROKER_PROFILE=docker \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src /app/src
COPY config/broker.example.yaml /app/config/broker.example.yaml
COPY docker/docker-entrypoint.sh /usr/local/bin/mcp-broker-docker

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir /app \
    && chmod +x /usr/local/bin/mcp-broker-docker \
    && groupadd --system mcp-broker \
    && useradd --system --gid mcp-broker --home-dir /var/lib/mcp-broker mcp-broker \
    && mkdir -p /var/lib/mcp-broker /etc/mcp-broker \
    && chown -R mcp-broker:mcp-broker /var/lib/mcp-broker /etc/mcp-broker

USER mcp-broker

ENTRYPOINT ["/usr/local/bin/mcp-broker-docker"]
