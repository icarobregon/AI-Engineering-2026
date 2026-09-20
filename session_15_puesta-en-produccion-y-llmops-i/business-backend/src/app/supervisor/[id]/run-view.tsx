"use client";

import Link from "next/link";
import { ArrowLeftOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Collapse,
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
import type { GraphState } from "@/lib/estimator/contracts";
import { ProposalCard } from "./proposal-card";
import { ReviewForm } from "./review-form";
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
              grounded ? <Tag color="green">Con precedente</Tag> : <Tag color="red">Sin precedente</Tag>,
          },
          {
            title: "Horas",
            dataIndex: "estimated_hours",
            width: 100,
            align: "right",
            render: hours,
          },
        ]}
      />
    </Card>
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

      {/*
        De dónde salió todo. Va aquí —hijo directo del Flex, sin guarda— porque
        las ramas de abajo son excluyentes entre sí: metida en una, faltaría en
        las otras cuatro (corriendo, pausada, terminada, fallida, y la quinta de
        facto: pausada con un payload que no valida). Cerrado por defecto: es el
        material de partida, no lo que se viene a mirar.
      */}
      <Collapse
        items={[
          {
            key: "transcript",
            label: "Transcripción de origen",
            children: (
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
            ),
          },
        ]}
      />

      {running && <RunProgressPanel id={run.id} />}

      {failed && (
        <Alert
          type="error"
          showIcon
          message="La ejecución murió antes de terminar"
          description="El estado quedó guardado en el punto en el que se paró. Arranca una estimación nueva con la misma transcripción: este identificador ya no puede reanudarse."
        />
      )}

      {!running && awaiting && review.success && (
        <>
          <Alert
            type="warning"
            showIcon
            message="El sistema se ha parado y pide una decisión"
            description={review.data.reason}
          />

          <Flex gap={16} wrap>
            <Card style={{ flex: "1 1 220px" }}>
              <Statistic
                title="Confianza"
                value={percent(review.data.confidence)}
              />
            </Card>
            <Card style={{ flex: "1 1 220px" }}>
              <Statistic
                title="Banda histórica"
                value={
                  review.data.historical_band
                    ? `${hours(review.data.historical_band.low).replace(" h", "")}–${hours(review.data.historical_band.high)}`
                    : "sin datos"
                }
              />
            </Card>
            <Card style={{ flex: "1 1 220px" }}>
              <Statistic
                title="Propuesta del sistema"
                value={review.data.estimate ? hours(review.data.estimate.total_hours) : "—"}
              />
            </Card>
          </Flex>

          <Card title="Qué disparó la parada">
            <List
              dataSource={review.data.triggers}
              renderItem={(trigger) => <List.Item>{trigger}</List.Item>}
            />
          </Card>

          {review.data.estimate && <EstimateTable estimate={review.data.estimate} />}

          {review.data.budget_matches.length > 0 && (
            <Card title="Presupuestos análogos encontrados" styles={{ body: { padding: 0 } }}>
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
            </Card>
          )}

          {review.data.concerns.length > 0 && (
            <Card title="Reservas del validador">
              <List
                dataSource={review.data.concerns}
                renderItem={(concern) => <List.Item>{concern}</List.Item>}
              />
            </Card>
          )}

          <ReviewForm id={run.id} proposedHours={review.data.estimate?.total_hours ?? null} />
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
                <List dataSource={run.errors as string[]} renderItem={(e) => <List.Item>{e}</List.Item>} />
              }
            />
          )}

          {decision.success && (
            <Card title="Decisión humana">
              <Descriptions
                column={1}
                items={[
                  { key: "action", label: "Acción", children: decision.data.action },
                  {
                    key: "hours",
                    label: "Horas fijadas",
                    children: decision.data.adjusted_hours != null ? hours(decision.data.adjusted_hours) : "—",
                  },
                  { key: "who", label: "Revisor", children: decision.data.reviewer_id ?? "—" },
                  { key: "why", label: "Motivo", children: decision.data.comment ?? "—" },
                ]}
              />
            </Card>
          )}

          {estimate.success ? (
            <EstimateTable estimate={estimate.data} />
          ) : (
            <Alert type="info" showIcon message="Esta ejecución todavía no ha producido un desglose." />
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
