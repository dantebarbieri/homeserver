FROM alpine:latest
RUN apk add --no-cache nmap curl jq
COPY pi-ip-monitor.sh /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/pi-ip-monitor.sh"]
