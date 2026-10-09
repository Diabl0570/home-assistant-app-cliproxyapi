FROM debian:bookworm-slim
ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=dev
ARG BUILD_REF=local
COPY updater.json manager-plus.json /tmp/
RUN test "$BUILD_ARCH" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-yaml tzdata \
    && CLIPROXY_VERSION="$(python3 -c 'import json; print(json.load(open("/tmp/updater.json"))["version"])')" \
    && CLIPROXY_SHA256="$(python3 -c 'import json; print(json.load(open("/tmp/updater.json"))["sha256"])')" \
    && curl -fsSL --retry 3 "https://github.com/router-for-me/CLIProxyAPI/releases/download/v${CLIPROXY_VERSION}/CLIProxyAPI_${CLIPROXY_VERSION}_linux_amd64.tar.gz" -o /tmp/cliproxy.tar.gz \
    && echo "${CLIPROXY_SHA256}  /tmp/cliproxy.tar.gz" | sha256sum -c - \
    && mkdir /tmp/release \
    && tar -xzf /tmp/cliproxy.tar.gz -C /tmp/release \
    && install -m 755 /tmp/release/cli-proxy-api /usr/local/bin/cli-proxy-api \
    && mkdir -p /usr/share/doc/cliproxyapi \
    && cp /tmp/release/LICENSE /usr/share/doc/cliproxyapi/LICENSE \
    && MANAGER_VERSION="$(python3 -c 'import json; print(json.load(open("/tmp/manager-plus.json"))["version"])')" \
    && MANAGER_SHA256="$(python3 -c 'import json; print(json.load(open("/tmp/manager-plus.json"))["sha256"])')" \
    && curl -fsSL --retry 3 "https://github.com/seakee/CPA-Manager-Plus/releases/download/v${MANAGER_VERSION}/cpa-manager-plus_v${MANAGER_VERSION}_linux_amd64.tar.gz" -o /tmp/manager.tar.gz \
    && echo "${MANAGER_SHA256}  /tmp/manager.tar.gz" | sha256sum -c - \
    && mkdir /tmp/manager \
    && tar -xzf /tmp/manager.tar.gz -C /tmp/manager --strip-components=1 \
    && install -m 755 /tmp/manager/cpa-manager-plus /usr/local/bin/cpa-manager-plus \
    && mkdir -p /usr/share/doc/cpa-manager-plus \
    && cp /tmp/manager/LICENSE /usr/share/doc/cpa-manager-plus/LICENSE \
    && rm -rf /tmp/release /tmp/cliproxy.tar.gz /tmp/manager /tmp/manager.tar.gz /var/lib/apt/lists/*
LABEL org.opencontainers.image.revision="${BUILD_REF}" io.hass.arch="${BUILD_ARCH}" io.hass.version="${BUILD_VERSION}" org.opencontainers.image.source="https://github.com/Diabl0570/home-assistant-app-cliproxyapi" io.hass.type="app" io.hass.name="CLIProxyAPI" io.hass.description="CLIProxyAPI for Home Assistant"
WORKDIR /data
COPY run.py diagnostics.py /usr/local/bin/
ENTRYPOINT ["python3", "/usr/local/bin/run.py"]
