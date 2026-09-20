"use client";

import Link from "next/link";
import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { ArrowLeftOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Flex,
  Popconfirm,
  Space,
  Steps,
  Table,
  Tag,
  Typography,
} from "antd";

import { eur, hours as horasFmt } from "@/lib/format";
import {
  RELIABILITY_OK,
  type Reformulation,
  type TaskHoursResult,
  type WorkModule,
} from "@/lib/estimator/contracts";
import {
  estimateHoursFor,
  generateStructureFor,
  rerunReformulation,
  type FormState,
} from "../actions";
import { stepLabels, stepOrder } from "../steps";
import { ReviewForm } from "./review-form";
import { VerificationForm } from "./verification-form";

type Run = {
  id: string;
  transcript: string;
  currentStep: string;
  confirmedAt: string | null;
  createdAt: string;
};

type Verification = {
  lines: {
    module: string;
    task: string;
    hours: number;
    rate: number;
    cost: number;
    reliability: number | null;
    hadMatch: boolean;
  }[];
  totalHours: number;
  totalCostEur: number;
};

const VACIO: FormState = { error: null, notice: null };

/** Un botón que lanza una etapa y enseña su resultado. */
function StageButton({
  runId,
  action,
  label,
  loadingLabel,
  danger,
  confirm,
}: {
  runId: string;
  action: (prev: FormState, data: FormData) => Promise<FormState>;
  label: string;
  loadingLabel: string;
  danger?: boolean;
  confirm?: string;
}) {
  const [state, run] = useActionState<FormState, FormData>(action, VACIO);
  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      {state.error && <Alert type="error" showIcon message={state.error} />}
      {state.notice && <Alert type="success" showIcon message={state.notice} />}
      <form action={run}>
        <input type="hidden" name="run_id" value={runId} />
        <StageSubmit label={label} loadingLabel={loadingLabel} danger={danger} confirm={confirm} />
      </form>
    </Space>
  );
}

function StageSubmit({
  label,
  loadingLabel,
  danger,
  confirm,
}: {
  label: string;
  loadingLabel: string;
  danger?: boolean;
  confirm?: string;
}) {
  const { pending } = useFormStatus();
  const boton = (
    <Button
      type={danger ? "default" : "primary"}
      danger={danger}
      htmlType={confirm ? "button" : "submit"}
      loading={pending}
    >
      {pending ? loadingLabel : label}
    </Button>
  );
  if (!confirm) return boton;
  // Re-ejecutar borra en cascada. La app de referencia lo hace sin preguntar.
  return (
    <Popconfirm
      title="Se borrará lo que venga después"
      description={confirm}
      okText="Re-ejecutar"
      cancelText="Cancelar"
      onConfirm={(e) => {
        (e?.currentTarget as HTMLElement)?.closest("form")?.requestSubmit();
      }}
    >
      {boton}
    </Popconfirm>
  );
}

