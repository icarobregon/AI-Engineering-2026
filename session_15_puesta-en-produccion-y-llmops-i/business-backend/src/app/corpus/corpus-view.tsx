"use client";

import Link from "next/link";
import { Alert, Button, Card, Empty, Flex, Space, Table, Typography } from "antd";

import type { CorpusStats } from "@/lib/estimator/contracts";
import { CorpusStatsTable, statusTag } from "./corpus-pieces";

type Run = {
  id: string;
  chunkType: string;
  submittedCount: number;
  processedCount: number;
  chunksCreated: number;
  status: string;
  createdAt: Date;
};

export function CorpusView({
  stats,
  statsError,
  runs,
}: {
  stats: CorpusStats | null;
  statsError: string | null;
  runs: Run[];
}) {
  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="flex-start" gap={16}>
        <Space direction="vertical" size={4}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Corpus e índice
          </Typography.Title>
          <Typography.Text type="secondary">
            Amplía la base vectorial con información nueva. Cada documento se trocea, se embebe y
            se indexa. Re-embeber lo que ya existe queda fuera.
          </Typography.Text>
        </Space>
        <Link href="/corpus/nueva">
          <Button type="primary">Añadir información</Button>
        </Link>
      </Flex>

      {/* La app de referencia escribe este error en un flash que su plantilla no
          pinta: el panel desaparece y nadie sabe por qué. Aquí se dice. */}
      {statsError && <Alert type="warning" showIcon message={statsError} />}

      {stats && (
        <Card
          title={
            <Space>
              <span>Estado del corpus</span>
              <Typography.Text type="secondary">
                {stats.total_chunks.toLocaleString("es-ES")} chunks ·{" "}
                {stats.total_documents.toLocaleString("es-ES")} documentos
              </Typography.Text>
            </Space>
          }
          styles={{ body: { padding: 0 } }}
        >
          <CorpusStatsTable collections={stats.collections} />
        </Card>
      )}

      <Card title="Ampliaciones recientes" styles={{ body: { padding: 0 } }}>
        {runs.length === 0 ? (
          <div style={{ padding: 24 }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Aún no hay ampliaciones. Empieza una nueva."
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
                render: (value: Date) => new Date(value).toLocaleString("es-ES"),
              },
              {
                title: "Tipo de chunk",
                dataIndex: "chunkType",
                render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
              },
              {
                title: "Documentos",
                key: "docs",
                align: "right",
                width: 130,
                render: (_, row) => `${row.processedCount} / ${row.submittedCount}`,
              },
              {
                title: "Chunks nuevos",
                dataIndex: "chunksCreated",
                align: "right",
                width: 130,
              },
              {
                title: "Estado",
                dataIndex: "status",
                width: 130,
                render: (value: string) => statusTag(value),
              },
              {
                key: "ver",
                align: "right",
                width: 100,
                render: (_, row) => (
                  <Link href={`/corpus/${row.id}`}>
                    <Button variant="outlined" size="small">
                      Ver
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
