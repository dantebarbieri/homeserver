FROM curlimages/curl:latest
USER root
RUN mkdir -m 700 /var/lib/ntfy-outbox && chown curl_user /var/lib/ntfy-outbox
USER curl_user
COPY port-sync.sh /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/port-sync.sh"]