export function RunWizard({
  run,
  reformulation,
  proposed,
  reviewed,
  taskHours,
  verification,
}: {
  run: Run;
  reformulation: Reformulation | null;
  proposed: WorkModule[] | null;
  reviewed: WorkModule[] | null;
  taskHours: TaskHoursResult | null;
  verification: Verification | null;
}) {
  const [paso, setPaso] = useState(() => {
    const i = stepOrder.indexOf(run.currentStep as (typeof stepOrder)[number]);
    return i >= 0 ? i : 0;
  });

  // El progreso se marca por lo que EXISTE, no por el paso en el que se está:
  // se puede volver atrás sin que el árbol o las horas dejen de estar hechos.
  const hecho = [
    reformulation != null,
    proposed != null,
    reviewed != null,
    taskHours != null,
    verification != null,
  ];

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="flex-start" gap={16}>
        <Space direction="vertical" size={4}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Estimación asistida
          </Typography.Title>
          <Space size={8}>
            {run.confirmedAt ? (
              <Tag color="success">confirmada</Tag>
            ) : (
              <Tag color="processing">{stepLabels[run.currentStep] ?? run.currentStep}</Tag>
            )}
            <Typography.Text type="secondary">
              {new Date(run.createdAt).toLocaleString("es-ES")}
            </Typography.Text>
          </Space>
        </Space>
        <Link href="/asistente">
          <Button variant="outlined" icon={<ArrowLeftOutlined />}>
            Histórico
          </Button>
        </Link>
      </Flex>

      <Steps
        current={paso}
        onChange={setPaso}
        items={stepOrder.map((clave, i) => ({
          title: stepLabels[clave],
          status: hecho[i] ? "finish" : i === paso ? "process" : "wait",
        }))}
      />

      {paso === 0 && (
        <Card title="Paso 1 · La transcripción, convertida en brief">
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            {reformulation ? (
              <Descriptions
                column={1}
                size="small"
                bordered
                items={[
                  { key: "f", label: "Función", children: reformulation.query.function },
                  {
                    key: "t",
                    label: "Tecnologías",
                    children:
                      reformulation.query.technologies.length > 0
                        ? reformulation.query.technologies.map((t) => <Tag key={t}>{t}</Tag>)
                        : "—",
                  },
                  { key: "s", label: "Sector", children: reformulation.query.sector ?? "—" },
                  { key: "e", label: "Escala", children: reformulation.query.scale },
                  { key: "p", label: "País", children: reformulation.query.country ?? "—" },
                  {
                    key: "r",
                    label: "Normativa",
                    children:
                      reformulation.query.regulations.length > 0
                        ? reformulation.query.regulations.map((r) => <Tag key={r}>{r}</Tag>)
                        : "—",
                  },
                  {
                    key: "c",
                    label: "Restricciones",
                    children:
                      reformulation.query.constraints.length > 0
                        ? reformulation.query.constraints.join(" · ")
                        : "—",
                  },
                  {
                    key: "b",
                    label: "Texto de búsqueda",
                    children: (
                      <Typography.Text type="secondary">
                        {reformulation.search_text}
                      </Typography.Text>
                    ),
                  },
                ]}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Sin reformulación." />
            )}

            <Card size="small" title="Transcripción original">
              <Typography.Paragraph
                type="secondary"
                style={{ marginBottom: 0, whiteSpace: "pre-wrap", maxHeight: 240, overflow: "auto" }}
              >
                {run.transcript}
              </Typography.Paragraph>
            </Card>

            <StageButton
              runId={run.id}
              action={rerunReformulation}
              label="Re-ejecutar reformulación"
              loadingLabel="Reformulando…"
              danger
              confirm="Volver a reformular deja sin sentido la estructura, las horas y la confirmación que salieron del brief anterior, así que se vacían."
            />
          </Space>
        </Card>
      )}

      {paso === 1 && (
        <Card title="Paso 2 · El brief, descompuesto en módulos y tareas">
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              message="La estructura se genera sin mirar el corpus"
              description="Es deliberado: generarla con presupuestos históricos delante empobrecía el árbol, porque el modelo se ceñía a lo que ya existía. El corpus vuelve a entrar en el paso 4, tarea a tarea."
            />
            {proposed ? (
              <TreePreview modules={proposed} />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Sin estructura todavía." />
            )}
            <StageButton
              runId={run.id}
              action={generateStructureFor}
              label={proposed ? "Re-generar estructura" : "Generar estructura"}
              loadingLabel="Generando… (puede tardar minutos)"
              danger={proposed != null}
              confirm={
                proposed
                  ? "Volver a generar descarta el árbol revisado, las horas y la confirmación."
                  : undefined
              }
            />
          </Space>
        </Card>
      )}

      {paso === 2 && (
        <ReviewForm runId={run.id} modules={reviewed ?? proposed ?? []} />
      )}

      {paso === 3 && (
        <Card title="Paso 4 · Horas por tarea, desde el corpus histórico">
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            {taskHours ? (
              <HoursTable result={taskHours} />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Sin horas todavía." />
            )}
            <StageButton
              runId={run.id}
              action={estimateHoursFor}
              label={taskHours ? "Re-calcular horas" : "Calcular horas"}
              loadingLabel="Buscando analogías… (puede tardar minutos)"
              danger={taskHours != null}
              confirm={taskHours ? "Volver a calcular descarta la confirmación." : undefined}
            />
          </Space>
        </Card>
      )}

      {paso === 4 && (
        <VerificationForm
          runId={run.id}
          modules={reviewed ?? []}
          taskHours={taskHours}
          verification={verification}
        />
      )}
    </Flex>
  );
}

function TreePreview({ modules }: { modules: WorkModule[] }) {
  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {modules.map((m) => (
        <Card key={m.name} size="small" title={m.name}>
          {m.description && (
            <Typography.Paragraph type="secondary">{m.description}</Typography.Paragraph>
          )}
          <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
            {m.tasks.map((t) => (
              <li key={t.name}>
                <Typography.Text>{t.name}</Typography.Text>
                {t.description && (
                  <Typography.Text type="secondary"> — {t.description}</Typography.Text>
                )}
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </Space>
  );
}

function HoursTable({ result }: { result: TaskHoursResult }) {
  const sinDato = result.tasks.filter((t) => !t.has_match).length;
  const flojas = result.tasks.filter(
    (t) => t.has_match && (t.reliability ?? 0) < RELIABILITY_OK,
  ).length;
  const total = result.tasks.reduce((n, t) => n + (t.estimated_hours ?? 0), 0);

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <Tag color="success">{result.tasks.length - sinDato - flojas} con analogía firme</Tag>
        {flojas > 0 && <Tag color="warning">{flojas} con consenso flojo</Tag>}
        {sinDato > 0 && <Tag color="error">{sinDato} sin analogía</Tag>}
        <Tag>{horasFmt(total)} en total</Tag>
      </Space>
      <Table
        rowKey={(t) => `${t.module}::${t.task}`}
        dataSource={result.tasks}
        pagination={false}
        size="small"
        columns={[
          { title: "Módulo", dataIndex: "module", width: 200 },
          { title: "Tarea", dataIndex: "task" },
          {
            title: "Horas",
            dataIndex: "estimated_hours",
            align: "right",
            width: 100,
            render: (v: number | null) =>
              v == null ? <Typography.Text type="danger">sin dato</Typography.Text> : v,
          },
          {
            title: "Fiabilidad",
            dataIndex: "reliability",
            align: "right",
            width: 130,
            render: (v: number | null, fila) =>
              !fila.has_match || v == null ? (
                <Typography.Text type="secondary">—</Typography.Text>
              ) : v >= RELIABILITY_OK ? (
                <Tag color="success">{Math.round(v * 100)} %</Tag>
              ) : (
                <Tag color="warning">{Math.round(v * 100)} %</Tag>
              ),
          },
          {
            title: "Precedentes",
            dataIndex: "neighbors",
            align: "right",
            width: 120,
            render: (n: { estimated_hours: number }[]) =>
              n.length === 0 ? "—" : `${n.length} · ${n.map((x) => x.estimated_hours).join(", ")} h`,
          },
        ]}
      />
      <Typography.Text type="secondary">
        Las horas salen del consenso ponderado de las tareas históricas más parecidas. Una tarea
        sin analogía no recibe número: lo pones tú en el paso siguiente.
      </Typography.Text>
    </Space>
  );
}
