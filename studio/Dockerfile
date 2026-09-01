# Build the app from source so the image is reproducible from a clean clone
# rather than depending on a dist/ that happened to be lying around.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
# This image is the public demo: it has no Identity Platform behind it and its
# nginx attaches the fixed demo identity to /api/web/v1. Dockerfile.web is the
# image to use for a deployment with real sign-in.
ARG VITE_HOSTED_DEMO=true
ENV VITE_HOSTED_DEMO=${VITE_HOSTED_DEMO}
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html

# Cloud Run sends traffic to $PORT, which defaults to 8080; nginx listens on 80
# out of the box, so the server block is replaced rather than inherited. The
# config is a template because the hosted deployment injects the stage executor
# credential at start-up rather than baking it into the image.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Defaults keep the image runnable with no configuration: the proxy points at a
# loopback nobody is listening on, so /api/stages returns 502 instead of
# preventing nginx from starting. The hosted service overrides both.
ENV STAGE_UPSTREAM=127.0.0.1:4345 \
    STAGE_TOKEN="" \
    WEB_BFF_UPSTREAM=127.0.0.1:8081 \
    WEB_BFF_TOKEN="" \
    # No trailing anchor: Dockerfile ENV escaping of $ is ambiguous, and no
    # other variable name starts with either of these.
    NGINX_ENVSUBST_FILTER="^(STAGE_UPSTREAM|STAGE_TOKEN|WEB_BFF_UPSTREAM|WEB_BFF_TOKEN)"

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
