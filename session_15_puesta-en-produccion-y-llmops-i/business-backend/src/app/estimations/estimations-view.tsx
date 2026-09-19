"use client";

import Link from "next/link";
import { Button, Card, Empty, Flex, Space, Table, Tag, Typography } from "antd";

const typeLabels: Record<string, string> = {
  mobile_app: "Aplicación móvil",
  web_saas: "SaaS web",
  internal_tool: "Herramienta interna",
  data_pipeline: "Pipeline de datos",
};

export type EstimationRow = {
  id: string;
  createdAt: Date;
  projectType: string;
  description: string;
  promptVersion: string;
  cached: boolean;
};

export function EstimationsView({ rows }: { rows: EstimationRow[] }) {
  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="center">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Estimaciones
        </Typography.Title>
        <Link href="/estimations/new">
          <Button type="primary">Nueva estimación</Button>
        </Link>
      </Flex>

      <Card styles={{ body: { padding: rows.length === 0 ? 24 : 0 } }}>
        {rows.length === 0 ? (
          <Empty description="Todavía no hay estimaciones">
            <Link href="/estimations/new">
              <Button type="primary">Crear la primera</Button>
            </Link>
          </Empty>
        ) : (
          <Table
            rowKey="id"
            dataSource={rows}
            pagination={false}
            columns={[
              {
                title: "Fecha",
                dataIndex: "createdAt",
                width: 170,
                render: (value: Date) => new Date(value).toLocaleString("es-ES"),
              },
              {
                title: "Tipo",
                dataIndex: "projectType",
                width: 170,
                render: (value: string) => typeLabels[value] ?? value,
              },
              {
                title: "Descripción",
                dataIndex: "description",
                render: (value: string) => (value.length > 80 ? `${value.slice(0, 80)}…` : value),
              },
              {
                title: "",
                key: "badges",
                width: 160,
                render: (_, row) => (
                  <Space size={4}>
                    <Tag>{row.promptVersion}</Tag>
                    {row.cached && <Tag color="blue">caché</Tag>}
                  </Space>
                ),
              },
              {
                title: "",
                key: "open",
                width: 70,
                render: (_, row) => <Link href={`/estimations/${row.id}`}>Ver →</Link>,
              },
            ]}
          />
        )}
      </Card>
    </Flex>
  );
}
