FROM node:26-alpine AS test
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY --chown=node:node *.cjs ./
# COPY keeps the checkout's modes; a 0600 package.json is unreadable as USER node.
RUN chmod -R a+rX /app
USER node
RUN node --test *.test.cjs

FROM node:26-alpine
WORKDIR /app
COPY --from=test --chown=node:node /app ./
USER node
EXPOSE 8080
CMD ["node", "server.cjs"]
