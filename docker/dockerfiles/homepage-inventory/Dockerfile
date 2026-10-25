FROM node:24-alpine AS test
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY --chown=node:node *.cjs ./
USER node
RUN node --test *.test.cjs

FROM node:24-alpine
WORKDIR /app
COPY --from=test --chown=node:node /app ./
USER node
EXPOSE 8080
CMD ["node", "server.cjs"]
