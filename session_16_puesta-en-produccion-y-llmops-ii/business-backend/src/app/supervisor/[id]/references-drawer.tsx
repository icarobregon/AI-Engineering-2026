"use client";

import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Flex,
  Skeleton,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";

import { CollapseCard } from "@/components/collapse-card";
import { hours } from "@/lib/format";
import type { BudgetMatch, Reference } from "@/lib/estimator/contracts";
import { fetchReferences, type ReferencesResult } from "../actions";

/** Lo mínimo del componente que el panel necesita para titularse. */
export type ComponenteAbierto = {
  component_id: string;
  name: string;
  estimated_hours: number;
};

/**
 * El acceso al desglose, debajo del razonamiento del componente.
 *
 * Enlace y no botón: va dentro de una celda de tabla, entre texto, y un botón
 * con su caja rompería la lectura de la columna. No se pinta cuando no hay
 * referencias —un componente sin precedente no tiene nada que abrir— en vez de
 * salir deshabilitado: un control apagado invita a preguntarse qué falta, y aquí
 * no falta nada, sencillamente no hay respaldo, que es justo lo que ya dice su
 * etiqueta roja.
 */
export function BotonReferencias({
  matches,
  onVer,
}: {
  matches: BudgetMatch[] | undefined;
  onVer: () => void;
}) {
  if (!matches || matches.length === 0) return null;
  return (
    <Button type="link" size="small" style={{ padding: 0, height: "auto" }} onClick={onVer}>
      {matches.length === 1 ? "Ver la referencia" : `Ver las ${matches.length} referencias`}
    </Button>
  );
}

/**
 * De dónde sale el número que el sistema propuso para un componente.
 *
 * Un Drawer y no una modal porque lo que hay que enseñar son VARIAS referencias
 * —cinco por componente— y cada una trae su propio desglose: en una modal eso es
 * una caja que crece hasta comerse la pantalla, y aquí es una columna que se
 * recorre sin perder de vista la estimación que hay detrás.
 *
 * La jerarquía va de «cuánto» a «por qué me lo creo»: en la cabecera de cada
 * referencia, las horas y la proximidad, que es lo que se compara; dentro, el
 * contexto que dice si es comparable —sector, año, tecnología— y el desglose por
 * tareas, cuya suma ES ese total. Eso último es lo que convierte la pantalla en
 * algo auditable: no enseña un dato parecido, enseña la descomposición exacta de
 * lo que el estimador usó.
 */
export function ReferencesDrawer({
  componente,
  horasEstimadas,
  matches,
  onClose,
}: {
  /** El componente cuya estimación se está justificando; null cierra el panel. */
  componente: string | null;
  horasEstimadas: number | null;
  matches: BudgetMatch[];
  onClose: () => void;
}) {
  /*
    La respuesta viaja etiquetada con el componente al que pertenece, en vez de
    vaciarse al empezar cada petición. Así no hay un setState síncrono dentro del
    efecto —que es un render en cascada— y, sobre todo, abrir un componente justo
    después de otro no enseña un instante los datos del anterior: mientras la
    etiqueta no coincida, lo que se pinta es el esqueleto.
  */
  const [resultado, setResultado] = useState<{ para: string; valor: ReferencesResult } | null>(
    null,
  );

  useEffect(() => {
    if (componente === null) return;
    let vigente = true;
    fetchReferences(matches.map((m) => m.reference_budget_id)).then((valor) => {
      // Cerrar el panel mientras la petición viaja no debe pintar su respuesta.
      if (vigente) setResultado({ para: componente, valor });
    });
    return () => {
      vigente = false;
    };
    // `matches` se reconstruye en cada render del padre; la identidad que importa
    // es la del componente abierto, que es lo que de verdad cambia la petición.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componente]);

  const respuesta = resultado !== null && resultado.para === componente ? resultado.valor : null;

  const importes = matches.map((m) => m.amount);
  const rango =
    importes.length > 0
      ? `${matches.length} referencia${matches.length === 1 ? "" : "s"} entre ${hours(
          Math.min(...importes),
        )} y ${hours(Math.max(...importes))}`
      : "sin referencias";

  return (
    <Drawer
      open={componente !== null}
      onClose={onClose}
      width={720}
      title={
        <Flex vertical gap={2}>
          <Typography.Text strong>{componente}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontWeight: 400, fontSize: 13 }}>
            {horasEstimadas != null ? `${hours(horasEstimadas)} estimadas · ` : ""}
            {rango}
          </Typography.Text>
        </Flex>
      }
    >
      {respuesta === null ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : respuesta.error !== null ? (
        <Alert
          type="error"
          showIcon
          message="No se ha podido abrir el desglose"
          description={respuesta.error}
        />
      ) : (
        <Flex vertical gap={16}>
          {respuesta.data.missing.length > 0 && (
            /*
              No es un detalle menor ni un fallo que ocultar: el corpus se
              reindexa, y una estimación guardada cita lo que había entonces. Que
              parte del respaldo haya dejado de existir es justo lo que un
              revisor necesita saber antes de aprobar.
            */
            <Alert
              type="warning"
              showIcon
              message="Parte del respaldo ya no está en el corpus"
              description={
                <>
                  Estas referencias se usaron para estimar y hoy no se encuentran:{" "}
                  {respuesta.data.missing.join(", ")}.
                </>
              }
            />
          )}

          {respuesta.data.references.length === 0 && respuesta.data.missing.length === 0 && (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Sin referencias que abrir" />
          )}

          {respuesta.data.references.map((referencia) => (
            <ReferenciaPanel
              key={referencia.reference_budget_id}
              referencia={referencia}
              match={matches.find((m) => m.reference_budget_id === referencia.reference_budget_id)}
              // La primera abierta: es la más próxima, y llegar y tener que
              // hacer un clic para ver algo es una fricción sin contrapartida.
              defaultOpen={
                referencia.reference_budget_id === respuesta.data.references[0]?.reference_budget_id
              }
            />
          ))}
        </Flex>
      )}
    </Drawer>
  );
}

