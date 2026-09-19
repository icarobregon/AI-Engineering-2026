"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import {
  Alert,
  Card,
  Checkbox,
  Collapse,
  Flex,
  Form,
  Input,
  InputNumber,
  Progress,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { Button } from "antd";

import {
  chunkingStrategies,
  defaultStrategies,
  type ChunkingStats,
  type StrategyName,
} from "@/lib/estimator/contracts";
import { runComparison, type FormState } from "./actions";

const usd = (v: number) => (v === 0 ? "—" : `$${v.toFixed(4)}`);
const secs = (v: number) => `${v.toFixed(1)} s`;

function SubmitButton({ paid }: { paid: boolean }) {
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" loading={pending} size="large" danger={paid}>
      {pending ? "Comparando…" : paid ? "Comparar (gasta dinero)" : "Comparar"}
    </Button>
  );
}

export function ChunkingLab({ corpusSize }: { corpusSize: number }) {
  const [state, action] = useActionState<FormState, FormData>(runComparison, {
    error: null,
    result: null,
  });
  const [selected, setSelected] = useState<StrategyName[]>(defaultStrategies);

  const paid = chunkingStrategies.filter((s) => s.paid && selected.includes(s.name));
  const stats = Object.values(state.result?.stats_per_strategy ?? {});
  const maxCost = Math.max(...stats.map((s) => s.ingestion_cost_usd), 0.000001);
  const maxSecs = Math.max(...stats.map((s) => s.ingestion_seconds), 0.001);
  const playground = Object.entries(state.result?.queries_per_strategy ?? {});

  return (
    <Flex vertical gap={24}>
      <Space direction="vertical" size={4}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Laboratorio de chunking
        </Typography.Title>
        <Typography.Text type="secondary">
          Trocea los mismos {corpusSize} presupuestos con varias estrategias y compara qué sale.
          Nada se persiste: la comparación se ejecuta y se muestra aquí.
        </Typography.Text>
      </Space>

      <form action={action}>
        <Card>
          <Flex vertical gap={20}>
            {state.error && <Alert type="error" showIcon message={state.error} />}

            <Form.Item label="Estrategias" layout="vertical" style={{ marginBottom: 0 }}>
              {/* antd renders its own inputs, so a `name` on Checkbox never
                  reaches FormData. The hidden inputs are the bridge, same as
                  with the selects elsewhere in the app. */}
              {selected.map((s) => (
                <input key={s} type="hidden" name="strategies" value={s} />
              ))}
              <Checkbox.Group
                value={selected}
                onChange={(v) => setSelected(v as StrategyName[])}
                style={{ width: "100%" }}
              >
                <Flex wrap gap={12}>
                  {chunkingStrategies.map((s) => (
                    <Checkbox key={s.name} value={s.name} style={{ width: 230 }}>
                      <Space direction="vertical" size={0}>
                        <Space size={6}>
                          <Typography.Text>{s.label}</Typography.Text>
                          {s.paid && <Tag color="red">$</Tag>}
                        </Space>
                        <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
                          {s.name}
                        </Typography.Text>
                      </Space>
                    </Checkbox>
                  ))}
                </Flex>
              </Checkbox.Group>
            </Form.Item>

            {/* The live cost hint: the reference app has the same, and it is the
                thing that stops somebody ticking every box out of curiosity. */}
            {paid.length > 0 ? (
              <Alert
                type="warning"
                showIcon
                message={`${paid.length} estrategia(s) de pago seleccionada(s)`}
                description={`${paid
                  .map((s) => `${s.label} (${s.provider})`)
                  .join(", ")} llaman al proveedor una vez por componente: el run puede tardar minutos y gasta dinero real.`}
              />
            ) : (
              <Typography.Text type="secondary">
                Sólo estrategias gratuitas: el run tarda segundos y no llama a ningún proveedor.
              </Typography.Text>
            )}

            <Space size="large" align="start" wrap>
              <Form.Item
                label="Consultas (una por línea)"
                layout="vertical"
                extra="Opcional. Con consultas se ejecuta además el playground de recuperación."
                style={{ marginBottom: 0 }}
              >
                <Input.TextArea
                  name="queries"
                  rows={4}
                  style={{ width: 440 }}
                  placeholder={"OAuth authentication for fintech mobile app\nreal-time inventory synchronization"}
                />
              </Form.Item>
              <Form.Item label="top_k" layout="vertical" style={{ marginBottom: 0 }}>
                <InputNumber name="top_k" min={1} max={10} defaultValue={3} />
              </Form.Item>
            </Space>

            <SubmitButton paid={paid.length > 0} />
          </Flex>
        </Card>
      </form>

      {stats.length > 0 && (
        <>
          <Card title="Estadísticas por estrategia" styles={{ body: { padding: 0 } }}>
            <Table
              rowKey="strategy"
              dataSource={stats}
              pagination={false}
              size="small"
              columns={[
                {
                  title: "Estrategia",
                  dataIndex: "strategy",
                  render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
                },
                { title: "Chunks", dataIndex: "n_chunks", align: "right", width: 90 },
                {
                  title: "Tokens (mín / p50 / p95 / máx)",
                  key: "tokens",
                  width: 230,
                  render: (_, s: ChunkingStats) =>
                    `${s.token_distribution.min} / ${s.token_distribution.p50} / ${s.token_distribution.p95} / ${s.token_distribution.max}`,
                },
                {
                  title: "Huérfanos",
                  dataIndex: "n_orphan_chunks",
                  align: "right",
                  width: 110,
                  render: (v: number) => (v > 0 ? <Tag color="orange">{v}</Tag> : v),
                },
                {
                  title: "Obesos",
                  dataIndex: "n_obese_chunks",
                  align: "right",
                  width: 100,
                  render: (v: number) => (v > 0 ? <Tag color="red">{v}</Tag> : v),
                },
                {
                  title: "Coste",
                  dataIndex: "ingestion_cost_usd",
                  align: "right",
                  width: 100,
                  render: usd,
                },
                {
                  title: "Tiempo",
                  dataIndex: "ingestion_seconds",
                  align: "right",
                  width: 100,
                  render: secs,
                },
              ]}
            />
          </Card>

          <Card title="Coste y tiempo, en proporción">
            <Typography.Paragraph type="secondary">
              El coste sólo cuenta las llamadas extra del troceador. Embeber los chunks para el
              playground no entra en este número, así que infravalora el gasto real.
            </Typography.Paragraph>
            <Flex vertical gap={12}>
              {stats.map((s) => (
                <Flex key={s.strategy} align="center" gap={12}>
                  <Typography.Text code style={{ width: 190 }}>
                    {s.strategy}
                  </Typography.Text>
                  <Progress
                    percent={Math.round((s.ingestion_cost_usd / maxCost) * 100)}
                    format={() => usd(s.ingestion_cost_usd)}
                    strokeColor="#cf1322"
                    style={{ flex: 1 }}
                  />
                  <Progress
                    percent={Math.round((s.ingestion_seconds / maxSecs) * 100)}
                    format={() => secs(s.ingestion_seconds)}
                    strokeColor="#5b21b6"
                    style={{ flex: 1 }}
                  />
                </Flex>
              ))}
            </Flex>
          </Card>
        </>
      )}

      {playground.length > 0 && (
        <Card title="Playground de recuperación" styles={{ body: { padding: 0 } }}>
          <Collapse
            ghost
            items={playground.map(([strategy, results]) => ({
              key: strategy,
              label: <Typography.Text code>{strategy}</Typography.Text>,
              children: (
                <Flex vertical gap={16}>
                  {results.map((r, i) => (
                    <Card key={i} size="small" title={`«${r.query}»`}>
                      <Table
                        rowKey="chunk_id"
                        dataSource={r.top_k}
                        pagination={false}
                        size="small"
                        columns={[
                          {
                            title: "cos",
                            dataIndex: "cosine",
                            width: 80,
                            align: "right",
                            render: (v: number) => v.toFixed(3),
                          },
                          {
                            title: "chunk",
                            dataIndex: "chunk_id",
                            width: 260,
                            render: (v: string) => (
                              <Typography.Text code style={{ fontSize: 11 }}>
                                {v}
                              </Typography.Text>
                            ),
                          },
                          { title: "Extracto", dataIndex: "text_preview" },
                        ]}
                      />
                    </Card>
                  ))}
                </Flex>
              ),
            }))}
          />
        </Card>
      )}
    </Flex>
  );
}
