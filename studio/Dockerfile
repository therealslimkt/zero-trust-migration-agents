# Build environment
FROM node:18-alpine as build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

# Production environment
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Expose port 80 for Google Cloud Run
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
