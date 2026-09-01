# Build the app from source so the image is reproducible from a clean clone
# rather than depending on a dist/ that happened to be lying around.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Cloud Run sends traffic to $PORT, which defaults to 8080; nginx listens on 80
# out of the box, so the server block is replaced rather than inherited. The
# try_files fallback keeps client-side routes working on a hard refresh.
RUN printf 'server {\n\
  listen 8080;\n\
  root /usr/share/nginx/html;\n\
  index index.html;\n\
  location / { try_files $uri $uri/ /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
