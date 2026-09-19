import { prisma } from "@/lib/db";
import { InboxView } from "./inbox-view";

export const dynamic = "force-dynamic";

const columns = {
  id: true,
  createdAt: true,
  transcript: true,
  confidence: true,
  status: true,
} as const;

/**
 * A work queue, not a wizard listing.
 *
 * The gate is conditional: most runs finish unattended and only the ones the
 * system does not trust land here. So what is waiting sorts OLDEST first — the
 * review that has been pending longest is the most urgent — and everything else
 * sorts newest first, like any history.
 */
export default async function SupervisorInboxPage() {
  const [awaiting, recent] = await Promise.all([
    prisma.supervisorRun.findMany({
      where: { runState: "paused" },
      orderBy: { createdAt: "asc" },
      select: columns,
    }),
    prisma.supervisorRun.findMany({
      where: { NOT: { runState: "paused" } },
      orderBy: { createdAt: "desc" },
      take: 20,
      select: columns,
    }),
  ]);

  return <InboxView awaiting={awaiting} recent={recent} />;
}
