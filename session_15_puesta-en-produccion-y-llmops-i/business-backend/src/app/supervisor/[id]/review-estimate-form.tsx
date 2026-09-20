"use client";

import { useMemo, useState } from "react";
import { useFormStatus } from "react-dom";
import {
  Alert,
  Button,
  Card,
  Flex,
  Form,
  Input,
  InputNumber,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";

import { hours } from "@/lib/format";
import type { DraftEstimate } from "@/lib/estimator/contracts";
import { submitReview, type FormState } from "../actions";

/**
 * La estimación, editable, con la decisión dentro.
 *
 * Una sola tarjeta y un solo formulario a propósito: revisar es poner precio y
 * firmar, no dos gestos separados. Con la decisión en una tarjeta aparte se
 * podía aprobar sin haber mirado el desglose que se estaba aprobando.
 *
 * El TOTAL no se teclea ni se manda: se deriva de la suma en cada pulsación, y
 * el servicio lo vuelve a derivar al aplicarlo. Que nadie pueda escribirlo es lo
 * que hace imposible que la cifra de abajo y el desglose se contradigan.
 */

function Botones({ faltaFirma, sinPrecio }: { faltaFirma: boolean; sinPrecio: string[] }) {
  // Dentro del form para poder leer `pending`: fuera, useFormStatus no ve nada.
  const { pending } = useFormStatus();

  // Un botón deshabilitado sin decir por qué es una pantalla que no responde.
  const aviso = faltaFirma
    ? "Revisor y Motivo son obligatorios: una decisión sin constancia de quién y por qué no se puede auditar."
    : sinPrecio.length > 0
      ? `No se puede aprobar con ${sinPrecio.length} componente(s) a 0 h: ${sinPrecio.join(", ")}. ` +
        "Un presupuesto con una línea a cero le dice al cliente que esa pieza es gratis. " +
        "Rechazar sí está disponible."
      : null;

  return (
    <Space direction="vertical" size="small" style={{ width: "100%" }}>
      {aviso && <Alert type="info" showIcon message={aviso} />}
      <Space>
        <Button
          type="primary"
          htmlType="submit"
          name="action"
          value="approve"
          size="large"
          loading={pending}
          disabled={faltaFirma || sinPrecio.length > 0}
        >
          Aprobar
        </Button>
        <Button
          danger
          htmlType="submit"
          name="action"
          value="reject"
          size="large"
          loading={pending}
          // Rechazar sólo exige la firma: un componente sin precio es
          // precisamente una de las razones por las que se rechaza.
          disabled={faltaFirma}
        >
          Rechazar
        </Button>
      </Space>
    </Space>
  );
}

export function ReviewEstimateForm({ id, estimate }: { id: string; estimate: DraftEstimate }) {
  const [horas, setHoras] = useState<Record<string, number | null>>(() =>
    Object.fromEntries(estimate.components.map((c) => [c.component_id, c.estimated_hours])),
  );
  const [revisor, setRevisor] = useState("");
  const [motivo, setMotivo] = useState("");
  const [error, setError] = useState<string | null>(null);

  const total = useMemo(
    () => Object.values(horas).reduce<number>((suma, h) => suma + (h ?? 0), 0),
    [horas],
  );
  const sinPrecio = estimate.components.filter((c) => !horas[c.component_id]).map((c) => c.name);
  const faltaFirma = revisor.trim().length === 0 || motivo.trim().length === 0;

  async function enviar(formData: FormData) {
    const resultado: FormState = await submitReview({ error: null }, formData);
    setError(resultado.error);
  }

  return (
    <Card
      title={estimate.project || "Desglose"}
      extra={
        <Space>
          <Typography.Text type="secondary">Total a aprobar</Typography.Text>
          <Typography.Text strong style={{ fontSize: 16 }}>
            {hours(total)}
          </Typography.Text>
        </Space>
      }
      /*
        A ras de los bordes, como el resto de tablas de estas vistas. La gemela
        de sólo lectura (`EstimateTable`) pinta EXACTAMENTE este desglose así, y
        con el relleno puesto el mismo contenido se veía distinto según si la
        ejecución estaba en pausa o cerrada.
      */
      styles={{ body: { padding: 0 } }}
    >
      <form action={enviar}>
        <input type="hidden" name="id" value={id} />
        {/* El puente que ya usa el resto de la app: AntD no escribe en el form. */}
        <input type="hidden" name="component_hours" value={JSON.stringify(horas)} />

        <Table
          rowKey="component_id"
          dataSource={estimate.components}
          pagination={false}
          columns={[
            {
              title: "Componente",
              dataIndex: "name",
              render: (value: string, row) => (
                <Space direction="vertical" size={0}>
                  <Typography.Text strong>{value}</Typography.Text>
                  <Typography.Text type="secondary">{row.rationale}</Typography.Text>
                </Space>
              ),
            },
            {
              // La etiqueta NO cambia aunque el revisor ponga un número: el
              // grounding habla de si hay evidencia histórica, no de si hay
              // cifra, y el cliente tiene que poder verlo en el documento final.
              title: "Evidencia",
              dataIndex: "grounded",
              width: 130,
              render: (grounded: boolean) =>
                grounded ? (
                  <Tag color="green">Con precedente</Tag>
                ) : (
                  <Tag color="red">Sin precedente</Tag>
                ),
            },
            {
              title: "Horas",
              dataIndex: "estimated_hours",
              width: 150,
              align: "right",
              render: (_valor: number, row) => (
                <InputNumber
                  aria-label={`Horas de ${row.name}`}
                  value={horas[row.component_id]}
                  onChange={(v) =>
                    setHoras((previas) => ({
                      ...previas,
                      [row.component_id]: v as number | null,
                    }))
                  }
                  min={0}
                  step={0.5}
                  precision={1}
                  // `suffix` y no `addonAfter`: el segundo está deprecado en antd 6.
                  suffix="h"
                  status={horas[row.component_id] ? undefined : "error"}
                  style={{ width: 130 }}
                />
              ),
            },
          ]}
        />

        {/*
          Sin `Divider`: la última fila de la tabla ya trae su propio borde
          inferior, así que eran dos líneas grises separadas por el margen del
          divisor. Se queda la de la tabla —la que delimita el desglose— y aquí
          sólo el aire que antes ponía el divisor, para que los campos no se
          peguen al último componente.
        */}
        <Space
          direction="vertical"
          size="large"
          // El cuerpo del Card ya no tiene relleno para que la tabla vaya a
          // ras, así que lo pone aquí la mitad de abajo: si no, los campos y
          // los botones quedarían pegados a los bordes de la tarjeta.
          style={{ width: "100%", padding: 24 }}
        >
          {error && <Alert type="error" showIcon message={error} />}

          <Flex gap={16} wrap>
            <Form.Item
              label="Revisor"
              layout="vertical"
              required
              style={{ marginBottom: 0, flex: "1 1 280px" }}
            >
              <Input
                name="reviewer_id"
                value={revisor}
                onChange={(e) => setRevisor(e.target.value)}
                placeholder="tu.nombre@empresa.com"
              />
            </Form.Item>
            <Form.Item
              label="Motivo"
              layout="vertical"
              required
              style={{ marginBottom: 0, flex: "2 1 420px" }}
            >
              <Input
                name="comment"
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                placeholder="Por qué apruebas o rechazas, y qué has cambiado."
              />
            </Form.Item>
          </Flex>

          <Botones faltaFirma={faltaFirma} sinPrecio={sinPrecio} />
        </Space>
      </form>
    </Card>
  );
}
