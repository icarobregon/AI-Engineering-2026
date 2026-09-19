"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Flex,
  Form,
  Input,
  Popconfirm,
  Radio,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";

import { SelectField } from "@/components/select-field";
import { eur } from "@/lib/format";
import {
  detailLevels,
  isOutOfScope,
  outputFormats,
  projectTypes,
  type SessionInfo,
} from "@/lib/estimator/contracts";
import { AcbTrace } from "./acb-trace";
import { resetSession, sendTurn, type TurnState } from "./actions";

const projectTypeLabels = {
  mobile_app: "Aplicación móvil",
  web_saas: "SaaS web",
  internal_tool: "Herramienta interna",
  data_pipeline: "Pipeline de datos",
} as const;
const detailLabels = { summary: "Resumen", medium: "Medio", detailed: "Detallado" } as const;
const formatLabels = {
  phases_table: "Tabla de fases",
  line_items: "Partidas",
  narrative: "Narrativa",
} as const;

const tierOptions = [
  { value: "", label: "Automático" },
  { value: "executive", label: "Dirección" },
  { value: "pm", label: "Gestión de proyecto" },
  { value: "developer", label: "Técnico" },
  { value: "default", label: "Genérico" },
];

function SubmitButton({ acb }: { acb: boolean }) {
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" loading={pending} size="large">
      {pending ? "Estimando…" : acb ? "Enviar turno (2 a 6 llamadas)" : "Enviar turno"}
    </Button>
  );
}

function MetadataPanel({ info }: { info: SessionInfo | null }) {
  if (!info) {
    return (
      <Card title="Conversación">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="Sin conversación abierta. El primer turno la crea."
        />
      </Card>
    );
  }

  const tech = info.metadata.mentioned_technologies;
  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card title="Conversación">
        <Descriptions
          column={1}
          size="small"
          items={[
            {
              key: "id",
              label: "Sesión",
              children: (
                <Typography.Text code copyable style={{ fontSize: 11 }}>
                  {info.session_id}
                </Typography.Text>
              ),
            },
            {
              key: "window",
              label: "Ventana",
              // Messages, not turns: compression pins this at max_turns*2.
              children: `${info.message_count} / ${info.max_turns * 2} mensajes`,
            },
            { key: "anchors", label: "Anclas", children: info.anchors_count },
            { key: "summary", label: "Resumen", children: `${info.summary_chars} caracteres` },
            {
              key: "tier",
              label: "Audiencia",
              children: info.last_resolved_tier ? (
                <Space size={6}>
                  <Tag color="purple">{info.last_resolved_tier}</Tag>
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    {info.last_tier_rule}
                  </Typography.Text>
                </Space>
              ) : (
                "—"
              ),
            },
          ]}
        />
      </Card>

      <Card title="Lo que el sistema ha retenido">
        {info.metadata.project_name || tech.length > 0 || info.metadata.agreed_scope ? (
          <Descriptions
            column={1}
            size="small"
            items={[
              { key: "n", label: "Proyecto", children: info.metadata.project_name ?? "—" },
              {
                key: "t",
                label: "Equipo",
                children: info.metadata.assumed_team_size ?? "—",
              },
              {
                key: "tech",
                label: "Tecnologías",
                children: tech.length > 0 ? tech.map((x) => <Tag key={x}>{x}</Tag>) : "—",
              },
              { key: "s", label: "Alcance", children: info.metadata.agreed_scope ?? "—" },
            ]}
          />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="Envía el primer turno para que se rellene."
          />
        )}
      </Card>
    </Space>
  );
}

