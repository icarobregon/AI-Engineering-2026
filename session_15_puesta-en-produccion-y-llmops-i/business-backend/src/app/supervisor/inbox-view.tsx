"use client";

import Link from "next/link";
import { ArrowRightOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Flex, Table, Tag, Typography } from "antd";

import { percent } from "@/lib/format";
import { AWAITING_REVIEW, statusLabel } from "@/lib/supervisor";

export type RunRow = {
  id: string;
  createdAt: Date;
  transcript: string;
  confidence: number | null;
  status: string | null;
};

export function InboxView({ awaiting, recent }: { awaiting: RunRow[]; recent: RunRow[] }) {
  const columns = [
    {
      title: "Creada",
      dataIndex: "createdAt",
      width: 170,
      render: (value: Date) => new Date(value).toLocaleString("es-ES"),
    },
    {
      title: "Transcripción",
      dataIndex: "transcript",
      render: (value: string) => (value.length > 90 ? `${value.slice(0, 90)}…` : value),
    },
    {
      title: "Confianza",
      dataIndex: "confidence",
      width: 110,
      align: "right" as const,
      render: (value: number | null) => percent(value),
    },
    {
      title: "Estado",
      dataIndex: "status",
      width: 190,
      render: (value: string | null) => {
        const { text, color } = statusLabel(value);
        return <Tag color={color}>{text}</Tag>;
      },
    },
    {
      title: "",
      key: "open",
      width: 90,
      render: (_: unknown, row: RunRow) => (
        <Link href={`/supervisor/${row.id}`}>
          <Button variant="outlined" size="small" icon={<ArrowRightOutlined />} iconPosition="end">
            {row.status === AWAITING_REVIEW ? "Revisar" : "Ver"}
          </Button>
        </Link>
      ),
    },
  ];

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="center">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Supervisor
        </Typography.Title>
        <Link href="/supervisor/new">
          <Button type="primary">Nueva estimación</Button>
        </Link>
      </Flex>

      <Card
        title={`Esperando revisión (${awaiting.length})`}
        styles={{ body: { padding: awaiting.length === 0 ? 24 : 0 } }}
      >
        {awaiting.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="Nada pendiente. Una puerta que casi nunca se dispara es una puerta que funciona."
          />
        ) : (
          <Table rowKey="id" dataSource={awaiting} columns={columns} pagination={false} />
        )}
      </Card>

      <Card title="Histórico" styles={{ body: { padding: recent.length === 0 ? 24 : 0 } }}>
        {recent.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Sin ejecuciones todavía" />
        ) : (
          <Table rowKey="id" dataSource={recent} columns={columns} pagination={false} />
        )}
      </Card>
    </Flex>
  );
}
