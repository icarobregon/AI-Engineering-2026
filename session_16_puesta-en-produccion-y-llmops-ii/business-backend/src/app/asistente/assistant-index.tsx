"use client";

import Link from "next/link";
import { Button, Card, Empty, Flex, Space, Table, Tag, Typography } from "antd";

import { eur, hours as horas } from "@/lib/format";
import { stepLabels } from "./steps";

type Run = {
  id: string;
  preview: string;
  currentStep: string;
  confirmedAt: string | null;
  totalHours: number | null;
  totalCostEur: number | null;
  createdAt: string;
};

export function AssistantIndex({ runs }: { runs: Run[] }) {
  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="flex-start" gap={16}>
        <Space direction="vertical" size={4}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Asistente de estimación
          </Typography.Title>
          <Typography.Text type="secondary">
            De una transcripción a una estimación fundamentada, en cinco pasos y con una persona
            revisando entre medias. Cada paso se puede volver a ejecutar.
          </Typography.Text>
        </Space>
        <Link href="/asistente/nueva">
          <Button type="primary">Nueva estimación</Button>
        </Link>
      </Flex>

      <Card styles={{ body: { padding: 0 } }}>
        {runs.length === 0 ? (
          <div style={{ padding: 24 }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Aún no hay estimaciones. Empieza pegando una transcripción."
            />
          </div>
        ) : (
          <Table
            rowKey="id"
            dataSource={runs}
            pagination={false}
            size="small"
            columns={[
              {
                title: "Creada",
                dataIndex: "createdAt",
                width: 160,
                render: (value: string) => new Date(value).toLocaleString("es-ES"),
              },
              {
                title: "Transcripción",
                dataIndex: "preview",
                render: (value: string) => (
                  <Typography.Text type="secondary">{value}…</Typography.Text>
                ),
              },
              {
                title: "Paso",
                dataIndex: "currentStep",
                width: 150,
                render: (value: string, row) =>
                  row.confirmedAt ? (
                    <Tag color="success">confirmada</Tag>
                  ) : (
                    <Tag color="processing">{stepLabels[value] ?? value}</Tag>
                  ),
              },
              {
                title: "Horas",
                dataIndex: "totalHours",
                align: "right",
                width: 100,
                render: (value: number | null) => (value == null ? "—" : horas(value)),
              },
              {
                title: "Coste",
                dataIndex: "totalCostEur",
                align: "right",
                width: 120,
                render: (value: number | null) => (value == null ? "—" : eur(value)),
              },
              {
                key: "ver",
                align: "right",
                width: 100,
                render: (_, row) => (
                  <Link href={`/asistente/${row.id}`}>
                    <Button variant="outlined" size="small">
                      Abrir
                    </Button>
                  </Link>
                ),
              },
            ]}
          />
        )}
      </Card>
    </Flex>
  );
}