/**
 * La distancia, dicha en palabras.
 *
 * El número crudo (0,3215) no significa nada para quien revisa, pero tirarlo del
 * todo tampoco vale: es el criterio por el que el buscador eligió esta
 * referencia. Los cortes se anclan en el umbral del propio buscador —0,6, por
 * encima del cual ni siquiera la habría devuelto— y el valor exacto queda a un
 * palmo, en el tooltip, para quien quiera comprobarlo.
 */
function proximidad(distance: number): { texto: string; color: string } {
  if (distance < 0.4) return { texto: "muy próxima", color: "green" };
  if (distance < 0.5) return { texto: "próxima", color: "blue" };
  return { texto: "en el límite", color: "orange" };
}

function ReferenciaPanel({
  referencia,
  match,
  defaultOpen,
}: {
  referencia: Reference;
  match: BudgetMatch | undefined;
  defaultOpen: boolean;
}) {
  const cerca = match ? proximidad(match.distance) : null;

  return (
    <CollapseCard
      defaultOpen={defaultOpen}
      title={
        <Flex align="center" gap={8} wrap>
          <Typography.Text strong>{referencia.module}</Typography.Text>
          {/*
            El presupuesto, en la cabecera y no sólo dentro: un componente se
            respalda a menudo con el MISMO módulo de cinco proyectos distintos
            —«Authentication & Access» las cinco veces— y plegadas sólo se
            distinguían por las horas.
          */}
          <Typography.Text type="secondary">{referencia.budget_id}</Typography.Text>
          {cerca && match && (
            <Tooltip
              title={`Distancia semántica ${match.distance.toFixed(3)} sobre un máximo útil de 0,6`}
            >
              <Tag color={cerca.color}>{cerca.texto}</Tag>
            </Tooltip>
          )}
        </Flex>
      }
      extra={<Typography.Text strong>{hours(referencia.total_hours)}</Typography.Text>}
    >
      <Flex vertical gap={12}>
        {/*
          El contexto va ANTES del desglose a propósito: decide si la referencia
          vale, y descubrirlo después de leer ocho tareas es haber leído ocho
          tareas para nada. Un precedente de otro sector, de hace cuatro años o
          de otro stack no traslada sus horas.
        */}
        <Descriptions
          size="small"
          column={2}
          items={[
            { key: "proyecto", label: "Proyecto", span: 2, children: referencia.project || "—" },
            { key: "sector", label: "Sector", children: referencia.client_sector || "—" },
            { key: "anio", label: "Año", children: referencia.year ?? "—" },
            { key: "tec", label: "Tecnología", children: referencia.main_technology || "—" },
          ]}
        />

        <Table
          rowKey="component_id"
          size="small"
          dataSource={referencia.tasks}
          pagination={false}
          columns={[
            {
              title: "Tarea",
              dataIndex: "name",
              render: (value: string, fila) => (
                <Flex vertical gap={0}>
                  <Typography.Text>{value}</Typography.Text>
                  <Typography.Text type="secondary">{fila.description}</Typography.Text>
                </Flex>
              ),
            },
            { title: "Stack", dataIndex: "tech_stack", width: 170 },
            { title: "Compl.", dataIndex: "complexity", width: 90 },
            {
              title: "Horas",
              dataIndex: "estimated_hours",
              width: 90,
              align: "right",
              render: hours,
            },
          ]}
          summary={() => (
            // La suma, escrita: es literalmente el número que el estimador
            // comparó con este componente, y verlo cuadrar con las filas de
            // arriba es lo que hace que la referencia se pueda auditar.
            <Table.Summary.Row>
              <Table.Summary.Cell index={0} colSpan={3}>
                <Typography.Text strong>Total del módulo</Typography.Text>
              </Table.Summary.Cell>
              <Table.Summary.Cell index={3} align="right">
                <Typography.Text strong>{hours(referencia.total_hours)}</Typography.Text>
              </Table.Summary.Cell>
            </Table.Summary.Row>
          )}
        />
      </Flex>
    </CollapseCard>
  );
}
