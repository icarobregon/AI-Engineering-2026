/**
 * `GET /supervisor/<id>/proposal.pdf` — la propuesta, para mandarla.
 *
 * Un GET que sólo lee. El PDF se compone en cada petición a partir de lo que ya
 * está guardado: no hay nada que persistir aquí, y guardar el binario obligaría
 * a invalidarlo cada vez que cambie la maquetación.
 *
 * La ruta se llama `proposal.pdf` para que el fichero que descarga el navegador
 * tenga extensión aunque alguien copie el enlace.
 */
import { NextResponse } from "next/server";

import { prisma } from "@/lib/db";
import { commercialProposalSchema, draftEstimateSchema } from "@/lib/estimator/contracts";
import { buildProposalPdf } from "@/lib/proposal-pdf";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await prisma.supervisorRun.findUnique({
    where: { id },
    select: { estimationId: true, proposal: true, estimate: true },
  });
  if (!run) return new NextResponse("No existe esa estimación.", { status: 404 });

  const proposal = commercialProposalSchema.safeParse(run.proposal);
  if (!proposal.success) {
    return new NextResponse("Esta estimación todavía no tiene propuesta redactada.", {
      status: 404,
    });
  }

  // El desglose es opcional en el documento: si lo guardado no encaja con el
  // contrato, se imprime la propuesta sin tabla en lugar de no imprimir nada.
  const estimate = draftEstimateSchema.safeParse(run.estimate);
  const pdf = await buildProposalPdf({
    proposal: proposal.data,
    estimate: estimate.success ? estimate.data : null,
    estimationId: run.estimationId,
  });

  return new NextResponse(pdf as unknown as BodyInit, {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Length": String(pdf.length),
      // `attachment` porque el botón dice «Descargar». El id es un uuid, así que
      // no hay nada que escapar en la cabecera.
      "Content-Disposition": `attachment; filename="propuesta-${run.estimationId}.pdf"`,
      // Se recompone en cada petición; cachearlo serviría una versión vieja
      // después de un «Regenerar».
      "Cache-Control": "no-store",
    },
  });
}
