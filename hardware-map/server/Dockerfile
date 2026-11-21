FROM python:3.13-alpine
WORKDIR /app
COPY . /app
RUN chmod -R a+rX /app
USER 65534:65534
EXPOSE 8080
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "/app/server/server.py", "--host", "0.0.0.0", "--port", "8080", "--state-dir", "/state", "--web-root", "/app"]
