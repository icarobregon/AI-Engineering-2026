"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Flex, Input, Space, Typography } from "antd";

import type { WorkModule } from "@/lib/estimator/contracts";
import { saveReview, type FormState } from "../actions";

type Tarea = { key: string; name: string; description: string };
type Modulo = { key: string; name: string; description: string; tasks: Tarea[] };

let contador = 0;
const nuevaClave = () => `n${(contador += 1)}`;

function aEstado(modules: WorkModule[]): Modulo[] {
  return modules.map((m) => ({
    key: nuevaClave(),
    name: m.name,
    description: m.description ?? "",
    tasks: m.tasks.map((t) => ({
      key: nuevaClave(),
      name: t.name,
      description: t.description ?? "",
    })),
  }));
}

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" loading={pending} size="large">
      {pending ? "Guardando…" : "Guardar árbol"}
    </Button>
  );
}

/**
 * Paso 3 — el árbol que propuso el modelo, corregido por una persona.
 *
 * Los campos viajan como `modules[i][tasks][j][name]`, y los índices son los de
 * POSICIÓN en el envío, no ids: eso es lo que permite luego emparejar las horas
 * por orden en vez de por nombre.
 */
export function ReviewForm({ runId, modules }: { runId: string; modules: WorkModule[] }) {
  const [state, action] = useActionState<FormState, FormData>(saveReview, {
    error: null,
    notice: null,
  });
  const [arbol, setArbol] = useState<Modulo[]>(() => aEstado(modules));

  const editarModulo = (key: string, campo: "name" | "description", valor: string) =>
    setArbol((prev) => prev.map((m) => (m.key === key ? { ...m, [campo]: valor } : m)));

  const editarTarea = (mk: string, tk: string, campo: "name" | "description", valor: string) =>
    setArbol((prev) =>
      prev.map((m) =>
        m.key === mk
          ? { ...m, tasks: m.tasks.map((t) => (t.key === tk ? { ...t, [campo]: valor } : t)) }
          : m,
      ),
    );

  return (
    <Card title="Paso 3 · Revisa el árbol antes de pedir horas">
      <form action={action}>
        <input type="hidden" name="run_id" value={runId} />
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          {state.error && <Alert type="error" showIcon message={state.error} />}
          {state.notice && <Alert type="success" showIcon message={state.notice} />}

          <Typography.Text type="secondary">
            Lo que dejes aquí es lo que se manda a buscar horas. Una fila sin nombre se descarta, y
            se te dice cuántas.
          </Typography.Text>

          {arbol.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Sin módulos. Añade el primero."
            />
          ) : (
            arbol.map((modulo, i) => (
              <Card
                key={modulo.key}
                size="small"
                title={
                  <Input
                    name={`modules[${i}][name]`}
                    value={modulo.name}
                    placeholder="Nombre del módulo"
                    onChange={(e) => editarModulo(modulo.key, "name", e.target.value)}
                    variant="borderless"
                    style={{ fontWeight: 600 }}
                  />
                }
                extra={
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => setArbol((prev) => prev.filter((m) => m.key !== modulo.key))}
                  >
                    Quitar
                  </Button>
                }
              >
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                  <Input
                    name={`modules[${i}][description]`}
                    value={modulo.description}
                    placeholder="Qué cubre este módulo (opcional)"
                    onChange={(e) => editarModulo(modulo.key, "description", e.target.value)}
                  />

                  {modulo.tasks.map((tarea, j) => (
                    <Flex key={tarea.key} gap={8} align="center">
                      <Input
                        name={`modules[${i}][tasks][${j}][name]`}
                        value={tarea.name}
                        placeholder="Tarea"
                        onChange={(e) => editarTarea(modulo.key, tarea.key, "name", e.target.value)}
                        style={{ flex: "0 0 32%" }}
                      />
                      <Input
                        name={`modules[${i}][tasks][${j}][description]`}
                        value={tarea.description}
                        placeholder="Alcance de la tarea (opcional)"
                        onChange={(e) =>
                          editarTarea(modulo.key, tarea.key, "description", e.target.value)
                        }
                      />
                      <Button
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() =>
                          setArbol((prev) =>
                            prev.map((m) =>
                              m.key === modulo.key
                                ? { ...m, tasks: m.tasks.filter((t) => t.key !== tarea.key) }
                                : m,
                            ),
                          )
                        }
                      />
                    </Flex>
                  ))}

                  <Button
                    type="dashed"
                    icon={<PlusOutlined />}
                    onClick={() =>
                      setArbol((prev) =>
                        prev.map((m) =>
                          m.key === modulo.key
                            ? {
                                ...m,
                                tasks: [
                                  ...m.tasks,
                                  { key: nuevaClave(), name: "", description: "" },
                                ],
                              }
                            : m,
                        ),
                      )
                    }
                  >
                    Añadir tarea
                  </Button>
                </Space>
              </Card>
            ))
          )}

          <Space size="large">
            <SubmitButton />
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={() =>
                setArbol((prev) => [
                  ...prev,
                  { key: nuevaClave(), name: "", description: "", tasks: [] },
                ])
              }
            >
              Añadir módulo
            </Button>
          </Space>
        </Space>
      </form>
    </Card>
  );
}
