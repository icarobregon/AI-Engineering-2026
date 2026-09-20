"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";

import { startRun, type FormState } from "../actions";

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" loading={pending} size="large">
      {pending ? "Arrancando…" : "Estimar"}
    </Button>
  );
}

export function TranscriptForm() {
  const [state, action] = useActionState<FormState, FormData>(startRun, { error: null });

  return (
    <Card>
      <form action={action}>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          {state.error && <Alert type="error" showIcon message={state.error} />}

          <Form.Item
            label="Transcripción de la reunión"
            layout="vertical"
            extra="El supervisor decide en ejecución qué agente actúa; sólo se detiene si la estimación no es fiable."
            style={{ marginBottom: 0 }}
          >
            <Input.TextArea
              name="transcript"
              rows={14}
              required
              minLength={100}
              placeholder="Pega aquí la transcripción completa…"
            />
          </Form.Item>

          <Space align="center" size="middle">
            <SubmitButton />
            <Typography.Text type="secondary">
              Arranca y te lleva a la pantalla de la ejecución. Tarda minutos, pero puedes
              cerrar la pestaña: el progreso se guarda en cada paso.
            </Typography.Text>
          </Space>
        </Space>
      </form>
    </Card>
  );
}
