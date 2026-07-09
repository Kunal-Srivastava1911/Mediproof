# MediProof dashboard: build with Vite, serve the static bundle with nginx.
# Build context is the repo root (see docker-compose.yml).
FROM node:20-alpine AS build
WORKDIR /app
COPY ui/package.json ui/package-lock.json* ./
RUN npm install
COPY ui/ ./
# The browser reaches the API at the published host port.
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
