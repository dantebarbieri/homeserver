FROM node:24-alpine AS test
WORKDIR /app
COPY --chown=node:node server.cjs server.test.cjs ./
USER node
RUN node --test server.test.cjs

FROM node:24-alpine
WORKDIR /app
COPY --from=test --chown=node:node /app/server.cjs ./
USER node
EXPOSE 8080
CMD ["node", "server.cjs"]
