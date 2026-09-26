"use client";

import { Table, Tag, Typography } from "antd";

import type { CollectionStat } from "@/lib/estimator/contracts";

const etiquetas: Record<string, string> = {
  budget: "Presupuestos históricos",
  transcript: "Transcripciones",
  technical_doc: "Documentación técnica",
};

/**
 * La tabla del corpus, compartida por el índice y por el detalle.
 *
 * Vive aparte porque el detalle la pinta DOS veces —antes y después— y el
 * índice una; tenerla en un sitio evita que las tres se separen.
 */
export function CorpusStatsTable({ collections }: { collections: CollectionStat[] }) {
  return (
    <Table
      rowKey="collection"
      dataSource={collections}
      pagination={false}
      size="small"
      columns={[
        {
          title: "Colección",
          dataIndex: "collection",
          render: (value: string) => (
            <div>
              <div>{etiquetas[value] ?? value}</div>
              <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
                {value}
              </Typography.Text>
            </div>
          ),
        },
        { title: "Documentos", dataIndex: "documents", align: "right", width: 110 },
        { title: "Chunks", dataIndex: "chunks", align: "right", width: 100 },
        {
          title: "Índice",
          dataIndex: "hnsw_indexed",
          align: "right",
          width: 140,
          render: (indexado: boolean, fila: CollectionStat) =>
            indexado ? (
              <Tag color="success">HNSW</Tag>
            ) : fila.chunks === 0 ? (
              <Typography.Text type="secondary">—</Typography.Text>
            ) : (
              // Con la colección vacía la ausencia de índice no dice nada; con
              // chunks dentro significa que cada búsqueda los recorre todos.
              <Tag color="warning">recorrido secuencial</Tag>
            ),
        },
      ]}
    />
  );
}

/** El estado de una ampliación. `failed` en rojo: un fallo no se pinta en verde. */
export function statusTag(status: string) {
  if (status === "completed") return <Tag color="success">completada</Tag>;
  if (status === "failed") return <Tag color="error">fallida</Tag>;
  if (status === "running") return <Tag color="processing">indexando</Tag>;
  return <Tag>en cola</Tag>;
}