export function ChatView({ info }: { info: SessionInfo | null }) {
  const [state, action] = useActionState<TurnState, FormData>(sendTurn, {
    error: null,
    notice: null,
    result: null,
  });
  const [mode, setMode] = useState<"actor" | "acb">("actor");

  const result = state.result;
  const estimate = result?.result;

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="center">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Conversación
        </Typography.Title>
        {info && (
          <Popconfirm
            title="Empezar de cero"
            description="Se abrirá una conversación nueva y se perderá la memoria de esta."
            okText="Empezar"
            cancelText="Cancelar"
            onConfirm={async () => {
              await resetSession();
            }}
          >
            <Button variant="outlined">Nueva conversación</Button>
          </Popconfirm>
        )}
      </Flex>

      <Row gutter={24}>
        <Col span={16}>
          <Space direction="vertical" size={24} style={{ width: "100%" }}>
            <form action={action}>
              <Card>
                <Space direction="vertical" size="large" style={{ width: "100%" }}>
                  {state.error && <Alert type="error" showIcon message={state.error} />}
                  {state.notice && <Alert type="warning" showIcon message={state.notice} />}

                  <Form.Item
                    label="Tu turno"
                    layout="vertical"
                    extra="Sólo lo nuevo: el histórico lo guarda el servicio IA."
                    style={{ marginBottom: 0 }}
                  >
                    <Input.TextArea
                      name="transcript"
                      rows={7}
                      required
                      minLength={20}
                      maxLength={80_000}
                      placeholder="Cuéntale lo siguiente de la reunión…"
                    />
                  </Form.Item>

                  <Form.Item
                    label="Adjuntos"
                    layout="vertical"
                    extra="PDF y DOCX. Su texto se añade al turno antes de estimar."
                    style={{ marginBottom: 0 }}
                  >
                    <input type="file" name="attachments" multiple accept=".pdf,.docx" />
                  </Form.Item>

                  <Space size="large" wrap>
                    <SelectField
                      name="project_type"
                      label="Tipo de proyecto"
                      defaultValue="web_saas"
                      width={200}
                      options={projectTypes.map((v) => ({ value: v, label: projectTypeLabels[v] }))}
                    />
                    <SelectField
                      name="detail_level"
                      label="Nivel de detalle"
                      defaultValue="medium"
                      width={160}
                      options={detailLevels.map((v) => ({ value: v, label: detailLabels[v] }))}
                    />
                    <SelectField
                      name="output_format"
                      label="Formato"
                      defaultValue="phases_table"
                      width={160}
                      options={outputFormats.map((v) => ({ value: v, label: formatLabels[v] }))}
                    />
                    <SelectField
                      name="tier"
                      label="Audiencia"
                      defaultValue=""
                      width={190}
                      options={tierOptions}
                    />
                  </Space>

                  <Form.Item
                    label="Modo"
                    layout="vertical"
                    extra={
                      mode === "acb"
                        ? "El crítico revisa el borrador y el jefe decide: hasta 3 vueltas, 2 llamadas cada una."
                        : "Una sola llamada al modelo."
                    }
                    style={{ marginBottom: 0 }}
                  >
                    <Radio.Group
                      name="mode"
                      value={mode}
                      onChange={(e) => setMode(e.target.value)}
                      optionType="button"
                      buttonStyle="solid"
                      options={[
                        { value: "actor", label: "Actor" },
                        { value: "acb", label: "Actor-Critic-Boss" },
                      ]}
                    />
                  </Form.Item>

                  <SubmitButton acb={mode === "acb"} />
                </Space>
              </Card>
            </form>

            {estimate && (
              <>
                {isOutOfScope(estimate) ? (
                  <Alert
                    type="warning"
                    showIcon
                    message="El servicio se ha negado a estimar"
                    description={estimate.summary}
                  />
                ) : (
                  <Card
                    title="Último resultado"
                    extra={<Tag>{result!.prompt_version}</Tag>}
                    styles={{ body: { paddingBottom: 0 } }}
                  >
                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                      <Typography.Paragraph>{estimate.summary}</Typography.Paragraph>
                      <Row gutter={16}>
                        <Col span={8}>
                          <Statistic
                            title="Duración"
                            value={estimate.total_duration_weeks}
                            suffix="semanas"
                          />
                        </Col>
                        <Col span={8}>
                          <Statistic title="Coste" value={eur(estimate.total_cost_eur)} />
                        </Col>
                        <Col span={8}>
                          <Statistic
                            title="Confianza"
                            value={estimate.confidence_pct}
                            suffix="%"
                          />
                        </Col>
                      </Row>
                      <Table
                        rowKey="name"
                        dataSource={estimate.phases}
                        pagination={false}
                        size="small"
                        columns={[
                          { title: "Fase", dataIndex: "name" },
                          {
                            title: "Semanas",
                            dataIndex: "duration_weeks",
                            width: 100,
                            align: "right",
                          },
                          {
                            title: "Coste",
                            dataIndex: "cost_eur",
                            width: 130,
                            align: "right",
                            render: eur,
                          },
                        ]}
                      />
                    </Space>
                  </Card>
                )}

                {result?.acb && <AcbTrace trace={result.acb} summary={estimate.summary} />}

                {result?.observation && (
                  <Card size="small" title="Telemetría del turno">
                    <Space size="large" wrap>
                      <Statistic
                        title="Latencia"
                        value={(result.observation.latency_ms / 1000).toFixed(1)}
                        suffix="s"
                      />
                      <Statistic
                        title="Tokens"
                        value={`${result.observation.tokens_in} / ${result.observation.tokens_out}`}
                      />
                      <Statistic
                        title="Coste"
                        value={`$${result.observation.cost_usd.toFixed(4)}`}
                      />
                      <Statistic
                        title="Transcripción enriquecida"
                        value={result.observation.enriched_transcript_chars}
                        suffix="car."
                      />
                    </Space>
                  </Card>
                )}
              </>
            )}
          </Space>
        </Col>

        <Col span={8}>
          <MetadataPanel info={info} />
        </Col>
      </Row>
    </Flex>
  );
}
