"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { Alert, Button, Card, Form, Input, InputNumber, Radio, Space } from "antd";

import { submitReview, type FormState } from "../actions";
import type { HumanAction } from "@/lib/estimator/contracts";

function SubmitButton({ action }: { action: HumanAction }) {
  const { pending } = useFormStatus();
  const label = { approve: "Aprobar", adjust: "Ajustar y aprobar", reject: "Rechazar" }[action];
  return (
    <Button
      type="primary"
      danger={action === "reject"}
      htmlType="submit"
      loading={pending}
      size="large"
    >
      {pending ? "Enviando decisión…" : label}
    </Button>
  );
}

export function ReviewForm({ id, proposedHours }: { id: string; proposedHours: number | null }) {
  const [state, action] = useActionState<FormState, FormData>(submitReview, { error: null });
  const [decision, setDecision] = useState<HumanAction>("approve");

  return (
    <Card title="Tu decisión">
      <form action={action}>
        <input type="hidden" name="id" value={id} />
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          {state.error && <Alert type="error" showIcon message={state.error} />}

          <Radio.Group
            name="action"
            value={decision}
            onChange={(event) => setDecision(event.target.value)}
            optionType="button"
            buttonStyle="solid"
            options={[
              { value: "approve", label: "Aprobar" },
              { value: "adjust", label: "Ajustar" },
              { value: "reject", label: "Rechazar" },
            ]}
          />

          {decision === "adjust" && (
            <Form.Item
              label="Total de horas"
              layout="vertical"
              extra="Sólo cambia el total. El desglose por componente se conserva tal cual lo produjo el sistema: revisar la cifra global no dice con qué componente no estás de acuerdo."
              style={{ marginBottom: 0 }}
            >
              <InputNumber
                name="adjusted_hours"
                min={0}
                step={1}
                defaultValue={proposedHours ?? undefined}
                style={{ width: 200 }}
              />
            </Form.Item>
          )}

          <Form.Item label="Revisor" layout="vertical" style={{ marginBottom: 0 }}>
            <Input name="reviewer_id" placeholder="tu.nombre@empresa.com" style={{ maxWidth: 360 }} />
          </Form.Item>

          <Form.Item label="Motivo" layout="vertical" style={{ marginBottom: 0 }}>
            <Input.TextArea name="comment" rows={3} placeholder="Por qué, para el registro." />
          </Form.Item>

          <SubmitButton action={decision} />
        </Space>
      </form>
    </Card>
  );
}
