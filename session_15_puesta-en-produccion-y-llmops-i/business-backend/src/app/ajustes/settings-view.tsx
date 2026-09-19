"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { Alert, Button, Card, Flex, Select, Space, Table, Tag, Typography } from "antd";

import { modelKnobs, type ModelKnob, type ModelsConfig } from "@/lib/estimator/contracts";
import { saveModels, type FormState } from "./actions";

/** Hardcoded here, as in the reference app: the AI service ships keys, not prose. */
/** "OpenAI y Anthropic", no "OpenAI, Anthropic". */
const listFormatter = new Intl.ListFormat("es-ES", { style: "long", type: "conjunction" });

const knobLabels: Record<ModelKnob, { label: string; description: string }> = {
  PRIMARY_MODEL: { label: "Modelo principal", description: "El que atiende las estimaciones." },
  FALLBACK_MODEL: {
    label: "Modelo de respaldo",
    description: "Entra cuando el proveedor principal falla, sólo en las llamadas no estructuradas.",
  },
  CRITIC_MODEL: { label: "Crítico", description: "Revisa el borrador en el modo Actor-Critic-Boss." },
  METADATA_EXTRACTOR_MODEL: {
    label: "Extractor de metadata",
    description: "Saca nombre de proyecto, equipo y tecnologías de la conversación.",
  },
  COMPRESSION_MODEL: {
    label: "Compresión",
    description: "Resume los turnos antiguos cuando la conversación no cabe en la ventana.",
  },
  PROPOSITIONAL_CHUNKER_MODEL: {
    label: "Chunker proposicional",
    description: "Trocea por proposiciones en el laboratorio de chunking. Llama al modelo por componente.",
  },
  CONTEXTUAL_CHUNKER_MODEL: {
    label: "Chunker contextual",
    description: "Añade contexto a cada fragmento. Es la estrategia más cara del laboratorio.",
  },
};

/**
 * antd renders a div, not a native <select>, so the hidden input is what makes
 * the value reach FormData. Same bridge as the estimation form.
 */
function KnobSelect({
  knob,
  state,
  options,
}: {
  knob: ModelKnob;
  state: { effective: string; default: string; overridden: boolean };
  options: string[];
}) {
  // "" means "no override". The reference app preselects it whenever the knob is
  // not overridden, so what you see selected is the decision, not the outcome.
  const [value, setValue] = useState(state.overridden ? state.effective : "");
  return (
    <>
      <input type="hidden" name={knob} value={value} />
      <Select
        value={value}
        onChange={setValue}
        style={{ width: 260 }}
        options={[
          { value: "", label: `Por defecto (${state.default})` },
          ...options.map((m) => ({ value: m, label: m })),
        ]}
      />
    </>
  );
}

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" loading={pending} size="large">
      {pending ? "Guardando…" : "Guardar"}
    </Button>
  );
}

export function SettingsView({ config }: { config: ModelsConfig }) {
  const [state, action] = useActionState<FormState, FormData>(saveModels, {
    error: null,
    saved: false,
  });

  const rows = modelKnobs
    .filter((knob) => config.models[knob])
    .map((knob) => ({ key: knob, knob, state: config.models[knob]! }));

  return (
    <Flex vertical gap={24}>
      <Space direction="vertical" size={4}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Ajustes del servicio IA
        </Typography.Title>
        <Typography.Text type="secondary">
          El cambio es en caliente: se guarda como override y lo coge la siguiente llamada, sin
          tocar el <Typography.Text code>.env</Typography.Text> ni recrear contenedores. «Por
          defecto» restaura el valor del fichero.
        </Typography.Text>
      </Space>

      <form action={action}>
        <Flex vertical gap={16}>
          {state.error && <Alert type="error" showIcon message={state.error} />}
          {state.saved && !state.error && (
            <Alert type="success" showIcon message="Configuración guardada." />
          )}

          <Card styles={{ body: { padding: 0 } }}>
            <Table
              rowKey="key"
              dataSource={rows}
              pagination={false}
              columns={[
                {
                  title: "Ajuste",
                  key: "knob",
                  render: (_, row) => (
                    <Space direction="vertical" size={0}>
                      <Typography.Text strong>{knobLabels[row.knob].label}</Typography.Text>
                      <Typography.Text type="secondary">
                        {knobLabels[row.knob].description}
                      </Typography.Text>
                      <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
                        {row.knob}
                      </Typography.Text>
                    </Space>
                  ),
                },
                {
                  title: "Modelo",
                  key: "model",
                  width: 290,
                  render: (_, row) => (
                    <KnobSelect
                      // Keyed by what the server says: React keeps component
                      // state across re-renders, so without this the select
                      // would still read "por defecto" after a save while the
                      // Estado column already showed the override.
                      key={`${row.knob}:${row.state.effective}:${row.state.overridden}`}
                      knob={row.knob}
                      state={row.state}
                      options={config.available_models}
                    />
                  ),
                },
                {
                  title: "Estado",
                  key: "status",
                  width: 210,
                  render: (_, row) =>
                    row.state.overridden ? (
                      <Space direction="vertical" size={2}>
                        <Tag color="purple">override</Tag>
                        <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
                          activo: {row.state.effective}
                        </Typography.Text>
                      </Space>
                    ) : (
                      <Tag>por defecto</Tag>
                    ),
                },
              ]}
              summary={() => (
                <Table.Summary.Row style={{ background: "#fafafa" }}>
                  <Table.Summary.Cell index={0}>
                    <Space direction="vertical" size={0}>
                      <Typography.Text strong>Modelo de embeddings</Typography.Text>
                      <Typography.Text type="secondary">
                        Fuera de los ajustes a propósito: cambiarlo invalidaría todos
                        los vectores ya almacenados.
                      </Typography.Text>
                      <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
                        EMBEDDING_MODEL
                      </Typography.Text>
                    </Space>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={1}>
                    <Typography.Text code>{config.embedding_model}</Typography.Text>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={2}>
                    <Tag>sólo lectura</Tag>
                  </Table.Summary.Cell>
                </Table.Summary.Row>
              )}
            />
          </Card>

          <Space align="center" size="middle">
            <SubmitButton />
            <Typography.Text type="secondary">
              El catálogo sólo ofrece modelos cuyo proveedor tiene clave configurada.
            </Typography.Text>
          </Space>

          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Catálogo generado el{" "}
            <strong>{new Date(config.catalog_generated_at).toLocaleString("es-ES")}</strong> a
            partir de los modelos publicados por{" "}
            <strong>{listFormatter.format(config.catalog_sources)}</strong>. Se cura a mano: ni un
            proveedor nuevo ni un modelo nuevo aparecen aquí solos. Hay que pedir que se regenere.
          </Typography.Text>
        </Flex>
      </form>
    </Flex>
  );
}
