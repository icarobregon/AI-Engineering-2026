"use client";

import Link from "next/link";
import { ArrowLeftOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Flex,
  List,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";

import {
  commercialProposalSchema,
  draftEstimateSchema,
  humanDecisionSchema,
  reviewPayloadSchema,
  type DraftEstimate,
} from "@/lib/estimator/contracts";
import { AWAITING_REVIEW, FAILED, statusLabel } from "@/lib/supervisor";
import { hours, percent } from "@/lib/format";
import type { GraphState, HistoricalBand } from "@/lib/estimator/contracts";
import { CollapseCard } from "@/components/collapse-card";
import { ProposalCard } from "./proposal-card";
import { ReviewEstimateForm } from "./review-estimate-form";
import { RoutingTrace } from "./routing-trace";
import { RunProgressPanel } from "./run-progress";

function EstimateTable({ estimate }: { estimate: DraftEstimate }) {
  return (
    <Card
      title={estimate.project || "Desglose"}
      extra={
        <Space>
          {estimate.original_total_hours != null && (
            <Typography.Text delete type="secondary">
              {hours(estimate.original_total_hours)}
            </Typography.Text>
          )}
          <Typography.Text strong>{hours(estimate.total_hours)}</Typography.Text>
        </Space>
      }
      styles={{ body: { padding: 0 } }}
    >
      <Table
        rowKey="component_id"
        dataSource={estimate.components}
        pagination={false}
        columns={[
          {
            title: "Componente",
            dataIndex: "name",
            render: (value: string, row) => (
              <Space direction="vertical" size={0}>
                <Typography.Text strong>{value}</Typography.Text>
                <Typography.Text type="secondary">{row.rationale}</Typography.Text>
              </Space>
            ),
          },
          {
            // The whole point of the grounding flag: a component with no
            // precedent is not a worse number, it is a number with nothing
            // behind it, and that is what the reviewer is here to judge.
            title: "Evidencia",
            dataIndex: "grounded",
            width: 130,
            render: (grounded: boolean) =>
              grounded ? (
                <Tag color="green">Con precedente</Tag>
              ) : (
                <Tag color="red">Sin precedente</Tag>
              ),
          },
          {
            title: "Horas",
            dataIndex: "estimated_hours",
            width: 150,
            align: "right",
            render: (value: number, row) => (
              <Space size={6}>
                {/*
                  Sólo aparece en las líneas que el revisor cambió: el servicio
                  guarda el original únicamente cuando difiere, así que esto no
                  compara números y no puede acabar tachando cifras idénticas.
                */}
                {row.original_estimated_hours != null && (
                  <Typography.Text delete type="secondary">
                    {hours(row.original_estimated_hours)}
                  </Typography.Text>
                )}
                <Typography.Text>{hours(value)}</Typography.Text>
              </Space>
            ),
          },
        ]}
      />
    </Card>
  );
}

/**
 * Las señales que el sistema calculó sobre su propia estimación.
 *
 * Un solo pintor, dos orígenes: en la pausa vienen del payload del revisor y en
 * una ejecución terminada del checkpoint. La banda NO es un campo del estado —
 * el servicio la deriva de los componentes y sus análogos— y por eso puede
 * faltar sin que eso signifique cero.
 *
 * `proposedHours` sólo se pasa en la pausa. En una ejecución terminada la
 * cabecera de la tabla ya lleva el total, y repetirlo a doscientos píxeles es
 * ruido, no refuerzo.
 */
function Senales({
  confidence,
  band,
  proposedHours,
}: {
  confidence: number | null | undefined;
  band: HistoricalBand | null | undefined;
  proposedHours?: number | null;
}) {
  // Sin ninguna de las dos no hay nada que contar, y tres tarjetas vacías dicen
  // menos que ninguna.
  if (confidence == null && band == null) return null;

  return (
    <Flex gap={16} wrap>
      <Card style={{ flex: "1 1 220px" }}>
        <Statistic title="Confianza" value={percent(confidence)} />
      </Card>
      <Card style={{ flex: "1 1 220px" }}>
        <Statistic
          title="Banda histórica"
          value={band ? `${hours(band.low).replace(" h", "")}–${hours(band.high)}` : "sin datos"}
        />
        {band && (
          // La banda está escalada por cobertura: sin este dato, un rango
          // construido sobre dos de ocho componentes se lee como si valiera
          // para el proyecto entero.
          <Typography.Text type="secondary">
            {band.covered_components} de {band.total_components} componentes · {band.references}{" "}
            referencias
          </Typography.Text>
        )}
      </Card>
      {proposedHours != null && (
        <Card style={{ flex: "1 1 220px" }}>
          <Statistic title="Propuesta del sistema" value={hours(proposedHours)} />
        </Card>
      )}
    </Flex>
  );
}

export type RunDetail = {
  id: string;
  estimationId: string;
  transcript: string;
  runState: string;
  status: string | null;
  estimate: unknown;
  reviewPayload: unknown;
  humanDecision: unknown;
  errors: unknown;
  proposal: unknown;
};

export function RunView({ run, state }: { run: RunDetail; state: GraphState | null }) {
  const review = reviewPayloadSchema.safeParse(run.reviewPayload);
  const estimate = draftEstimateSchema.safeParse(run.estimate);
  const decision = humanDecisionSchema.safeParse(run.humanDecision);
  const proposal = commercialProposalSchema.safeParse(run.proposal);
  const badge = statusLabel(run.status);
  const awaiting = run.status === AWAITING_REVIEW && run.runState === "paused";
  // Mientras corre no hay nada que enseñar salvo el avance: el estado existe,
  // pero a medias, y pintar media estimación como si fuera la final es peor que
  // no pintarla.
  const running = run.runState === "running";
  const failed = run.runState === FAILED;

  /*
    El estado del run, arriba del todo: es lo primero que hay que saber al
    abrir. Sale a una variable porque vivía dentro del fragmento de la rama
    pausada, y sacarlo de ahí sin más obligaba a repetir su guarda; en un
    ternario TypeScript sigue estrechando `review.data`, cosa que un booleano
    guardado aparte no hace.
  */
  const avisoDeParada =
    !running && awaiting && review.success ? (
      <Alert
        type="warning"
        showIcon
        message="El sistema se ha parado y pide una decisión"
        description={
          /*
            TODOS los disparadores, no el titular. `reason` resume varios en
            «…, and N more concern(s)» y esconde el resto. La tarjeta que los
            listaba se quitó por redundante con esta alerta, y lo era sólo
            mientras hubiera uno: confianza, banda histórica y sin precedente
            pueden dispararse a la vez, y este pasa a ser el único sitio donde
            se ven enteros.
          */
          review.data.triggers.length > 1 ? (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {review.data.triggers.map((trigger) => (
                <li key={trigger}>{trigger}</li>
              ))}
            </ul>
          ) : (
            review.data.reason
          )
        }
      />
    ) : null;

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="center">
        <Space direction="vertical" size={0}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Estimación supervisada
          </Typography.Title>
          <Typography.Text type="secondary" copyable>
            {run.estimationId}
          </Typography.Text>
        </Space>
        <Space>
          <Tag color={badge.color}>{badge.text}</Tag>
          <Link href="/supervisor">
            <Button variant="outlined" icon={<ArrowLeftOutlined />}>
              Bandeja
            </Button>
          </Link>
        </Space>
      </Flex>

      {failed && (
        <Alert
          type="error"
          showIcon
          message="La ejecución murió antes de terminar"
          description="El estado quedó guardado en el punto en el que se paró. Arranca una estimación nueva con la misma transcripción: este identificador ya no puede reanudarse."
        />
      )}

      {avisoDeParada}

      {/*
        De dónde salió todo. Va aquí —hijo directo del Flex, sin guarda— porque
        las ramas de abajo son excluyentes entre sí: metida en una, faltaría en
        las otras cuatro (corriendo, pausada, terminada, fallida, y la quinta de
        facto: pausada con un payload que no valida). Cerrado por defecto: es el
        material de partida, no lo que se viene a mirar.
      */}
      <CollapseCard title="Transcripción de origen">
        <Typography.Paragraph
          style={{
            marginBottom: 0,
            // Es texto plano con saltos de línea: sin esto sale corrido.
            whiteSpace: "pre-wrap",
            // Y sin el tope, abrirla empuja la página varias pantallas.
            maxHeight: 420,
            overflowY: "auto",
          }}
        >
          {run.transcript}
        </Typography.Paragraph>
      </CollapseCard>

      {running && <RunProgressPanel id={run.id} />}

      {!running && awaiting && review.success && (
        <>
          <Senales
            confidence={review.data.confidence}
            band={review.data.historical_band}
            proposedHours={review.data.estimate?.total_hours ?? null}
          />

          {/*
            Justo detrás de los disparadores: lo que hay que decidir, pegado al
            porqué de que haya que decidirlo. Lo que sigue —análogos y reservas—
            es material de consulta, y queda a mano sin empujar el formulario
            fuera de la primera pantalla.
          */}
          {review.data.estimate && (
            <ReviewEstimateForm id={run.id} estimate={review.data.estimate} />
          )}

          {review.data.budget_matches.length > 0 && (
            <CollapseCard
              title="Presupuestos análogos encontrados"
              styles={{ body: { padding: 0 } }}
            >
              <Table
                rowKey={(row) => `${row.component_id}-${row.reference_budget_id}`}
                dataSource={review.data.budget_matches}
                pagination={false}
                columns={[
                  { title: "Componente", dataIndex: "component" },
                  { title: "Referencia", dataIndex: "reference_budget_id" },
                  {
                    title: "Horas",
                    dataIndex: "amount",
                    width: 100,
                    align: "right",
                    render: hours,
                  },
                  {
                    title: "Distancia",
                    dataIndex: "distance",
                    width: 110,
                    align: "right",
                    render: (value: number) => value.toFixed(3),
                  },
                ]}
              />
            </CollapseCard>
          )}

          {review.data.concerns.length > 0 && (
            <CollapseCard title="Reservas del validador">
              <List
                dataSource={review.data.concerns}
                renderItem={(concern) => <List.Item>{concern}</List.Item>}
              />
            </CollapseCard>
          )}
        </>
      )}

      {!running && !awaiting && (
        <>
          {run.errors != null && Array.isArray(run.errors) && run.errors.length > 0 && (
            <Alert
              type="warning"
              showIcon
              message="La ejecución degradó por el camino"
              description={
                <List
                  dataSource={run.errors as string[]}
                  renderItem={(e) => <List.Item>{e}</List.Item>}
                />
              }
            />
          )}

          {/*
            Las mismas señales que ve un revisor, para quien abre una ejecución
            ya cerrada. Salen del checkpoint, que las conserva, y no de la fila:
            la confianza de la fila puede venir de un payload antiguo.
          */}
          <Senales confidence={state?.values.confidence} band={state?.historical_band} />

          {estimate.success ? (
            <EstimateTable estimate={estimate.data} />
          ) : (
            <Alert
              type="info"
              showIcon
              message="Esta ejecución todavía no ha producido un desglose."
            />
          )}

          {/*
            Después del desglose, y no antes: lo que decidió una persona se lee
            mirando sobre qué lo decidió. Arriba obligaba a bajar, leer la tabla
            y volver.
          */}
          {decision.success && (
            <Card title="Decisión humana">
              <Descriptions
                column={1}
                items={[
                  {
                    key: "action",
                    label: "Acción",
                    children: decision.data.action === "reject" ? "Rechazada" : "Aprobada",
                  },
                  {
                    key: "hours",
                    label: "Horas revisadas",
                    children:
                      // Desde la S15 el revisor pone precio línea a línea, así
                      // que se cuentan las que tocó y el total sale de la tabla.
                      // `adjusted_hours` es el total suelto de las S13-S14 y
                      // sólo aparece en decisiones de entonces.
                      decision.data.component_hours
                        ? `${Object.keys(decision.data.component_hours).length} componente(s)`
                        : decision.data.adjusted_hours != null
                          ? `${hours(decision.data.adjusted_hours)} (total, S13-S14)`
                          : "—",
                  },
                  {
                    key: "who",
                    label: "Revisor",
                    children: decision.data.reviewer_id ?? "—",
                  },
                  {
                    key: "why",
                    label: "Motivo",
                    children: decision.data.comment ?? "—",
                  },
                ]}
              />
            </Card>
          )}

          {estimate.success && estimate.data.notes && (
            <Card title="Notas del sistema">
              <Typography.Paragraph style={{ marginBottom: 0 }}>
                {estimate.data.notes}
              </Typography.Paragraph>
            </Card>
          )}

          <ProposalCard
            id={run.id}
            proposal={proposal.success ? proposal.data : null}
            canDraft={estimate.success && !failed}
          />
        </>
      )}

      {!running && state && <RoutingTrace state={state} />}
    </Flex>
  );
}
