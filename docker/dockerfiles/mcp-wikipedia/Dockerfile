FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir wikipedia-mcp==2.0.0
COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh
EXPOSE 8080
CMD ["/usr/local/bin/start.sh"]
