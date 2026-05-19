FROM alpine:latest
RUN apk add --no-cache curl jq coreutils
COPY check-stock.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/check-stock.sh
ENTRYPOINT ["/usr/local/bin/check-stock.sh"]
