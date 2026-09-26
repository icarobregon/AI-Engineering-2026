/**
 * One Prisma client per process, created on first use.
 *
 * Lazy on purpose: `next build` imports every page module to collect its
 * metadata, and there is no database — nor a DATABASE_URL — at image build time.
 * Constructing the client at import time turned that into a build failure.
 *
 * Next's dev server reloads modules on every edit; without the global cache each
 * reload would open a new pool and Postgres would run out of connections after a
 * handful of saves.
 */
import "server-only";

import { PrismaPg } from "@prisma/adapter-pg";

import { PrismaClient } from "@/generated/prisma/client";

const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

function client(): PrismaClient {
  if (!globalForPrisma.prisma) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error("DATABASE_URL is not set: the business backend has no datastore.");
    }
    // `?schema=` is Prisma Migrate's own convention; `pg` ignores it entirely.
    // Without passing it to the adapter the CLI creates the tables in `business`
    // and every query at runtime looks for them in `public`.
    const schema = new URL(connectionString).searchParams.get("schema") ?? undefined;
    globalForPrisma.prisma = new PrismaClient({
      adapter: new PrismaPg({ connectionString }, { schema }),
    });
  }
  return globalForPrisma.prisma;
}

export const prisma = new Proxy({} as PrismaClient, {
  get: (_target, property) => Reflect.get(client(), property),
}) as PrismaClient;
