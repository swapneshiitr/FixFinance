FROM node:20-alpine

WORKDIR /app

# Install deps first (cached unless package.json changes), then copy source.
COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
