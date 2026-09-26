import { defineConfig } from "prisma/config";

// Prisma 7 no longer reads .env on its own, and the connection URL no longer
// lives in schema.prisma. Inside Docker the variable is already in the
// environment, so a missing file is not an error.
try {
  process.loadEnvFile(".env");
} catch {
  /* no .env: the environment already carries DATABASE_URL */
}

export default defineConfig({
  schema: "prisma/schema.prisma",
  // `process.env` rather than Prisma's `env()` helper on purpose: `env()` throws
  // when the variable is missing, and `prisma generate` runs at image build time,
  // where there is no database and no URL. The migrate commands, which do need
  // it, run at container start with the variable set.
  datasource: { url: process.env.DATABASE_URL },
  migrations: { path: "prisma/migrations" },
});
