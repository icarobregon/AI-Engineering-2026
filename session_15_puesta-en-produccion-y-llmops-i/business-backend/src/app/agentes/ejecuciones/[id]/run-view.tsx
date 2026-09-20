"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeftOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Flex,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";

import { hours as horasFmt } from "@/lib/format";
import type { AgentEstimate, AgentTrace } from "@/lib/estimator/contracts";
import { pollAgentRun } from "../../actions";
import { statusTag } from "../../pieces";

type Run = {
  id: string;
  status: string;
  errorMessage: string | null;
  model: string;
  reasoningEffort: string;
  maxIterations: number;
  profileName: string | null;
  transcript: string;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
};

const INTERVALO_MS = 3_000;
/** Techo de sondeos: 40 minutos. El bucle es largo, pero no infinito. */
const MAX_SONDEOS = (40 * 60_000) / INTERVALO_MS;

export function AgentRunView({
  run,
  estimate,
  trace,
}: {
  run: Run;
  estimate: AgentEstimate | null;
  trace: AgentTrace | null;
}) {
  const router = useRouter();
  const [vivo, setVivo] = useState({
    status: run.status,
    errorMessage: run.errorMessage,
    stalled: false,
  });

  const terminado = vivo.status === "completed" || vivo.status === "failed";

  useEffect(() => {
    if (terminado) return;
    let sondeos = 0;
    let cancelado = false;

    const id = setInterval(async () => {
      if (cancelado) return;
      sondeos += 1;
      if (sondeos > MAX_SONDEOS) {
        clearInterval(id);
        return;
      }
      try {
        const datos = await pollAgentRun(run.id);
        if (!datos || cancelado) return;
        setVivo({
          status: datos.status,
          errorMessage: datos.errorMessage,
          stalled: datos.stalled,
        });
        if (datos.finished) {
          clearInterval(id);
          // La estimación y la traza NO viajan en el sondeo: se piden al
          // servidor una vez, al terminar.
          router.refresh();
        }
      } catch {
        // Un fallo de red puntual no mata el sondeo: el siguiente tick reintenta.
      }
    }, INTERVALO_MS);

    return () => {
      cancelado = true;
      clearInterval(id);
    };
  }, [run.id, terminado, router]);

  const duracion =
    run.startedAt && run.finishedAt
      ? Math.round(
          (new Date(run.finishedAt).getTime() - new Date(run.startedAt).getTime()) / 1000,
        )
      : null;

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="flex-start" gap={16}>
        <Space direction="vertical" size={4}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Ejecución del agente
          </Typography.Title>
          <Space size={8} wrap>
            {statusTag(vivo.status)}
            <Typography.Text type="secondary">
              {new Date(run.createdAt).toLocaleString("es-ES")}
            </Typography.Text>
          </Space>
        </Space>
        <Link href="/agentes">
          <Button variant="outlined" icon={<ArrowLeftOutlined />}>
            Consola
          </Button>
        </Link>
      </Flex>

      {vivo.status === "failed" && (
        <Alert
          type="error"
          showIcon
          message="La ejecución falló"
          description={vivo.errorMessage ?? "El servicio IA no completó el bucle."}
        />
      )}

      {vivo.stalled && !terminado && (
        <Alert
          type="warning"
          showIcon
          message="Sin señales de esta ejecución"
          description="Lleva más de diez minutos sin avanzar. El proceso que la corría pudo reiniciarse; el bucle del agente no se reanuda solo."
        />
      )}

      <Card
        title="Con qué corrió"
        extra={
          !terminado && !vivo.stalled ? (
            <Space size={8}>
              <Spin size="small" />
              <Typography.Text type="secondary">corriendo…</Typography.Text>
            </Space>
          ) : null
        }
      >
        <Descriptions
          column={{ xs: 1, md: 2 }}
          size="small"
          items={[
            {
              key: "perfil",
              label: "Perfil",
              children:
                run.profileName ?? (
                  <Typography.Text type="secondary">sin perfil</Typography.Text>
                ),
            },
            {
              key: "modelo",
              label: "Modelo",
              children: <Typography.Text code>{run.model}</Typography.Text>,
            },
            { key: "esfuerzo", label: "Esfuerzo", children: run.reasoningEffort },
            {
              key: "iter",
              label: "Techo de iteraciones",
              children:
                run.maxIterations > 0 ? (
                  run.maxIterations
                ) : (
                  <Typography.Text type="secondary">(por defecto del servicio)</Typography.Text>
                ),
            },
            {
              key: "dur",
              label: "Duración",
              children: duracion == null ? "—" : `${duracion} s`,
            },
          ]}
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          Los ajustes se copiaron al lanzar. Si el perfil cambia o se borra, esta ejecución sigue
          diciendo con qué corrió.
        </Typography.Paragraph>
      </Card>

      {estimate && (
        <Card title={estimate.project}>
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            <Space size="large" wrap>
              <Statistic title="Horas totales" value={horasFmt(estimate.total_hours)} />
              <Statistic title="Componentes" value={estimate.components.length} />
              {trace && <Statistic title="Vueltas del bucle" value={trace.iterations} />}
            </Space>

            {estimate.components.length > 0 && (
              <Table
                rowKey={(c) => String(c.name)}
                dataSource={estimate.components}
                pagination={false}
                size="small"
                columns={[
                  { title: "Componente", dataIndex: "name" },
                  {
                    title: "Horas",
                    dataIndex: "estimated_hours",
                    align: "right",
                    width: 120,
                    render: (v: number) => horasFmt(v),
                  },
                ]}
              />
            )}

            {estimate.notes && (
              <Alert
                type="info"
                showIcon
                message="Lo que el agente quiere que mire una persona"
                description={estimate.notes}
              />
            )}
          </Space>
        </Card>
      )}

      {trace && (
        <Card title="Traza del bucle">
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Space size={8} wrap>
              <Tag>{trace.iterations} vueltas</Tag>
              <Tag>{trace.steps.length} llamadas a herramienta</Tag>
              {/* `natural` = el modelo dejó de pedir herramientas solo. Cualquier
                  otra cosa significa que lo cortamos nosotros, y eso cambia
                  cuánto fiarse del resultado. */}
              <Tag color={trace.stop_reason === "natural" ? "success" : "warning"}>
                paró: {trace.stop_reason}
              </Tag>
            </Space>
            {trace.stop_reason !== "natural" && (
              <Alert
                type="warning"
                showIcon
                message="El bucle no paró solo"
                description="Se agotó el techo de iteraciones. La estimación es la que el agente pudo cerrar con lo que llevaba, no la que habría dado con más vueltas."
              />
            )}
          </Space>
        </Card>
      )}

      {!estimate && terminado && vivo.status !== "failed" && (
        <Card>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="La ejecución terminó sin estimación."
          />
        </Card>
      )}

      <Card size="small" title="Transcripción">
        <Typography.Paragraph
          type="secondary"
          style={{ marginBottom: 0, whiteSpace: "pre-wrap", maxHeight: 200, overflow: "auto" }}
        >
          {run.transcript}
        </Typography.Paragraph>
      </Card>
    </Flex>
  );
}
