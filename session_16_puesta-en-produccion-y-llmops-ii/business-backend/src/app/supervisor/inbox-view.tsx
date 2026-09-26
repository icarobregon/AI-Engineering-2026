"use client";

import Link from "next/link";
import { ArrowRightOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Flex, Table, Tag, Typography } from "antd";

import { percent } from "@/lib/format";
import { AWAITING_REVIEW, statusLabel } from "@/lib/supervisor";

export type RunRow = {
  id: string;
  createdAt: Date;
  title: string | null;
  origen: string | null;
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
      /*
        El título y no la transcripción. Un recorte a 90 caracteres empieza casi
        siempre por la misma fórmula de acta —«Reunión de descubrimiento —
        Proyecto…»— y con dos ejecuciones de la misma reunión los dos recortes
        salían idénticos: la columna ocupaba el ancho sin distinguir nada. El
        título que pone el sistema sí dice de qué va cada una.
      */
      title: "Título",
      key: "title",
      render: (_: unknown, row: RunRow) =>
        row.title ??
        (row.origen ? (
          /*
            Todavía no hay título —en curso, o muerta antes de estimar— así que
            se enseña de dónde salió. Atenuado y en cursiva a propósito: dice que
            esto no es el nombre que puso el sistema, sino la línea de la que
            partió, y así una fila a medias no se confunde con una terminada.
          */
          <Typography.Text type="secondary" italic>
            {row.origen}
          </Typography.Text>
        ) : (
          // Ni título ni transcripción con contenido: la misma raya con la que
          // Confianza dice «no lo sé».
          <Typography.Text type="secondary">—</Typography.Text>
        )),
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
