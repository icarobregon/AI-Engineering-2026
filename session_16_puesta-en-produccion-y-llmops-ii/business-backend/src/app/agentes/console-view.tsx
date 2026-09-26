"use client";

import Link from "next/link";
import { useActionState, useRef, useState } from "react";
import { useFormStatus } from "react-dom";
import {
  Alert,
  Button,
  Card,
  Empty,
  Flex,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";

import { hours as horasFmt } from "@/lib/format";
import { deleteProfile, startAgentRun, type FormState } from "./actions";
import { statusTag } from "./pieces";

type Profile = {
  id: string;
  name: string;
  description: string | null;
  model: string | null;
  reasoningEffort: string | null;
  maxIterations: number | null;
  isDefault: boolean;
};

type Run = {
  id: string;
  status: string;
  model: string;
  reasoningEffort: string;
  profileName: string | null;
  totalHours: number | null;
  createdAt: string;
};

const MIN = 100;

/**
 * Qué ajustes empuja un perfil, dicho dentro de su propia opción.
 *
 * Elegir un perfil ES elegir un modelo y un esfuerzo, así que tenerlos que
 * buscar en la tabla de abajo para saber qué vas a lanzar es una vuelta de más.
 * Mismo formato que el precio en el desplegable de Ajustes: el nombre a la
 * izquierda y el dato secundario a la derecha, sin romper línea.
 */
function opcionPerfil(
  value: string,
  nombre: string,
  perfil: Pick<Profile, "model" | "reasoningEffort" | "isDefault"> | null,
) {
  const ajustes = perfil ? [perfil.model, perfil.reasoningEffort].filter(Boolean).join(" · ") : "";
  return {
    value,
    label: (
      <Flex justify="space-between" align="center" gap={12}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
          {nombre}
          {perfil?.isDefault && <Typography.Text type="secondary"> · por defecto</Typography.Text>}
        </span>
        <Typography.Text type="secondary" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
          {/* Un perfil sin ajustes y «sin perfil» acaban en el mismo sitio —todo
              lo resuelve el servicio—, así que dicen lo mismo. */}
          {ajustes || "todo del servicio"}
        </Typography.Text>
      </Flex>
    ),
  };
}

/**
 * Borrar un perfil, tras confirmar.
 *
 * La referencia al formulario es imprescindible y no un adorno: el botón de
 * confirmación del Popconfirm se renderiza en un PORTAL, fuera del `<form>`, así
 * que buscar el formulario desde el evento —`closest("form")`— devuelve null y el
 * borrado no llega a lanzarse nunca, sin error en consola.
 */
function DeleteProfileButton({ id }: { id: string }) {
  const formRef = useRef<HTMLFormElement>(null);
  return (
    <form action={deleteProfile} ref={formRef}>
      <input type="hidden" name="id" value={id} />
      <Popconfirm
        title="Borrar el perfil"
        description="Las ejecuciones que ya corrieron con él se conservan: cada una guardó sus ajustes."
        okText="Borrar"
        cancelText="Cancelar"
        onConfirm={() => formRef.current?.requestSubmit()}
      >
        <Button danger size="small" htmlType="button">
          Borrar
        </Button>
      </Popconfirm>
    </form>
  );
}

function LaunchButton({ suficiente }: { suficiente: boolean }) {
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" size="large" loading={pending} disabled={!suficiente}>
      {pending ? "Lanzando…" : "Lanzar agente"}
    </Button>
  );
}

