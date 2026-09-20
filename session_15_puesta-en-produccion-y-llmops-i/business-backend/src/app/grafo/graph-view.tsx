"use client";

import {
  Alert,
  Card,
  Col,
  Empty,
  Flex,
  Input,
  Row,
  Space,
  Tag,
  theme,
  Typography,
} from "antd";

import type { GraphDiagram } from "@/lib/estimator/contracts";
import { graphNodes } from "@/lib/graph-nodes";
import { CollapseCard } from "@/components/collapse-card";

export function GraphView({
  diagram,
  error,
}: {
  diagram: GraphDiagram | null;
  error: string | null;
}) {
  const { token } = theme.useToken();

  return (
    <Flex vertical gap={24}>
      <Space direction="vertical" size={4}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Flujo multi-agente
        </Typography.Title>
        <Typography.Text type="secondary">
          El grafo que orquesta la estimación supervisada, leído del grafo ya
          compilado. Es de sólo lectura: esta pantalla no ejecuta nada.
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
                Sale de{" "}
                <Typography.Text code>graph.get_graph()</Typography.Text> sobre
                el grafo compilado, no de una constante escrita a mano. Y desde
                la Sesión 14 las aristas ya no se declaran: viven dentro de cada{" "}
                <Typography.Text code>Command</Typography.Text>, y LangGraph las
                reconstruye resolviendo la anotación de cada nodo. Si esa
                anotación dejara de resolver, las aristas desaparecerían de aquí
                — que es la señal más temprana de un fallo que por lo demás es
                mudo.
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
            <Typography.Paragraph
              type="secondary"
              style={{ marginTop: 12, marginBottom: 0 }}
            >
              START apunta aquí, y todo lo demás vuelve aquí. No hay topología
              lineal: el camino se elige en tiempo de ejecución y sólo existe
              después, en <Typography.Text code>routing_trail</Typography.Text>{" "}
              — que es lo que pinta la traza de cada ejecución en la pantalla
              del supervisor.
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

          <CollapseCard title="Origen en Mermaid">
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Typography.Text type="secondary">
                Pégalo en cualquier visor de Mermaid. Se sirve tal cual en vez
                de dibujarlo aquí: la librería pesa 124 MB descomprimidos, que
                es mucho contenedor por un diagrama de siete nodos.
              </Typography.Text>
              <Input.TextArea
                readOnly
                value={diagram.mermaid}
                rows={18}
                // La misma pila monoespaciada que usa `Typography` con `code`,
                // por su token: la que había declaraba una variable que no
                // existe, y un `var()` que no resuelve dentro de `font-family`
                // invalida la declaración entera en vez de pasar al siguiente
                // de la lista, así que el código salía en tipografía de texto.
                style={{ fontFamily: token.fontFamilyCode, fontSize: 12 }}
              />
            </Space>
          </CollapseCard>
        </>
      )}
    </Flex>
  );
}

function NodoDetalle({ nombre }: { nombre: string }) {
  const rol = graphNodes[nombre];
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
