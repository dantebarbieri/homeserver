FROM alpine:latest
RUN apk add --no-cache curl jq coreutils tzdata
COPY autoconsume.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/autoconsume.sh
ENTRYPOINT ["/usr/local/bin/autoconsume.sh"]
