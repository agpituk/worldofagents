FROM node:22-slim

WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund --no-progress --legacy-peer-deps

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
