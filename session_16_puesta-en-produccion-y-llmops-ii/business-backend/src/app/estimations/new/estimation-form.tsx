"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";

import { createEstimation, type FormState } from "../actions";
import { SelectField } from "@/components/select-field";
import { detailLevels, outputFormats, projectTypes } from "@/lib/estimator/contracts";

const projectTypeLabels: Record<(typeof projectTypes)[number], string> = {
  mobile_app: "Aplicación móvil",
  web_saas: "SaaS web",
  internal_tool: "Herramienta interna",
  data_pipeline: "Pipeline de datos",
};

const detailLabels: Record<(typeof detailLevels)[number], string> = {
  summary: "Resumen",
  medium: "Medio",
  detailed: "Detallado",
};

const formatLabels: Record<(typeof outputFormats)[number], string> = {
  phases_table: "Tabla de fases",
  line_items: "Partidas",
  narrative: "Narrativa",
};

const options = <T extends string>(values: readonly T[], labels: Record<T, string>) =>
  values.map((value) => ({ value, label: labels[value] }));

function SubmitButton() {
  // An estimate takes seconds. Without this the page looks frozen and people
  // submit twice, which is two LLM calls for one answer.
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" loading={pending} size="large">
      {pending ? "Estimando…" : "Estimar"}
    </Button>
  );
}

export function EstimationForm() {
  const [state, action] = useActionState<FormState, FormData>(createEstimation, { error: null });

  return (
    <Card>
      <form action={action}>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          {state.error && (
            <Alert
              type="error"
              showIcon
              message={state.error}
              description={state.reason ? `Regla: ${state.reason}` : undefined}
            />
          )}

          <Form.Item
            label="Descripción o transcripción"
            layout="vertical"
            extra="Entre 20 y 80.000 caracteres — el mismo límite que exige el servicio IA."
            style={{ marginBottom: 0 }}
          >
            <Input.TextArea
              name="description"
              rows={12}
              required
              minLength={20}
              maxLength={80_000}
              placeholder="Pega aquí la transcripción de la reunión con el cliente…"
            />
          </Form.Item>

          <Space size="large" wrap>
            <SelectField
              name="project_type"
              label="Tipo de proyecto"
              defaultValue="web_saas"
              width={220}
              options={options(projectTypes, projectTypeLabels)}
            />
            <SelectField
              name="detail_level"
              label="Nivel de detalle"
              defaultValue="medium"
              width={180}
              options={options(detailLevels, detailLabels)}
            />
            <SelectField
              name="output_format"
              label="Formato"
              defaultValue="phases_table"
              width={180}
              options={options(outputFormats, formatLabels)}
            />
          </Space>

          <Space align="center" size="middle">
            <SubmitButton />
            <Typography.Text type="secondary">
              La petición viaja al servicio IA por la red interna; la clave nunca sale del servidor.
            </Typography.Text>
          </Space>
        </Space>
      </form>
    </Card>
  );
}
