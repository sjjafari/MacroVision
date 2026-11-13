FROM node:24.18.0-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24.18.0-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24.18.0-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
RUN addgroup -S macrovision && adduser -S macrovision -G macrovision
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER macrovision
EXPOSE 3000
CMD ["node","server.js"]
