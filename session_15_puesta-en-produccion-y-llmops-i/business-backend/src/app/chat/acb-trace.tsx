"use client";

import { Alert, Card, Collapse, Space, Tag, Timeline, Typography } from "antd";

import { SYNTHESIS_PREFIX, type BossTrace } from "@/lib/estimator/contracts";

const verdictTag: Record<string, { color: string; label: string }> = {
  accept: { color: "green", label: "acepta" },
  needs_iteration: { color: "orange", label: "pide otra vuelta" },
  reject: { color: "red", label: "rechaza" },
};

const severityColor: Record<string, string> = {
  critical: "red",
  major: "orange",
  minor: "blue",
};

/** `"[critical] math_error @ total_cost_eur"` — the server pre-renders these. */
function Issue({ text }: { text: string }) {
  const match = /^\[(\w+)\]\s*(.*)$/.exec(text);
  if (!match) return <Typography.Text>{text}</Typography.Text>;
  return (
    <Space size={6}>
      <Tag color={severityColor[match[1]] ?? "default"}>{match[1]}</Tag>
      <Typography.Text code style={{ fontSize: 12 }}>
        {match[2]}
      </Typography.Text>
    </Space>
  );
}

export function AcbTrace({ trace, summary }: { trace: BossTrace; summary: string }) {
  const synthesised = summary.startsWith(SYNTHESIS_PREFIX);

  return (
    <Card
      title="Traza Actor-Critic-Boss"
      extra={
        <Space>
          <Typography.Text type="secondary">
            {trace.iterations_run} vuelta(s) · {trace.iterations_run * 2} llamadas
          </Typography.Text>
          <Tag color={trace.final_decision === "accept" ? "green" : "orange"}>
            {trace.final_decision === "accept" ? "aceptada" : "sintetizada"}
          </Tag>
        </Space>
      }
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        {synthesised && (
          <Alert
            type="warning"
            showIcon
            message="El bucle no convergió"
            description="El servicio reescribió el resumen anteponiendo las reservas que quedaron abiertas y lo recortó a 1.200 caracteres, así que el texto original del modelo puede haber desaparecido."
          />
        )}

        <Timeline
          items={trace.iterations.map((it) => {
            // Confidence zero is not a confident critic: it is the synthetic
            // feedback the service produces when the critic call itself failed.
            const criticFailed = it.critic_confidence === 0 && it.issue_summary.length === 0;
            const verdict = verdictTag[it.critic_verdict] ?? {
              color: "default",
              label: it.critic_verdict,
            };
            return {
              key: it.iteration,
              color: criticFailed ? "gray" : verdict.color,
              children: (
                <Space direction="vertical" size={6}>
                  <Space wrap size={8}>
                    <Typography.Text strong>Vuelta {it.iteration + 1}</Typography.Text>
                    <Tag color={verdict.color}>crítico: {verdict.label}</Tag>
                    {criticFailed ? (
                      <Tag color="default">el crítico no respondió</Tag>
                    ) : (
                      <Typography.Text type="secondary">
                        confianza en su revisión: {it.critic_confidence}%
                      </Typography.Text>
                    )}
                    <Tag>jefe: {it.decision_after}</Tag>
                  </Space>
                  {it.issue_summary.length > 0 && (
                    <Collapse
                      ghost
                      size="small"
                      items={[
                        {
                          key: "issues",
                          label: `${it.issue_summary.length} incidencia(s)`,
                          children: (
                            <Space direction="vertical" size={4}>
                              {it.issue_summary.map((text, i) => (
                                <Issue key={i} text={text} />
                              ))}
                            </Space>
                          ),
                        },
                      ]}
                    />
                  )}
                </Space>
              ),
            };
          })}
        />

        <Typography.Text type="secondary">
          Sólo viajan las cinco primeras incidencias de cada vuelta, y sin descripción: el detalle
          vive en los logs del servicio IA.
        </Typography.Text>
      </Space>
    </Card>
  );
}
