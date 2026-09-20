"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { App, Badge, ConfigProvider, Flex, Layout, Menu, Tooltip, Typography } from "antd";
import esES from "antd/locale/es_ES";

/**
 * Every antd component lives on this side of the boundary.
 *
 * In RSC an `import { Typography } from "antd"` inside a Server Component is an
 * opaque client reference, so `Typography.Title` — a property access on it — is
 * `undefined` at render time. Compound components therefore have to be used from
 * a Client Component. Server Components fetch; this renders.
 */

const items = [
  { key: "/estimations", label: <Link href="/estimations">Estimación</Link> },
  { key: "/chat", label: <Link href="/chat">Conversación</Link> },
  { key: "/supervisor", label: <Link href="/supervisor">Supervisor</Link> },
  { key: "/asistente", label: <Link href="/asistente">Asistente</Link> },
  { key: "/agentes", label: <Link href="/agentes">Agentes</Link> },
  { key: "/grafo", label: <Link href="/grafo">Grafo</Link> },
  { key: "/corpus", label: <Link href="/corpus">Corpus</Link> },
  { key: "/lab/chunking", label: <Link href="/lab/chunking">Laboratorio</Link> },
  { key: "/ajustes", label: <Link href="/ajustes">Ajustes</Link> },
];

export function AppShell({
  model,
  online,
  children,
}: {
  model: string | null;
  online: boolean;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const selected = items.map((i) => i.key).filter((key) => pathname.startsWith(key));

  return (
    <ConfigProvider locale={esES} theme={{ token: { colorPrimary: "#5b21b6" } }}>
      <App>
        <Layout style={{ minHeight: "100vh" }}>
          <Layout.Header style={{ display: "flex", alignItems: "center", gap: 24, paddingInline: 24 }}>
            <Link href="/" style={{ color: "#fff", fontWeight: 600, fontSize: 16 }}>
              Estimator
            </Link>
            <Menu
              theme="dark"
              mode="horizontal"
              selectedKeys={selected}
              items={items}
              style={{ flex: 1, minWidth: 0 }}
            />
            {/* The cheapest liveness signal there is: if the AI service stops
                answering, the badge goes red and every page still renders. */}
            <Tooltip title={online ? "El servicio IA responde" : "El servicio IA no responde"}>
              <Flex align="center" gap={8}>
                <Badge status={online ? "success" : "error"} />
                <Typography.Text style={{ color: "rgba(255,255,255,0.65)" }}>
                  {model ?? (online ? "modelo desconocido" : "sin conexión")}
                </Typography.Text>
              </Flex>
            </Tooltip>
          </Layout.Header>
          <Layout.Content
            style={{ padding: "32px 24px", maxWidth: 1100, margin: "0 auto", width: "100%" }}
          >
            {children}
          </Layout.Content>
        </Layout>
      </App>
    </ConfigProvider>
  );
}
