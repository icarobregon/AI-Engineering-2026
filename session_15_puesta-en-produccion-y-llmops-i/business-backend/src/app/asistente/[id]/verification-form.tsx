"use client";

import { useActionState, useMemo, useState } from "react";
import { useFormStatus } from "react-dom";
import { Alert, Button, Card, Empty, InputNumber, Space, Statistic, Table, Tag, Typography } from "antd";

import { eur, hours as horasFmt } from "@/lib/format";
import {
  DEFAULT_RATE_EUR,
  RELIABILITY_OK,
  type TaskHoursResult,
  type WorkModule,
} from "@/lib/estimator/contracts";
import { confirmEstimate, type FormState } from "../actions";

type Verification = {
  lines: {
    module: string;
    task: string;
    hours: number;
    rate: number;
    cost: number;
    reliability: number | null;
    hadMatch: boolean;
  }[];
  totalHours: number;
  totalCostEur: number;
};

type Linea = {
  clave: string;
  indice: number;
  modulo: string;
  tarea: string;
  horas: number;
  tarifa: number;
  fiabilidad: number | null;
  conAnalogia: boolean;
};

function SubmitButton({ confirmada }: { confirmada: boolean }) {
  const { pending } = useFormStatus();
  return (
    <Button type="primary" htmlType="submit" size="large" loading={pending}>
      {pending ? "Confirmando…" : confirmada ? "Volver a confirmar" : "Confirmar estimación"}
    </Button>
  );
}

/**
 * Paso 5 — horas y tarifas, revisadas por una persona, y el total.
 *
 * El total que se ve aquí es COSMÉTICO: el servidor lo recalcula línea a línea
 * al confirmar. Si sólo se enviara el número de pantalla, cualquiera podría
 * mandar el que quisiera.
 */
export function VerificationForm({
  runId,
  modules,
  taskHours,
  verification,
}: {
  runId: string;
  modules: WorkModule[];
  taskHours: TaskHoursResult | null;
  verification: Verification | null;
}) {
  const [state, action] = useActionState<FormState, FormData>(confirmEstimate, {
    error: null,
    notice: null,
  });

  const iniciales = useMemo<Linea[]>(() => {
    const filas: Linea[] = [];
    let indice = 0;
    for (const modulo of modules) {
      for (const tarea of modulo.tasks) {
        const estimada = taskHours?.tasks[indice];
        const confirmada = verification?.lines[indice];
        filas.push({
          clave: `t${indice}`,
          indice,
          modulo: modulo.name,
          tarea: tarea.name,
          horas: confirmada?.hours ?? estimada?.estimated_hours ?? 0,
          // Una fila nueva sin tarifa vale 0 € sin avisar. El default evita eso.
          tarifa: confirmada?.rate ?? DEFAULT_RATE_EUR,
          fiabilidad: estimada?.reliability ?? confirmada?.reliability ?? null,
          conAnalogia: estimada?.has_match ?? confirmada?.hadMatch ?? false,
        });
        indice += 1;
      }
    }
    return filas;
  }, [modules, taskHours, verification]);

  const [lineas, setLineas] = useState<Linea[]>(iniciales);

  const totalHoras = lineas.reduce((n, l) => n + (l.horas || 0), 0);
  const totalCoste = lineas.reduce((n, l) => n + (l.horas || 0) * (l.tarifa || 0), 0);
  const sinHoras = lineas.filter((l) => !l.horas).length;

  const editar = (clave: string, campo: "horas" | "tarifa", valor: number | null) =>
    setLineas((prev) =>
      prev.map((l) => (l.clave === clave ? { ...l, [campo]: valor ?? 0 } : l)),
    );

  if (lineas.length === 0) {
    return (
      <Card title="Paso 5 · Verificación">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="Todavía no hay tareas que verificar. Revisa el árbol y calcula las horas."
        />
      </Card>
    );
  }

  return (
    <Card title="Paso 5 · Ajusta horas y tarifas, y confirma">
      <form action={action}>
        <input type="hidden" name="run_id" value={runId} />
        {/* El árbol viaja otra vez para que el servidor sepa a qué tarea
            pertenece cada línea sin fiarse del orden del navegador. */}
        {modules.map((m, i) => (
          <div key={`${m.name}-${i}`}>
            <input type="hidden" name={`modules[${i}][name]`} value={m.name} />
            {m.tasks.map((t, j) => (
              <input
                key={`${t.name}-${j}`}
                type="hidden"
                name={`modules[${i}][tasks][${j}][name]`}
                value={t.name}
              />
            ))}
          </div>
        ))}

        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          {state.error && <Alert type="error" showIcon message={state.error} />}
          {state.notice && <Alert type="success" showIcon message={state.notice} />}

          {sinHoras > 0 && (
            <Alert
              type="warning"
              showIcon
              message={`${sinHoras} tareas siguen a cero horas`}
              description="El corpus no encontró analogía para ellas. Se pueden confirmar así, pero no aportarán nada al total."
            />
          )}

          <Table
            rowKey="clave"
            dataSource={lineas}
            pagination={false}
            size="small"
            columns={[
              { title: "Módulo", dataIndex: "modulo", width: 180 },
              { title: "Tarea", dataIndex: "tarea" },
              {
                title: "Origen",
                key: "origen",
                width: 140,
                render: (_, l: Linea) =>
                  !l.conAnalogia ? (
                    <Tag color="error">sin analogía</Tag>
                  ) : (l.fiabilidad ?? 0) >= RELIABILITY_OK ? (
                    <Tag color="success">{Math.round((l.fiabilidad ?? 0) * 100)} %</Tag>
                  ) : (
                    <Tag color="warning">{Math.round((l.fiabilidad ?? 0) * 100)} %</Tag>
                  ),
              },
              {
                title: "Horas",
                key: "horas",
                align: "right",
                width: 110,
                render: (_, l: Linea) => (
                  <>
                    <input type="hidden" name={`hours[${l.clave}]`} value={l.horas} />
                    <InputNumber
                      min={0}
                      value={l.horas}
                      onChange={(v) => editar(l.clave, "horas", v)}
                      style={{ width: 90 }}
                    />
                  </>
                ),
              },
              {
                title: "€/h",
                key: "tarifa",
                align: "right",
                width: 110,
                render: (_, l: Linea) => (
                  <>
                    <input type="hidden" name={`rate[${l.clave}]`} value={l.tarifa} />
                    <InputNumber
                      min={0}
                      value={l.tarifa}
                      onChange={(v) => editar(l.clave, "tarifa", v)}
                      style={{ width: 90 }}
                    />
                  </>
                ),
              },
              {
                title: "Coste",
                key: "coste",
                align: "right",
                width: 120,
                render: (_, l: Linea) => eur((l.horas || 0) * (l.tarifa || 0)),
              },
            ]}
          />

          <Space size="large" wrap>
            <Statistic title="Horas" value={horasFmt(totalHoras)} />
            <Statistic title="Coste" value={eur(totalCoste)} />
            <SubmitButton confirmada={verification != null} />
          </Space>

          <Typography.Text type="secondary">
            Estos totales son informativos: al confirmar, el servidor los recalcula tarea a tarea.
            No hay tarifa global — cada línea lleva la suya.
          </Typography.Text>
        </Space>
      </form>
    </Card>
  );
}
