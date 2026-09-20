"use client";

import { Alert, List, Space, Table, Tag, Typography } from "antd";

import {
  deniedActions,
  hopSource,
  type GraphState,
  type HopSource,
} from "@/lib/estimator/contracts";
import { CollapseCard } from "@/components/collapse-card";

const sourceTag: Record<HopSource, { color: string; title: string }> = {
  regla: {
    color: "blue",
    title: "Precondición resuelta por código, sin llamar al modelo.",
  },
  modelo: {
    color: "purple",
    title: "La única pregunta que el supervisor delega en el modelo.",
  },
  limite: {
    color: "red",
    title: "Se agotó el presupuesto de pasos. Freno de emergencia.",
  },
};

/**
 * The routing trail is where the shape of a supervised run exists: in Session 13
 * the order lived in the edges, written once for every transcript. Here it is
 * decided one hop at a time and only exists afterwards.
 */
export function RoutingTrace({ state }: { state: GraphState }) {
  const trail = state.values.routing_trail;
  const denied = deniedActions(state.values.errors);

  if (trail.length === 0) {
    return null;
  }

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <CollapseCard
        title="Enrutado del supervisor"
        extra={
          state.values.routing_steps != null && (
            <Typography.Text type="secondary">
              {state.values.routing_steps} pasos
            </Typography.Text>
          )
        }
        styles={{ body: { padding: 0 } }}
      >
        <div style={{ padding: "12px 16px 0" }}>
          <Typography.Text type="secondary">
            Quién decidió cada salto: <Tag color="blue">regla</Tag> una
            precondición, resuelta en código · <Tag color="purple">modelo</Tag>{" "}
            la única pregunta que este dominio delega ·{" "}
            <Tag color="red">límite</Tag> se agotó el presupuesto de pasos.
          </Typography.Text>
        </div>
        <Table
          rowKey={(_, index) => String(index)}
          dataSource={trail}
          pagination={false}
          columns={[
            {
              title: "#",
              key: "step",
              width: 50,
              // The trail is append-only, so its order IS the step number. The
              // AI service does not send one.
              render: (_, __, index) => index + 1,
            },
            {
              title: "Agente",
              dataIndex: "next_agent",
              width: 220,
              render: (value: string) => (
                <Typography.Text code>{value}</Typography.Text>
              ),
            },
            {
              title: "Origen",
              key: "source",
              width: 110,
              render: (_, hop) => {
                const source = hopSource(hop.reason);
                return (
                  <Tag
                    color={sourceTag[source].color}
                    title={sourceTag[source].title}
                  >
                    {source === "limite" ? "límite" : source}
                  </Tag>
                );
              },
            },
            { title: "Motivo", dataIndex: "reason" },
          ]}
        />
      </CollapseCard>

      {denied.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message="La guarda de privilegios denegó alguna acción"
          description={
            <>
              <List
                size="small"
                dataSource={denied}
                renderItem={(item) => <List.Item>{item}</List.Item>}
              />
              <Typography.Text type="secondary">
                El servicio IA no expone una auditoría estructurada: registra
                las acciones en sus logs y sólo el texto de la denegación llega
                hasta aquí.
              </Typography.Text>
            </>
          }
        />
      )}
    </Space>
  );
}
