import { prisma } from "@/lib/db";
import { DashboardView } from "./dashboard-view";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const [estimations, awaiting] = await Promise.all([
    prisma.estimation.count(),
    prisma.supervisorRun.count({ where: { runState: "paused" } }),
  ]);

  return <DashboardView estimations={estimations} awaiting={awaiting} />;
}
