FROM node:24-alpine AS test
WORKDIR /app
COPY --chown=node:node server.cjs server.test.cjs stats.cjs stats.test.cjs ./
USER node
RUN node --test server.test.cjs stats.test.cjs

FROM node:24-alpine
WORKDIR /app
COPY --from=test --chown=node:node /app/server.cjs /app/stats.cjs ./
USER node
EXPOSE 8080
CMD ["node", "server.cjs"]
