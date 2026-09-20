"use client";

import Link from "next/link";
import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { ArrowLeftOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Flex,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Typography,
} from "antd";

import { usdPerMillion } from "@/lib/format";
import { reasoningEfforts, type ModelsConfig } from "@/lib/estimator/contracts";
import { saveProfile, type FormState } from "../actions";

type Profile = {
  id: string;
  name: string;
  description: string | null;
  model: string | null;
  reasoningEffort: string | null;
  maxIterations: number | null;
  isDefault: boolean;
};

/** Una opción del desplegable de modelos, con su precio a la derecha. */
function opcionModelo(
  value: string,
  texto: string,
  precios: ModelsConfig["model_prices"],
) {
  const precio = precios[value];
  return {
    value,
    label: (
      <Flex justify="space-between" align="center" gap={12}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{texto}</span>
        {precio && (
          <Typography.Text type="secondary" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
            {usdPerMillion(precio.input, precio.output)}
          </Typography.Text>
        )}
      </Flex>
    ),
  };
}

function SubmitButton({ editando }: { editando: boolean }) {
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" size="large" loading={pending}>
      {pending ? "Guardando…" : editando ? "Guardar cambios" : "Crear perfil"}
    </Button>
  );
}

/**
 * Alta y edición de un perfil.
 *
 * Los tres ajustes son OPCIONALES a propósito. Dejar uno en blanco no es lo
 * mismo que copiar aquí el valor por defecto del servicio: copiarlo lo
 * congelaría, y el día que cambie el `.env` este perfil seguiría empujando el
 * valor viejo sin que nadie lo note.
 */
export function ProfileForm({
  availableModels,
  modelPrices,
  profile,
}: {
  availableModels: string[];
  modelPrices: ModelsConfig["model_prices"];
  profile: Profile | null;
}) {
  const [state, action] = useActionState<FormState, FormData>(saveProfile, {
    error: null,
    notice: null,
  });
  const [model, setModel] = useState<string>(profile?.model ?? "");
  const [effort, setEffort] = useState<string>(profile?.reasoningEffort ?? "");
  const [iterations, setIterations] = useState<number | null>(profile?.maxIterations ?? null);

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="center">
        <Typography.Title level={3} style={{ margin: 0 }}>
          {profile ? "Editar perfil" : "Nuevo perfil"}
        </Typography.Title>
        <Link href="/agentes">
          <Button variant="outlined" icon={<ArrowLeftOutlined />}>
            Consola
          </Button>
        </Link>
      </Flex>

      <form action={action}>
        {profile && <input type="hidden" name="id" value={profile.id} />}
        {/* AntD no llega al FormData: los ocultos son el puente, igual que en
            el resto de la aplicación. */}
        <input type="hidden" name="model" value={model} />
        <input type="hidden" name="reasoning_effort" value={effort} />
        <input type="hidden" name="max_iterations" value={iterations ?? ""} />

        <Card>
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            {state.error && <Alert type="error" showIcon message={state.error} />}

            <Form.Item label="Nombre" layout="vertical" style={{ marginBottom: 0 }}>
              <Input
                name="name"
                required
                defaultValue={profile?.name}
                placeholder="Veloz (depuración)"
                style={{ maxWidth: 380 }}
              />
            </Form.Item>

            <Form.Item
              label="Descripción"
              layout="vertical"
              extra="Para qué sirve este perfil. Lo lee quien tenga que elegir entre varios."
              style={{ marginBottom: 0 }}
            >
              <Input
                name="description"
                defaultValue={profile?.description ?? ""}
                placeholder="Modelo pequeño y pocas vueltas, para iterar sobre el prompt sin gastar."
              />
            </Form.Item>

            <Typography.Text type="secondary">
              Los tres ajustes son opcionales. Lo que dejes en blanco lo resuelve el{" "}
              <Typography.Text code>.env</Typography.Text> del servicio en cada ejecución, que no
              es lo mismo que copiar aquí su valor de hoy: copiarlo lo congelaría.
            </Typography.Text>

            <Space size="large" wrap align="start">
              <Form.Item label="Modelo" layout="vertical" style={{ marginBottom: 0 }}>
                <Select
                  value={model}
                  onChange={setModel}
                  style={{ width: 360 }}
                  showSearch
                  // Mismo formato que el desplegable de Ajustes: el precio al
                  // lado del nombre. Elegir el modelo de un perfil es decidir lo
                  // que va a costar cada ejecución que lo use, y el catálogo va
                  // de 0,05 a 600 US$ por millón.
                  options={[
                    opcionModelo("", "Por defecto del servicio", modelPrices),
                    ...availableModels.map((m) => opcionModelo(m, m, modelPrices)),
                  ]}
                />
              </Form.Item>

              <Form.Item
                label="Esfuerzo de razonamiento"
                layout="vertical"
                style={{ marginBottom: 0 }}
              >
                <Select
                  value={effort}
                  onChange={setEffort}
                  style={{ width: 200 }}
                  options={[
                    { value: "", label: "Por defecto del servicio" },
                    ...reasoningEfforts.map((e) => ({ value: e, label: e })),
                  ]}
                />
              </Form.Item>

              <Form.Item
                label="Máximo de iteraciones"
                layout="vertical"
                extra="El corte natural es una vuelta sin llamada a herramienta."
                style={{ marginBottom: 0 }}
              >
                <InputNumber
                  min={1}
                  max={30}
                  value={iterations}
                  onChange={setIterations}
                  placeholder="del servicio"
                  style={{ width: 180 }}
                />
              </Form.Item>
            </Space>

            <Checkbox name="is_default" defaultChecked={profile?.isDefault}>
              Perfil por defecto — se preselecciona al lanzar
            </Checkbox>

            <Space size="large">
              <SubmitButton editando={profile != null} />
              <Link href="/agentes">
                <Button type="link">Cancelar</Button>
              </Link>
            </Space>
          </Space>
        </Card>
      </form>
    </Flex>
  );
}
