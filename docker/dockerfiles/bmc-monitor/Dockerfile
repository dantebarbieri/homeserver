FROM alpine:latest
RUN apk add --no-cache ipmitool curl jq && mkdir -m 700 /var/lib/ntfy-outbox
COPY bmc-ip-monitor.sh /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/bmc-ip-monitor.sh"]
