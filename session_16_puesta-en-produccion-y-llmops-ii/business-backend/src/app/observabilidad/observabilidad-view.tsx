"use client";

import { useState, useTransition } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Flex,
  Row,
  Segmented,
  Space,
  Statistic,
  Table,
  Tag,
  theme,
  Tooltip,
  Typography,
} from "antd";

import type { MetricsSummary, MetricsWindow } from "@/lib/estimator/contracts";
import { percent, usdCost } from "@/lib/format";
import { leerMetricas } from "./actions";

const VENTANAS: { label: string; value: MetricsWindow }[] = [
  { label: "1 hora", value: "1h" },
  { label: "24 horas", value: "24h" },
  { label: "7 días", value: "7d" },
];

const segundos = (ms: number | null | undefined) =>
  ms == null ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;

const hora = (iso: string) =>
  new Date(iso).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });

/**
 * Una línea con la forma de la serie, dibujada a mano.
 *
 * Sin librería de gráficos: no hay ninguna en el proyecto y meter uno entero
 * para pintar catorce puntos es peor negocio que veinte líneas de SVG. No lleva
 * ejes a propósito — lo que se busca aquí es la FORMA (¿hay un pico?, ¿sube?),
 * y el número exacto vive en las tablas de abajo.
 */
function Sparkline({ valores, color }: { valores: number[]; color: string }) {
  if (valores.length < 2) return null;
  const max = Math.max(...valores, 1);
  const puntos = valores
    .map((v, i) => `${(i / (valores.length - 1)) * 100},${28 - (v / max) * 26}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" style={{ width: "100%", height: 34 }}>
      <polyline
        points={puntos}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export function ObservabilidadView({
  initial,
  initialError,
}: {
  initial: MetricsSummary | null;
  initialError: string | null;
}) {
  const { token } = theme.useToken();
  const [summary, setSummary] = useState(initial);
  const [error, setError] = useState(initialError);
  const [ventana, setVentana] = useState<MetricsWindow>("24h");
  const [cargando, startTransition] = useTransition();

  const recargar = (w: MetricsWindow) => {
    setVentana(w);
    startTransition(async () => {
      const r = await leerMetricas(w);
      if (r.summary) setSummary(r.summary);
      setError(r.error);
    });
  };

  const vacio = summary != null && summary.requests === 0;

  return (
    <Flex vertical gap={24}>
      <Space direction="vertical" size={4}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Observabilidad
        </Typography.Title>
        <Typography.Text type="secondary">
          El golden set mide la calidad <em>cuando se lanza la evaluación</em>, con entradas que
          elegimos nosotros. Esto mide lo que el sistema hace el resto del tiempo, con las que manda
          el mundo. Son complementarias: una avisa de lo que rompen nuestros cambios, la otra de lo
          que no supimos imaginar.
        </Typography.Text>
      </Space>

      <Flex align="center" justify="space-between" wrap gap={12}>
        <Segmented
          options={VENTANAS}
          value={ventana}
          disabled={cargando}
          onChange={(v) => recargar(v as MetricsWindow)}
        />
        <Button onClick={() => recargar(ventana)} loading={cargando}>
          Actualizar
        </Button>
      </Flex>

      {error && <Alert type="warning" showIcon message={error} />}

      {!summary ? (
        <Card>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Sin métricas que enseñar." />
        </Card>
      ) : (
        <>
          {vacio && (
            <Alert
              type="info"
              showIcon
              message="Ninguna petición en esta ventana"
              description="El servicio sólo apunta lo que atiende. Las sondas de salud quedan fuera a propósito: contarlas haría que la latencia p95 del sistema fuese en realidad la de un latido."
            />
          )}

          <Row gutter={[16, 16]}>
            <Col xs={24} md={8}>
              <Card>
                <Statistic
                  title="Latencia media"
                  value={segundos(summary.mean_latency_ms)}
                  valueStyle={{ fontSize: 30 }}
                />
                <Tooltip title="La media esconde a la minoría que sufre. El p95 dice si hay usuarios esperando una eternidad.">
                  <Typography.Text type="secondary">
                    p95 <Typography.Text strong>{segundos(summary.p95_latency_ms)}</Typography.Text>
                  </Typography.Text>
                </Tooltip>
                <Sparkline
                  valores={summary.series.map((b) => b.p95_latency_ms ?? b.mean_latency_ms ?? 0)}
                  color={token.colorPrimary}
                />
              </Card>
            </Col>

            <Col xs={24} md={8}>
              <Card>
                <Statistic
                  title="Coste por petición"
                  value={usdCost(summary.mean_cost_usd)}
                  valueStyle={{ fontSize: 30 }}
                />
                <Typography.Text type="secondary">
                  {usdCost(summary.total_cost_usd)} en la ventana ·{" "}
                  {summary.prompt_tokens + summary.completion_tokens} tokens · {summary.llm_calls}{" "}
                  llamadas
                </Typography.Text>
                <Sparkline
                  valores={summary.series.map((b) => b.cost_usd)}
                  color={token.colorSuccess}
                />
              </Card>
            </Col>

            <Col xs={24} md={8}>
              <Card>
                <Statistic
                  title="Tasa de error"
                  value={percent(summary.error_rate)}
                  valueStyle={{
                    fontSize: 30,
                    color: (summary.error_rate ?? 0) > 0 ? token.colorError : undefined,
                  }}
                />
                <Typography.Text type="secondary">
                  {summary.errors} de {summary.requests} peticiones
                </Typography.Text>
                <Sparkline valores={summary.series.map((b) => b.errors)} color={token.colorError} />
              </Card>
            </Col>
          </Row>

          {summary.calls_without_usage > 0 && (
            <Alert
              type="warning"
              showIcon
              message={`${summary.calls_without_usage} llamada(s) sin datos de consumo`}
              description="El proveedor no informó de tokens en esas llamadas. No son gratis: son desconocidas, y se cuentan aparte para que el coste de arriba no se lea como si estuviera completo."
            />
          )}

          <Card title="Por ruta" size="small">
            <Table
              size="small"
              rowKey="route"
              pagination={false}
              dataSource={summary.by_route}
              columns={[
                { title: "Ruta", dataIndex: "route", ellipsis: true },
                { title: "Peticiones", dataIndex: "requests", width: 110, align: "right" },
                {
                  title: "Media",
                  dataIndex: "mean_latency_ms",
                  width: 100,
                  align: "right",
                  render: segundos,
                },
                {
                  title: "p95",
                  dataIndex: "p95_latency_ms",
                  width: 100,
                  align: "right",
                  render: segundos,
                },
                {
                  title: "Coste",
                  dataIndex: "total_cost_usd",
                  width: 120,
                  align: "right",
                  render: (v: number) => usdCost(v),
                },
                {
                  title: "Errores",
                  dataIndex: "error_rate",
                  width: 100,
                  align: "right",
                  render: (v: number | null) => percent(v),
                },
              ]}
            />
          </Card>

          <Card title="Últimas peticiones" size="small">
            <Table
              size="small"
              rowKey="request_id"
              pagination={false}
              dataSource={summary.recent}
              columns={[
                {
                  title: "Hora",
                  dataIndex: "recorded_at",
                  width: 80,
                  render: (v: string) => hora(v),
                },
                { title: "Ruta", dataIndex: "route", ellipsis: true },
                {
                  title: "Estado",
                  dataIndex: "status",
                  width: 90,
                  render: (v: string) => (
                    <Tag color={v.startsWith("2") || v === "completed" ? "green" : "red"}>{v}</Tag>
                  ),
                },
                {
                  title: "Latencia",
                  dataIndex: "latency_ms",
                  width: 100,
                  align: "right",
                  render: segundos,
                },
                { title: "Tokens", dataIndex: "total_tokens", width: 90, align: "right" },
                {
                  title: "Coste",
                  dataIndex: "estimated_cost",
                  width: 120,
                  align: "right",
                  render: (v: number) => usdCost(v),
                },
              ]}
            />
          </Card>

          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Desde {new Date(summary.since).toLocaleString("es-ES")}. Quedan fuera dos cosas a
            propósito: el <code>/health</code>, que Compose llama cada quince segundos y haría que
            el p95 del servicio fuese el de la sonda, y las lecturas de esta misma pantalla, que si
            se contaran acabarían siendo la ruta más transitada del sistema. El agente de la Sesión
            12 y las llamadas de embeddings sí entran, desde la Sesión 16.
          </Typography.Text>
        </>
      )}
    </Flex>
  );
}
