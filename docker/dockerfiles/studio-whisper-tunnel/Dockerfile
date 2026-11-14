FROM alpine:3

# ssh refuses to run as a UID without a passwd entry, so the image creates the
# host user that owns the key under ${DATA}.
ARG UID=1000
ARG GID=1000
RUN apk add --no-cache openssh-client && \
    if ! getent group "$GID" >/dev/null; then addgroup -g "$GID" tunnel; fi && \
    adduser -D -H -h /nonexistent -s /sbin/nologin -u "$UID" \
        -G "$(getent group "$GID" | cut -d: -f1)" tunnel

COPY studio-whisper-tunnel.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/studio-whisper-tunnel.sh
USER tunnel
ENTRYPOINT ["/usr/local/bin/studio-whisper-tunnel.sh"]
