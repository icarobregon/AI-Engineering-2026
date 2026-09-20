"use client";

import Link from "next/link";
import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Flex, Form, Input, Space, Typography } from "antd";

import { createRun, type FormState } from "../actions";

const MIN = 100;

function SubmitButton({ suficiente }: { suficiente: boolean }) {
  const { pending } = useFormStatus();
  return (
    <Button
      type="primary"
      htmlType="submit"
      size="large"
      loading={pending}
      disabled={!suficiente}
    >
      {pending ? "Reformulando…" : "Empezar"}
    </Button>
  );
}

export function NewRunForm() {
  const [state, action] = useActionState<FormState, FormData>(createRun, {
    error: null,
    notice: null,
  });
  const [largo, setLargo] = useState(0);
  const suficiente = largo >= MIN;

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="center">
        <Typography.Title level={3} style={{ margin: 0 }}>
          Nueva estimación asistida
        </Typography.Title>
        <Link href="/asistente">
          <Button variant="outlined" icon={<ArrowLeftOutlined />}>
            Histórico
          </Button>
        </Link>
      </Flex>

      <form action={action}>
        <Card>
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            {state.error && <Alert type="error" showIcon message={state.error} />}

            <Typography.Text type="secondary">
              Pega la transcripción de la reunión de descubrimiento, tal cual. El primer paso la
              convierte en un brief tipado; no hace falta limpiarla antes.
            </Typography.Text>

            <Form.Item
              label="Transcripción"
              layout="vertical"
              // El servicio exige 100 caracteres. Decirlo aquí y contar en vivo
              // evita descubrirlo con un 422 después de pegar el texto.
              extra={
                suficiente
                  ? `${largo.toLocaleString("es-ES")} caracteres.`
                  : `${largo} de ${MIN} caracteres mínimos.`
              }
              style={{ marginBottom: 0 }}
            >
              <Input.TextArea
                name="transcript"
                rows={16}
                required
                onChange={(e) => setLargo(e.target.value.trim().length)}
                placeholder="— Necesitamos un portal para que los clientes reserven…"
              />
            </Form.Item>

            <Space size="large">
              <SubmitButton suficiente={suficiente} />
              <Typography.Text type="secondary">
                La transcripción no se puede editar después: cada ejecución es la suya.
              </Typography.Text>
            </Space>
          </Space>
        </Card>
      </form>
    </Flex>
  );
}
