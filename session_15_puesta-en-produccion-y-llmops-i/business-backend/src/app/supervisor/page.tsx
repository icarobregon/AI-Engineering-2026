import { prisma } from "@/lib/db";
import { InboxView } from "./inbox-view";

export const dynamic = "force-dynamic";

const columns = {
  id: true,
  createdAt: true,
  transcript: true,
  estimate: true,
  confidence: true,
  status: true,
} as const;

/**
 * El título que el sistema le puso al proyecto, si ya llegó a ponérselo.
 *
 * Se lee a mano y no con `draftEstimateSchema`: validar la estimación entera de
 * veinte filas para quedarse con una cadena es caro, y además frágil en la
 * dirección equivocada — una fila cuyo desglose no pasara el esquema perdería el
 * título teniéndolo delante. Aquí sólo hace falta ese campo, así que sólo ese se
 * mira.
 *
 * Devuelve null mientras no hay estimación: una ejecución recién arrancada o una
 * que murió antes de estimar no tiene todavía cómo llamarse.
 */
function tituloDe(estimate: unknown): string | null {
  if (typeof estimate !== "object" || estimate === null) return null;
  const project = (estimate as { project?: unknown }).project;
  return typeof project === "string" && project.trim() !== "" ? project.trim() : null;
}

/**
 * La primera línea de la transcripción, para cuando todavía no hay título.
 *
 * `estimate` se escribe tarde: sólo lo consolida `syncRun`, y a `syncRun` sólo lo
 * llama el panel de progreso del detalle. Así que una ejecución en curso —y una
 * FALLIDA para siempre, porque esa rama nunca escribe la estimación— no tiene
 * cómo llamarse. Antes daba igual: la columna pintaba la transcripción, que es
 * NOT NULL desde el INSERT, así que ninguna fila salía en blanco. Sin este
 * respaldo, cambiar la columna dejaría el histórico de ejecuciones muertas como
 * filas con una fecha y nada más, que es justo lo contrario de lo que se busca.
 *
 * La PRIMERA LÍNEA y no los primeros 90 caracteres: ahí es donde el acta pone el
 * nombre del proyecto («Reunión de descubrimiento — Proyecto "MARELUZ"»). El
 * recorte ciego se comía esa línea a mitad y seguía con la de al lado, que es lo
 * que hacía la columna vieja indistinguible entre reuniones.
 */
function primeraLineaDe(transcript: string): string | null {
  const linea = transcript.split("\n", 1)[0].trim();
  if (linea === "") return null;
  return linea.length > 80 ? `${linea.slice(0, 80)}…` : linea;
}

/**
 * Ni la estimación ni la transcripción salen de aquí: al cliente sólo viajan las
 * dos cadenas cortas. Antes se serializaba la transcripción entera de cada fila.
 */
const filas = <T extends { estimate: unknown; transcript: string }>({
  estimate,
  transcript,
  ...row
}: T) => {
  const title = tituloDe(estimate);
  return { ...row, title, origen: title === null ? primeraLineaDe(transcript) : null };
};

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

  return <InboxView awaiting={awaiting.map(filas)} recent={recent.map(filas)} />;
}
