"use client";

import { Tag } from "antd";

/** El estado de una ejecución. `failed` en rojo: un fallo no se pinta en verde. */
export function statusTag(status: string) {
  if (status === "completed") return <Tag color="success">completada</Tag>;
  if (status === "failed") return <Tag color="error">fallida</Tag>;
  if (status === "running") return <Tag color="processing">corriendo</Tag>;
  return <Tag>en cola</Tag>;
}
