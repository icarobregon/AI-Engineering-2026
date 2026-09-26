"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Flex, Spin, Statistic, Timeline, Typography } from "antd";

import { nodeTitle } from "@/lib/graph-nodes";
import type { RunProgress } from "@/lib/estimator/contracts";
import { syncRun, type SyncResult } from "../actions";

/**
 * El feed de una ejecución en marcha.
 *
 * Tres cosas que la implementación de referencia no hace y que son la diferencia
 * entre un feed y un bucle infinito:
 *
 * 1. **Espera creciente.** Su sondeo va a 1,5 s fijos, para siempre. Aquí empieza
 *    en 2 s y crece hasta 10 s: una estimación tarda minutos, y los primeros
 *    segundos son los únicos en los que mirar cada dos segundos aporta algo.
 * 2. **Se rinde.** Con errores seguidos deja de sondear y lo dice, en lugar de
 *    machacar un servicio que ya ha contestado mal cinco veces.
 * 3. **Detecta el atasco.** Si el checkpoint no se mueve en un cuarto de hora,
 *    el run no está lento: está muerto de una forma que nadie registró. Sondearlo
 *    hasta que alguien cierre la pestaña no lo arregla.
 */
const PRIMERA_ESPERA = 2_000;
const ESPERA_MAXIMA = 10_000;
const FACTOR = 1.35;
const ERRORES_SEGUIDOS = 5;
const ATASCO_MS = 15 * 60_000;

function duracion(segundos: number | null): string {
  if (segundos == null) return "";
  if (segundos < 60) return `${segundos.toFixed(1).replace(".", ",")} s`;
  const minutos = Math.floor(segundos / 60);
  return `${minutos} min ${Math.round(segundos % 60)} s`;
}

function atascado(progress: RunProgress | null): boolean {
  if (!progress?.last_activity_at) return false;
  const ultima = Date.parse(progress.last_activity_at);
  return Number.isFinite(ultima) && Date.now() - ultima > ATASCO_MS;
}

export function RunProgressPanel({ id }: { id: string }) {
  const router = useRouter();
  const [progress, setProgress] = useState<RunProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detenido, setDetenido] = useState<string | null>(null);
  // Refs y no estado: cambiarlos no tiene por qué repintar, y leerlos desde el
  // temporizador tiene que dar el valor de AHORA, no el de cuando se programó.
  const espera = useRef(PRIMERA_ESPERA);
  const fallos = useRef(0);
  const vivo = useRef(true);
  /*
    El temporizador no puede reprogramar `sondear` por su nombre: dentro del
    propio useCallback esa referencia apunta al binding de ESTE render, que
    todavía no existe cuando se construye la función. Hoy funciona de milagro
    controlado —lo que la función toca son refs y setters, todos estables— pero
    deja una trampa puesta: si algún día entra en el cuerpo algo que dependa de
    `id`, el temporizador pendiente seguiría llamando a la copia vieja. Un ref
    que apunta siempre a la última versión rompe el ciclo y la trampa a la vez.
  */
  const ultimoSondeo = useRef<() => void>(() => {});

  const sondear = useCallback(async () => {
    let resultado: SyncResult;
    try {
      resultado = await syncRun(id);
    } catch {
      resultado = { progress: null, error: "No se ha podido consultar el avance." };
    }
    if (!vivo.current) return;

    if (resultado.error) {
      setError(resultado.error);
      fallos.current += 1;
      if (fallos.current >= ERRORES_SEGUIDOS) {
        setDetenido("El servicio no responde. Recarga la página para volver a intentarlo.");
        return;
      }
    } else {
      fallos.current = 0;
      setError(null);
      setProgress(resultado.progress);

      if (resultado.progress && resultado.progress.status !== "running") {
        // La fila ya está consolidada por la acción; esto trae a la pantalla lo
        // que el servidor sabe ahora.
        router.refresh();
        return;
      }
      if (atascado(resultado.progress)) {
        setDetenido(
          "La ejecución lleva un cuarto de hora sin dar señales. Es más probable que haya muerto a que siga trabajando.",
        );
        return;
      }
    }

    espera.current = Math.min(Math.round(espera.current * FACTOR), ESPERA_MAXIMA);
    if (vivo.current) window.setTimeout(() => ultimoSondeo.current(), espera.current);
  }, [id, router]);

  useEffect(() => {
    ultimoSondeo.current = sondear;
  }, [sondear]);

  useEffect(() => {
    vivo.current = true;
    const primero = window.setTimeout(sondear, 400);
    return () => {
      vivo.current = false;
      window.clearTimeout(primero);
    };
  }, [sondear]);

  const pasos = progress?.steps ?? [];

  return (
    <Flex vertical gap={16}>
      {detenido ? (
        <Alert
          type="warning"
          showIcon
          message="Se ha dejado de consultar el avance"
          description={detenido}
          action={
            <Button size="small" onClick={() => router.refresh()}>
              Recargar
            </Button>
          }
        />
      ) : (
        <Alert
          type="info"
          showIcon
          icon={<Spin size="small" />}
          message={
            progress?.current
              ? `Trabajando: ${nodeTitle(progress.current)}`
              : "Arrancando la ejecución…"
          }
          description="La estimación corre en el servicio de IA. Puedes cerrar esta pestaña y volver: el progreso se guarda en cada paso."
        />
      )}

      {error && !detenido && (
        <Alert type="warning" showIcon message={`Un sondeo falló: ${error}`} />
      )}

      {progress && (
        <Flex gap={16} wrap>
          <Card style={{ flex: "1 1 180px" }}>
            <Statistic title="Componentes" value={progress.counts.components} />
          </Card>
          <Card style={{ flex: "1 1 180px" }}>
            <Statistic title="Análogos encontrados" value={progress.counts.budget_matches} />
          </Card>
          <Card style={{ flex: "1 1 180px" }}>
            <Statistic title="Pasos de enrutado" value={progress.counts.routing_steps} />
          </Card>
        </Flex>
      )}

      {pasos.length > 0 && (
        <Card title="Qué ha corrido hasta ahora">
          <Timeline
            items={pasos.map((paso, indice) => ({
              key: `${paso.node}-${indice}`,
              color: paso.finished_at ? "green" : "blue",
              dot: paso.finished_at ? undefined : <Spin size="small" />,
              children: (
                <Flex justify="space-between" gap={12}>
                  <Typography.Text strong={!paso.finished_at}>
                    {nodeTitle(paso.node)}
                  </Typography.Text>
                  <Typography.Text type="secondary">{duracion(paso.seconds)}</Typography.Text>
                </Flex>
              ),
            }))}
          />
          <Typography.Text type="secondary">
            Los tiempos salen del checkpointer, que sella cada superstep. El estado del grafo no
            lleva ninguna fecha.
          </Typography.Text>
        </Card>
      )}

      {progress && progress.errors.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message="La ejecución va degradando"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {progress.errors.map((linea) => (
                <li key={linea}>{linea}</li>
              ))}
            </ul>
          }
        />
      )}
    </Flex>
  );
}
