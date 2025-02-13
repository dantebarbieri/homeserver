# ======================================
# Dockerfile.danteb.com
# ======================================

# -------------------------------
# Stage 1: Build the SvelteKit app
# -------------------------------
FROM node:18-alpine AS builder

# Create and switch to the /app directory
WORKDIR /app

# Copy only the package files to install dependencies (cache-friendly)
COPY danteb.com/package*.json ./

# Install *all* dependencies (dev+prod, needed to build)
RUN npm ci

# Copy the rest of the app source code
COPY danteb.com/ .

# Build the SvelteKit app
RUN npm run build

# -----------------------------------
# Stage 2: Create a minimal production image
# -----------------------------------
FROM node:18-alpine AS runner

# Set the working directory
WORKDIR /app

# Copy only the package files for a clean install of production deps
COPY danteb.com/package*.json ./
RUN npm ci --omit=dev

# Copy the compiled build output from builder stage
COPY --from=builder /app/build ./build

# Expose the port your SvelteKit server listens on
EXPOSE 3000

# Start the SvelteKit server
CMD ["node", "build"]
