"use client";

import Link from "next/link";
import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Flex, Form, Input, Space, Typography } from "antd";

import { SelectField } from "@/components/select-field";
import { startIndexRun, type FormState } from "../actions";

/**
 * Un presupuesto de ejemplo, con la forma que el servicio IA espera.
 *
 * Está precargado a propósito: sin él, la primera pregunta de cualquiera es qué
 * forma tiene que tener el JSON, y la respuesta vive en un schema de Pydantic.
 */
const EJEMPLO = JSON.stringify(
  {
    budget_id: "NEW-2026-0001",
    client_metadata: { name: "Cuenta Nueva S.L.", sector: "ecommerce", country: "ES" },
    project_summary: "Portal de reservas con motor de disponibilidad y pagos",
    main_technology: "typescript",
    year: 2026,
    total_estimated_hours: 200,
    components: [
      {
        component_id: "AUTH-001",
        name: "Autenticación y perfiles",
        description: "Registro, inicio de sesión y recuperación de contraseña.",
        tech_stack: ["typescript", "postgresql"],
        estimated_hours: 80,
        complexity: "medium",
      },
      {
        component_id: "BOOK-001",
        name: "Motor de reservas",
        description: "Disponibilidad en tiempo real y confirmación de reserva.",
        tech_stack: ["typescript", "redis"],
        estimated_hours: 120,
        complexity: "high",
      },
    ],
  },
  null,
  2,
);

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" loading={pending} size="large">
      {pending ? "Enviando…" : "Indexar en el corpus"}
    </Button>
  );
}

export function NewRunForm() {
  const [state, action] = useActionState<FormState, FormData>(startIndexRun, { error: null });

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="center">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Añadir información al corpus
        </Typography.Title>
        <Link href="/corpus">
          <Button variant="outlined" icon={<ArrowLeftOutlined />}>
            Corpus
          </Button>
        </Link>
      </Flex>

      <form action={action}>
        <Card>
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            {state.error && <Alert type="error" showIcon message={state.error} />}

            <Typography.Text type="secondary">
              Pega un presupuesto nuevo (un objeto JSON) o varios (un array de objetos). Se
              indexan de uno en uno y verás el progreso. Un documento que el servicio ya tenga se
              salta, no se duplica.
            </Typography.Text>

            <SelectField
              name="chunk_type"
              label="Tipo de chunk"
              defaultValue="budget_component"
              width={240}
              options={[
                { value: "budget_component", label: "Componente de presupuesto" },
                { value: "historical_task", label: "Tarea histórica" },
              ]}
            />

            <Form.Item
              label="Documentos (JSON)"
              layout="vertical"
              extra="El tipo de chunk y la forma del JSON tienen que casar: un presupuesto va con «componente de presupuesto». Cada componente necesita component_id, name, description, estimated_hours y complexity (low, medium o high)."
              style={{ marginBottom: 0 }}
            >
              <Input.TextArea
                name="documents"
                rows={18}
                required
                defaultValue={EJEMPLO}
                style={{ fontFamily: "var(--font-geist-mono), monospace", fontSize: 12 }}
              />
            </Form.Item>

            <Space size="large">
              <SubmitButton />
              <Link href="/corpus">
                <Button type="link">Cancelar</Button>
              </Link>
            </Space>
          </Space>
        </Card>
      </form>
    </Flex>
  );
}
