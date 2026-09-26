import { prisma } from "@/lib/db";
import { EstimationsView } from "./estimations-view";

export const dynamic = "force-dynamic";

export default async function EstimationsPage() {
  const rows = await prisma.estimation.findMany({
    orderBy: { createdAt: "desc" },
    take: 20,
    select: {
      id: true,
      createdAt: true,
      projectType: true,
      description: true,
      promptVersion: true,
      cached: true,
    },
  });

  return <EstimationsView rows={rows} />;
}
