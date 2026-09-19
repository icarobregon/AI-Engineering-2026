"use client";

import Link from "next/link";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Flex, Row, Space, Statistic, Table, Tag, Typography } from "antd";

import { estimationResponseSchema, isOutOfScope } from "@/lib/estimator/contracts";
import { eur } from "@/lib/format";

export function EstimationView({
  promptVersion,
  cached,
  payload,
}: {
  promptVersion: string;
  cached: boolean;
  payload: unknown;
}) {
  // Parsed, not cast: this payload was written by a version of the contract that
  // may no longer be the current one, and a silent shape change should say so.
  const parsed = estimationResponseSchema.safeParse(payload);
  if (!parsed.success) {
    return (
      <Alert
        type="error"
        showIcon
        message="Esta estimación se guardó con un contrato que ya no se reconoce"
        description={parsed.error.issues.map((i) => i.message).join("; ")}
      />
    );
  }
  const { result } = parsed.data;

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="center">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Estimación
        </Typography.Title>
        <Space>
          <Tag>{promptVersion}</Tag>
          {cached && <Tag color="blue">caché</Tag>}
          <Link href="/estimations">
            <Button variant="outlined" icon={<ArrowLeftOutlined />}>
              Histórico
            </Button>
          </Link>
        </Space>
      </Flex>

      {isOutOfScope(result) ? (
        <Alert
          type="warning"
          showIcon
          message="El servicio se ha negado a estimar"
          description={result.summary}
        />
      ) : (
        <>
          <Card>
            <Typography.Paragraph style={{ marginBottom: 0 }}>{result.summary}</Typography.Paragraph>
          </Card>

          <Row gutter={16}>
            <Col span={8}>
              <Card>
                <Statistic title="Duración" value={result.total_duration_weeks} suffix="semanas" />
              </Card>
            </Col>
            <Col span={8}>
              <Card>
                <Statistic title="Coste" value={eur(result.total_cost_eur)} />
              </Card>
            </Col>
            <Col span={8}>
              <Card>
                <Statistic title="Confianza" value={result.confidence_pct} suffix="%" />
              </Card>
            </Col>
          </Row>

          <Card title="Fases" styles={{ body: { padding: 0 } }}>
            <Table
              rowKey="name"
              dataSource={result.phases}
              pagination={false}
              columns={[
                {
                  title: "Fase",
                  dataIndex: "name",
                  render: (value: string, phase) => (
                    <Space direction="vertical" size={0}>
                      <Typography.Text strong>{value}</Typography.Text>
                      <Typography.Text type="secondary">{phase.summary}</Typography.Text>
                    </Space>
                  ),
                },
                { title: "Semanas", dataIndex: "duration_weeks", width: 110, align: "right" },
                {
                  title: "Coste",
                  dataIndex: "cost_eur",
                  width: 140,
                  align: "right",
                  render: (value: number) => eur(value),
                },
              ]}
            />
          </Card>
        </>
      )}
    </Flex>
  );
}
