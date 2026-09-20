"use client";

import { Alert, Card, Col, Collapse, Empty, Flex, Row, Space, Tag, Typography } from "antd";

import type { GraphDiagram } from "@/lib/estimator/contracts";

/**
 * Qué hace cada nodo, en prosa.
 *
 * Los NOMBRES salen del grafo compilado; esto es sólo la glosa. Un nodo que no
 * esté aquí se pinta igual, con su nombre y sin descripción: así, añadir un
 * agente en Python lo hace aparecer en esta pantalla sin tocarla, que es el
 * fallo correcto — aparecer sin glosa es mucho mejor que no aparecer.
 */
const roles: Record<string, { titulo: string; que: string; herramientas?: string }> = {
  supervisor: {
    titulo: "Supervisor",
    que: "Decide quién actúa en cada paso. Es híbrido: cuatro precondiciones son ifs de Python y al modelo se le hace exactamente una pregunta — el validador señaló evidencia escasa, ¿se vuelve a buscar o esto lo mira una persona?",
  },
  requirements_extractor: {
    titulo: "Extractor de requisitos",
    que: "Convierte la transcripción en requisitos y componentes.",
    herramientas: "ninguna",
  },
  budget_searcher: {
    titulo: "Buscador de presupuestos",
    que: "Busca análogos históricos, componente a componente.",
    herramientas: "search_budgets",
  },
  estimate_generator: {
    titulo: "Generador de la estimación",
    que: "Pone precio a los componentes. Las horas las da la herramienta —mediana de las referencias por 1,15 de contingencia—; al modelo sólo se le piden la justificación y las notas, así que «el modelo se inventa un número» no es un modo de fallo disponible.",
    herramientas: "calculate_estimate",
  },
  coherence_validator: {
    titulo: "Validador de coherencia",
    que: "Produce la señal de confianza. No se le pregunta al modelo cuánto confía en su propia respuesta: se calcula.",
    herramientas: "validate_estimate",
  },
  human_review_gate: {
    titulo: "Puerta humana",
    que: "Pausa la ejecución y espera. Dispara con confianza baja, con la estimación fuera de la banda histórica, o cuando el buscador corrió y no encontró nada. No hace nada más que leer el estado e interrumpir: interrupt() vuelve a ejecutar el cuerpo entero al reanudar, así que lo que escribiera se perdería.",
  },
  finalize: {
    titulo: "Cierre",
    que: "El único que escribe el estado final.",
  },
};

export function GraphView({
  diagram,
  error,
}: {
  diagram: GraphDiagram | null;
  error: string | null;
}) {
  return (
    <Flex vertical gap={24}>
      <Space direction="vertical" size={4}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Flujo multi-agente
        </Typography.Title>
        <Typography.Text type="secondary">
          El grafo que orquesta la estimación supervisada, leído del grafo ya compilado. Es de
          sólo lectura: esta pantalla no ejecuta nada.
        </Typography.Text>
      </Space>

      {error && <Alert type="warning" showIcon message={error} />}

      {!diagram ? (
        <Card>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="Sin topología que enseñar."
          />
        </Card>
      ) : (
        <>
          <Alert
            type="info"
            showIcon
            message="Este dibujo no puede desincronizarse del código"
            description={
              <>
                Sale de <Typography.Text code>graph.get_graph()</Typography.Text> sobre el grafo
                compilado, no de una constante escrita a mano. Y desde la Sesión 14 las aristas ya
                no se declaran: viven dentro de cada{" "}
                <Typography.Text code>Command</Typography.Text>, y LangGraph las reconstruye
                resolviendo la anotación de cada nodo. Si esa anotación dejara de resolver, las
                aristas desaparecerían de aquí — que es la señal más temprana de un fallo que por
                lo demás es mudo.
              </>
            }
          />

          <Card
            title={
              <Space>
                <span>El conductor</span>
                <Tag color="gold">entrada: {diagram.entry_point}</Tag>
              </Space>
            }
          >
            <NodoDetalle nombre={diagram.entry_point} />
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              START apunta aquí, y todo lo demás vuelve aquí. No hay topología lineal: el camino
              se elige en tiempo de ejecución y sólo existe después, en{" "}
              <Typography.Text code>routing_trail</Typography.Text> — que es lo que pinta la traza
              de cada ejecución en la pantalla del supervisor.
            </Typography.Paragraph>
          </Card>

          <Row gutter={[16, 16]}>
            {diagram.nodes
              .filter((n) => n !== diagram.entry_point)
              .map((nombre) => (
                <Col xs={24} md={12} key={nombre}>
                  <Card size="small" style={{ height: "100%" }}>
                    <NodoDetalle nombre={nombre} />
                  </Card>
                </Col>
              ))}
          </Row>

          <Collapse
            items={[
              {
                key: "mermaid",
                label: "Origen en Mermaid",
                children: (
                  <Space direction="vertical" size={8} style={{ width: "100%" }}>
                    <Typography.Text type="secondary">
                      Pégalo en cualquier visor de Mermaid. Se sirve tal cual en vez de dibujarlo
                      aquí: la librería pesa 124 MB descomprimidos, que es mucho contenedor por un
                      diagrama de siete nodos.
                    </Typography.Text>
                    <Typography.Paragraph
                      copyable={{ text: diagram.mermaid }}
                      style={{
                        marginBottom: 0,
                        whiteSpace: "pre-wrap",
                        fontFamily: "var(--font-geist-mono), monospace",
                        fontSize: 12,
                      }}
                    >
                      {diagram.mermaid}
                    </Typography.Paragraph>
                  </Space>
                ),
              },
            ]}
          />
        </>
      )}
    </Flex>
  );
}

function NodoDetalle({ nombre }: { nombre: string }) {
  const rol = roles[nombre];
  return (
    <Space direction="vertical" size={4} style={{ width: "100%" }}>
      <Space size={8} wrap>
        <Typography.Text strong>{rol?.titulo ?? nombre}</Typography.Text>
        <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
          {nombre}
        </Typography.Text>
        {rol?.herramientas && (
          <Tag color={rol.herramientas === "ninguna" ? "default" : "blue"}>
            {rol.herramientas}
          </Tag>
        )}
      </Space>
      {rol ? (
        <Typography.Text type="secondary">{rol.que}</Typography.Text>
      ) : (
        // Un nodo nuevo en Python aparece aquí sin tocar esta pantalla. Sin
        // glosa, pero aparece: el fallo correcto.
        <Typography.Text type="secondary" italic>
          Sin descripción en esta pantalla todavía.
        </Typography.Text>
      )}
    </Space>
  );
}
