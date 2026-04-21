FROM docker:28-cli

RUN apk add --no-cache docker-cli-compose tini

COPY vpn-netns-watcher.sh /usr/local/bin/vpn-netns-watcher.sh
RUN chmod +x /usr/local/bin/vpn-netns-watcher.sh

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/usr/local/bin/vpn-netns-watcher.sh"]
