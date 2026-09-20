"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Flex, Progress, Row, Space, Statistic, Typography } from "antd";

import type { CorpusStats } from "@/lib/estimator/contracts";
import { pollIndexRun } from "../actions";
import { CorpusStatsTable, statusTag } from "../corpus-pieces";

type Run = {
  id: string;
  chunkType: string;
  submittedCount: number;
  processedCount: number;
  skippedCount: number;
  chunksCreated: number;
  status: string;
  errorMessage: string | null;
  createdAt: string;
};

const INTERVALO_MS = 1_500;
/** Techo de sondeos: 20 minutos. La referencia no tiene ninguno y golpea para siempre. */
const MAX_SONDEOS = (20 * 60_000) / INTERVALO_MS;

export function RunView({
  run,
  before,
  after,
}: {
  run: Run;
  before: CorpusStats | null;
  after: CorpusStats | null;
}) {
  const router = useRouter();
  const [vivo, setVivo] = useState({
    status: run.status,
    processed: run.processedCount,
    skipped: run.skippedCount,
    chunksCreated: run.chunksCreated,
    errorMessage: run.errorMessage,
    stalled: false,
  });

  const terminado = vivo.status === "completed" || vivo.status === "failed";

  useEffect(() => {
    if (terminado) return;

    let sondeos = 0;
    let cancelado = false;

    const id = setInterval(async () => {
      if (cancelado) return;
      sondeos += 1;
      if (sondeos > MAX_SONDEOS) {
        clearInterval(id);
        return;
      }
      try {
        const datos = await pollIndexRun(run.id);
        if (!datos || cancelado) return;
        setVivo({
          status: datos.status,
          processed: datos.processed,
          skipped: datos.skipped,
          chunksCreated: datos.chunksCreated,
          errorMessage: datos.errorMessage,
          stalled: datos.stalled,
        });
        if (datos.finished) {
          clearInterval(id);
          // Las fotos antes/después NO viajan en el sondeo: se piden al servidor
          // una vez, al terminar. La referencia hace location.reload() entero.
          router.refresh();
        }
      } catch {
        // Un fallo de red puntual no debe matar el sondeo ni pintar basura:
        // se ignora y el siguiente tick lo vuelve a intentar.
      }
    }, INTERVALO_MS);

    return () => {
      cancelado = true;
      clearInterval(id);
    };
  }, [run.id, terminado, router]);

  const porcentaje =
    run.submittedCount === 0
      ? 0
      : Math.min(100, Math.round((vivo.processed * 100) / run.submittedCount));

  // Delta explícito contra null: un delta de 0 es un resultado, no un "no hay
  // resultado", y `{delta && …}` lo escondería además de pintar un 0 suelto.
  const delta =
    after && before ? after.total_chunks - before.total_chunks : null;

  return (
    <Flex vertical gap={24}>
      <Flex justify="space-between" align="center">
        <Space direction="vertical" size={4}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Ampliación del corpus
          </Typography.Title>
          <Space size={8}>
            {statusTag(vivo.status)}
            <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
              {run.chunkType}
            </Typography.Text>
            <Typography.Text type="secondary">
              {new Date(run.createdAt).toLocaleString("es-ES")}
            </Typography.Text>
          </Space>
        </Space>
        <Link href="/corpus">
          <Button variant="outlined" icon={<ArrowLeftOutlined />}>
            Corpus
          </Button>
        </Link>
      </Flex>

      {vivo.status === "failed" && (
        <Alert
          type="error"
          showIcon
          message="La ampliación falló"
          description={vivo.errorMessage ?? "El servicio IA no aceptó el lote."}
        />
      )}

      {vivo.stalled && !terminado && (
        <Alert
          type="warning"
          showIcon
          message="Sin señales de este trabajo"
          description="Lleva más de tres minutos sin avanzar. El proceso que lo indexaba pudo reiniciarse; los documentos ya procesados están en el corpus."
        />
      )}

      {vivo.status === "completed" && delta !== null && (
        <Alert
          type="success"
          showIcon
          message={`Corpus ampliado: ${delta.toLocaleString("es-ES")} chunks nuevos indexados.`}
          description={
            vivo.skipped > 0
              ? `${vivo.skipped} de ${run.submittedCount} documentos ya estaban en el corpus y se saltaron.`
              : undefined
          }
        />
      )}

      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Space size="large" wrap>
            <Statistic
              title="Documentos"
              value={`${vivo.processed} / ${run.submittedCount}`}
            />
            <Statistic title="Saltados" value={vivo.skipped} />
            <Statistic title="Chunks nuevos" value={vivo.chunksCreated} />
          </Space>
          <Progress
            percent={porcentaje}
            status={
              vivo.status === "failed"
                ? "exception"
                : terminado
                  ? "success"
                  : "active"
            }
          />
          {!terminado && !vivo.stalled && (
            <Typography.Text type="secondary">
              Indexando en segundo plano… esta página se actualiza sola.
            </Typography.Text>
          )}
        </Space>
      </Card>

      {before && after ? (
        <Row gutter={24}>
          <Col span={12}>
            <Card title="Antes" styles={{ body: { padding: 0 } }}>
              <CorpusStatsTable collections={before.collections} />
            </Card>
          </Col>
          <Col span={12}>
            <Card title="Después" styles={{ body: { padding: 0 } }}>
              <CorpusStatsTable collections={after.collections} />
            </Card>
          </Col>
        </Row>
      ) : before ? (
        <Card title="Corpus al iniciar" styles={{ body: { padding: 0 } }}>
          <CorpusStatsTable collections={before.collections} />
        </Card>
      ) : null}
    </Flex>
  );
}
