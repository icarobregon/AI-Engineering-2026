"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { Alert, Button, Card, Divider, Empty, Space, Typography } from "antd";
import { DownloadOutlined, FileTextOutlined } from "@ant-design/icons";

import { parseSimpleMarkdown } from "@/lib/markdown";
import type { CommercialProposal } from "@/lib/estimator/contracts";
import { generateProposal, type FormState } from "../actions";

function BotonRedactar({ rehacer }: { rehacer: boolean }) {
  const { pending } = useFormStatus();
  return (
    <Button type={rehacer ? "default" : "primary"} htmlType="submit" loading={pending} icon={<FileTextOutlined />}>
      {pending ? "Redactando…" : rehacer ? "Volver a redactar" : "Redactar propuesta"}
    </Button>
  );
}

/**
 * El cuerpo de la propuesta, desde los MISMOS bloques que imprime el PDF.
 *
 * La aplicación de referencia guarda markdown, lo enseña crudo aquí y lo
 * interpreta allí con tres expresiones regulares. Son dos lecturas distintas del
 * mismo texto y divergen en cuanto el modelo escribe algo que una no contempla.
 */
function Cuerpo({ markdown }: { markdown: string }) {
  return (
    <>
      {parseSimpleMarkdown(markdown).map((bloque, indice) => {
        if (bloque.kind === "heading") {
          return (
            <Typography.Title key={indice} level={5} style={{ marginTop: 20 }}>
              {bloque.text}
            </Typography.Title>
          );
        }
        if (bloque.kind === "list") {
          return (
            <ul key={indice} style={{ paddingLeft: 20, marginBottom: 12 }}>
              {bloque.items.map((item, i) => (
                <li key={i}>
                  <Typography.Text>{item}</Typography.Text>
                </li>
              ))}
            </ul>
          );
        }
        return (
          <Typography.Paragraph key={indice} style={{ textAlign: "justify" }}>
            {bloque.text}
          </Typography.Paragraph>
        );
      })}
    </>
  );
}

function Puntos({ titulo, items }: { titulo: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      <Typography.Title level={5} style={{ marginTop: 20 }}>
        {titulo}
      </Typography.Title>
      <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
        {items.map((item, i) => (
          <li key={i}>
            <Typography.Text>{item}</Typography.Text>
          </li>
        ))}
      </ul>
    </>
  );
}

export function ProposalCard({
  id,
  proposal,
  canDraft,
}: {
  id: string;
  proposal: CommercialProposal | null;
  canDraft: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(generateProposal, { error: null });

  return (
    <Card
      title="Propuesta comercial"
      extra={
        proposal && (
          // Un enlace y no un fetch: el navegador ya sabe descargar, y el
          // documento se recompone en cada petición desde lo guardado.
          <Button href={`/supervisor/${id}/proposal.pdf`} icon={<DownloadOutlined />}>
            Descargar PDF
          </Button>
        )
      }
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        {state.error && <Alert type="error" showIcon message={state.error} />}

        {!canDraft && !proposal && (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="Todavía no hay una estimación cerrada sobre la que redactar."
          />
        )}

        {canDraft && !proposal && (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            El servicio redacta el documento a partir de la estimación ya validada, sin volver a
            ejecutar el grafo: las horas son las que hay y no se recalcula nada. Las cifras no se le
            piden al modelo, se le dan.
          </Typography.Paragraph>
        )}

        {proposal && (
          <div>
            <Typography.Title level={4} style={{ marginTop: 0 }}>
              {proposal.title}
            </Typography.Title>
            <Typography.Paragraph style={{ textAlign: "justify" }}>
              {proposal.executive_summary}
            </Typography.Paragraph>

            <Puntos titulo="Alcance" items={proposal.scope} />
            <Puntos titulo="Supuestos y reservas" items={proposal.assumptions} />

            <Divider />
            <Cuerpo markdown={proposal.body_markdown} />
          </div>
        )}

        {canDraft && (
          <form action={action}>
            <input type="hidden" name="id" value={id} />
            <BotonRedactar rehacer={proposal != null} />
          </form>
        )}
      </Space>
    </Card>
  );
}
