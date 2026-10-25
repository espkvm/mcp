# SPDX-FileCopyrightText: 2026 ESP-KVM contributors
# SPDX-License-Identifier: Apache-2.0
#
# The MCP server in a container, for hosts without Python. It talks MCP over
# stdin/stdout, so run it with -i (podman and docker take the same flags):
#
#   podman build -t espkvm-mcp .          or: docker build -f Containerfile -t espkvm-mcp .
#   podman run -i --rm -e ESPKVM_URL=https://192.168.1.42 -e ESPKVM_PASSWORD=... \
#     -e ESPKVM_INSECURE=1 ghcr.io/espkvm/mcp
#
# Use the device's IP: espkvm.local is mDNS, which does not cross the
# container's network bridge (on Linux, --network host works too).

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/espkvm/mcp" \
      org.opencontainers.image.description="MCP server: the screen, keyboard and mouse of a machine through an ESP-KVM" \
      org.opencontainers.image.licenses="Apache-2.0"
COPY --from=build /install /usr/local
ENV PYTHONUNBUFFERED=1
# Nothing here needs root.
USER nobody
ENTRYPOINT ["espkvm-mcp"]
