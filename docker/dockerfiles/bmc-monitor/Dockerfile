FROM alpine:latest
RUN apk add --no-cache ipmitool curl jq
COPY bmc-ip-monitor.sh /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/bmc-ip-monitor.sh"]
