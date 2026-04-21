FROM docker:29-cli

# docker:28-cli ships compose v2.40.3, which rejects our docker-compose.yml
# include: pattern with "networks.proxy conflicts with imported resource".
# Pin upstream compose (v5.x line) where the merge rules were relaxed.
ARG COMPOSE_VERSION=v5.1.3
RUN apk add --no-cache tini \
 && ARCH="$(uname -m)" \
 && wget -qO /usr/local/libexec/docker/cli-plugins/docker-compose \
    "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}" \
 && chmod +x /usr/local/libexec/docker/cli-plugins/docker-compose

COPY vpn-netns-watcher.sh /usr/local/bin/vpn-netns-watcher.sh
RUN chmod +x /usr/local/bin/vpn-netns-watcher.sh

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/usr/local/bin/vpn-netns-watcher.sh"]
