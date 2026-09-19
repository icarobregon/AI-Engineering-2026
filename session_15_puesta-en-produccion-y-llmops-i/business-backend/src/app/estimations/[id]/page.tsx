import { notFound } from "next/navigation";

import { prisma } from "@/lib/db";
import { EstimationView } from "./estimation-view";

export const dynamic = "force-dynamic";

export default async function EstimationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const row = await prisma.estimation.findUnique({ where: { id } });
  if (!row) notFound();

  return (
    <EstimationView
      promptVersion={row.promptVersion}
      cached={row.cached}
      payload={row.responsePayload}
    />
  );
}
