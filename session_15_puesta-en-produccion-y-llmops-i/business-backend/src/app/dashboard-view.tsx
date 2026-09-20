"use client";

import Link from "next/link";
import { Button, Card, Col, Flex, Row, Space, Typography } from "antd";

export function DashboardView({
  estimations,
  awaiting,
}: {
  estimations: number;
  awaiting: number;
}) {
  return (
    <Flex vertical gap={24}>
      <Space direction="vertical" size={4}>
        <Typography.Title level={2} style={{ margin: 0 }}>
          Sistema de estimación
        </Typography.Title>
        <Typography.Text type="secondary">
          Esta capa es el único punto de entrada público. El servicio IA vive en la red privada y
          nadie más que este backend lo alcanza.
        </Typography.Text>
      </Space>

      <Row gutter={16}>
        <Col span={12}>
          <Card
            title="Estimación transaccional"
            extra={<Typography.Text type="secondary">Sesión 04</Typography.Text>}
          >
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                Un disparo: descripción del proyecto dentro, desglose por fases con coste y
                confianza fuera.
              </Typography.Paragraph>
              <Typography.Text>
                <Typography.Text strong style={{ fontSize: 24 }}>
                  {estimations}
                </Typography.Text>{" "}
                registradas
              </Typography.Text>
              <Space>
                <Link href="/estimations/new">
                  <Button type="primary">Nueva</Button>
                </Link>
                <Link href="/estimations">
                  <Button>Histórico</Button>
                </Link>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col span={12}>
          <Card
            title="Supervisor y revisión humana"
            extra={<Typography.Text type="secondary">Sesión 14</Typography.Text>}
          >
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                Agentes especializados coordinados en ejecución. Se detiene sólo cuando la
                estimación no es fiable.
              </Typography.Paragraph>
              <Typography.Text>
                <Typography.Text strong style={{ fontSize: 24 }} type={awaiting > 0 ? "warning" : undefined}>
                  {awaiting}
                </Typography.Text>{" "}
                esperando revisión
              </Typography.Text>
              <Space>
                <Link href="/supervisor/new">
                  <Button type="primary">Nueva</Button>
                </Link>
                <Link href="/supervisor">
                  <Button>Bandeja</Button>
                </Link>
              </Space>
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={8}>
          <Card
            title="Conversación"
            extra={<Typography.Text type="secondary">Sesión 05</Typography.Text>}
          >
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                Estimación a varios turnos, con memoria, adjuntos y el modo
                Actor-Critic-Boss.
              </Typography.Paragraph>
              <Link href="/chat">
                <Button>Abrir</Button>
              </Link>
            </Space>
          </Card>
        </Col>
        <Col span={8}>
          <Card
            title="Flujo multi-agente"
            extra={<Typography.Text type="secondary">Sesiones 13–14</Typography.Text>}
          >
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                Qué agentes hay, qué puede tocar cada uno y cómo se pasan el control. Leído del
                grafo compilado, no de un dibujo.
              </Typography.Paragraph>
              <Link href="/grafo">
                <Button>Abrir</Button>
              </Link>
            </Space>
          </Card>
        </Col>
        <Col span={8}>
          <Card
            title="Asistente de estimación"
            extra={<Typography.Text type="secondary">Sesiones 09–12</Typography.Text>}
          >
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                De una transcripción a una estimación fundamentada, en cinco pasos y con una
                persona revisando entre medias.
              </Typography.Paragraph>
              <Link href="/asistente">
                <Button>Abrir</Button>
              </Link>
            </Space>
          </Card>
        </Col>
        <Col span={8}>
          <Card
            title="Corpus e índice"
            extra={<Typography.Text type="secondary">Sesión 11</Typography.Text>}
          >
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                Mira qué hay indexado en la base vectorial y amplíalo con presupuestos nuevos,
                viendo el corpus crecer.
              </Typography.Paragraph>
              <Link href="/corpus">
                <Button>Abrir</Button>
              </Link>
            </Space>
          </Card>
        </Col>
        <Col span={8}>
          <Card
            title="Laboratorio de chunking"
            extra={<Typography.Text type="secondary">Sesión 07</Typography.Text>}
          >
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                Trocea el mismo corpus con ocho estrategias y compara coste, tamaño y qué
                recupera cada una.
              </Typography.Paragraph>
              <Link href="/lab/chunking">
                <Button>Abrir</Button>
              </Link>
            </Space>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="Ajustes" extra={<Typography.Text type="secondary">Transversal</Typography.Text>}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                Cambia en caliente el modelo de cada pieza del sistema, sin recrear
                contenedores.
              </Typography.Paragraph>
              <Link href="/ajustes">
                <Button>Abrir</Button>
              </Link>
            </Space>
          </Card>
        </Col>
      </Row>
    </Flex>
  );
}
