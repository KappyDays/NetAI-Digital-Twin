# =============================================================================
# Web Dashboard — Multi-stage Dockerfile
#
# Stage 1 (build):  Node.js / Vite — compile React SPA to static assets
# Stage 2 (serve):  nginx:alpine — serve static files + reverse proxy to API
#
# Build context: dashboard/
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Build — Node.js + Vite
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first (layer cache optimization)
COPY package.json package-lock.json* ./
RUN npm ci --silent 2>/dev/null || npm install --silent

# Copy source and build
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Serve — nginx:alpine (minimal footprint)
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS production

# Remove default nginx configuration
RUN rm -rf /etc/nginx/conf.d/default.conf /usr/share/nginx/html/*

# Copy custom nginx configuration
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/default.conf /etc/nginx/conf.d/default.conf

# Copy built static files from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Copy fallback error page
COPY public/50x.html /usr/share/nginx/html/50x.html

# Expose HTTP port
EXPOSE 80

# Health check — verify nginx is responding
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost/ || exit 1

# Run nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