export function ConsoleView({
  availableModels,
  modelsError,
  profiles,
  runs,
}: {
  availableModels: string[];
  modelsError: string | null;
  profiles: Profile[];
  runs: Run[];
}) {
  const [state, action] = useActionState<FormState, FormData>(startAgentRun, {
    error: null,
    notice: null,
  });
  const porDefecto = profiles.find((p) => p.isDefault);
  const [perfil, setPerfil] = useState<string>(porDefecto?.id ?? "");
  const [largo, setLargo] = useState(0);

  return (
    <Flex vertical gap={24}>
      <Space direction="vertical" size={4}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Consola de agentes
        </Typography.Title>
        <Typography.Text type="secondary">
          Perfiles con nombre para el agente escrito a mano de la S12. Un perfil elige modelo,
          esfuerzo de razonamiento y techo de iteraciones, y <strong>gobierna de verdad</strong> la
          ejecución: lo que deja en blanco lo resuelve el <code>.env</code> del servicio.
        </Typography.Text>
      </Space>

      {modelsError && <Alert type="warning" showIcon message={modelsError} />}

      <Card title="Lanzar una ejecución">
        <form action={action}>
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            {state.error && <Alert type="error" showIcon message={state.error} />}

            <Form.Item label="Perfil" layout="vertical" style={{ marginBottom: 0 }}>
              <input type="hidden" name="profile_id" value={perfil} />
              <Select
                value={perfil}
                onChange={setPerfil}
                style={{ width: 460 }}
                options={[
                  opcionPerfil("", "Sin perfil", null),
                  ...profiles.map((p) => opcionPerfil(p.id, p.name, p)),
                ]}
              />
            </Form.Item>

            <Form.Item
              label="Transcripción"
              layout="vertical"
              extra={
                largo >= MIN
                  ? `${largo.toLocaleString("es-ES")} caracteres.`
                  : `${largo} de ${MIN} caracteres mínimos.`
              }
              style={{ marginBottom: 0 }}
            >
              <Input.TextArea
                name="transcript"
                rows={8}
                required
                onChange={(e) => setLargo(e.target.value.trim().length)}
                placeholder="Pega la transcripción de la reunión…"
              />
            </Form.Item>

            <Space size="large">
              <LaunchButton suficiente={largo >= MIN} />
              <Typography.Text type="secondary">
                El bucle encadena varias llamadas a un modelo de razonamiento: tarda minutos. Corre
                en segundo plano y la página del detalle se actualiza sola.
              </Typography.Text>
            </Space>
          </Space>
        </form>
      </Card>

      <Card
        title="Perfiles"
        extra={
          <Link href="/agentes/perfiles/nuevo">
            <Button type="primary">Nuevo perfil</Button>
          </Link>
        }
        styles={{ body: { padding: 0 } }}
      >
        {profiles.length === 0 ? (
          <div style={{ padding: 24 }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Sin perfiles. Sin ninguno, el agente corre con los valores del servicio."
            />
          </div>
        ) : (
          <Table
            rowKey="id"
            dataSource={profiles}
            pagination={false}
            size="small"
            columns={[
              {
                title: "Perfil",
                key: "name",
                render: (_, p: Profile) => (
                  <Space direction="vertical" size={0}>
                    <Space size={8}>
                      <Typography.Text strong>{p.name}</Typography.Text>
                      {p.isDefault && <Tag color="gold">por defecto</Tag>}
                    </Space>
                    {p.description && (
                      <Typography.Text type="secondary">{p.description}</Typography.Text>
                    )}
                  </Space>
                ),
              },
              {
                title: "Modelo",
                dataIndex: "model",
                width: 200,
                render: (v: string | null) =>
                  v ? (
                    <Typography.Text code>{v}</Typography.Text>
                  ) : (
                    <Typography.Text type="secondary">del servicio</Typography.Text>
                  ),
              },
              {
                title: "Esfuerzo",
                dataIndex: "reasoningEffort",
                width: 120,
                render: (v: string | null) =>
                  v ? <Tag>{v}</Tag> : <Typography.Text type="secondary">—</Typography.Text>,
              },
              {
                title: "Iteraciones",
                dataIndex: "maxIterations",
                align: "right",
                width: 110,
                render: (v: number | null) =>
                  v ?? <Typography.Text type="secondary">—</Typography.Text>,
              },
              {
                key: "acciones",
                align: "right",
                width: 160,
                render: (_, p: Profile) => (
                  <Space>
                    <Link href={`/agentes/perfiles/${p.id}`}>
                      <Button variant="outlined" size="small">
                        Editar
                      </Button>
                    </Link>
                    <DeleteProfileButton id={p.id} />
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Card title="Ejecuciones recientes" styles={{ body: { padding: 0 } }}>
        {runs.length === 0 ? (
          <div style={{ padding: 24 }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Aún no hay ejecuciones." />
          </div>
        ) : (
          <Table
            rowKey="id"
            dataSource={runs}
            pagination={false}
            size="small"
            columns={[
              {
                title: "Lanzada",
                dataIndex: "createdAt",
                width: 160,
                render: (v: string) => new Date(v).toLocaleString("es-ES"),
              },
              {
                title: "Perfil",
                dataIndex: "profileName",
                render: (v: string | null) =>
                  v ?? <Typography.Text type="secondary">sin perfil</Typography.Text>,
              },
              {
                title: "Modelo",
                dataIndex: "model",
                width: 200,
                render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
              },
              { title: "Esfuerzo", dataIndex: "reasoningEffort", width: 130 },
              {
                title: "Horas",
                dataIndex: "totalHours",
                align: "right",
                width: 100,
                render: (v: number | null) => (v == null ? "—" : horasFmt(v)),
              },
              {
                title: "Estado",
                dataIndex: "status",
                width: 130,
                render: (v: string) => statusTag(v),
              },
              {
                key: "ver",
                align: "right",
                width: 90,
                render: (_, r: Run) => (
                  <Link href={`/agentes/ejecuciones/${r.id}`}>
                    <Button variant="outlined" size="small">
                      Ver
                    </Button>
                  </Link>
                ),
              },
            ]}
          />
        )}
      </Card>

      {availableModels.length > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          El desplegable de modelos de un perfil ofrece los {availableModels.length} del catálogo
          del servicio IA, el mismo que usa la pantalla de Ajustes.
        </Typography.Text>
      )}
    </Flex>
  );
}
