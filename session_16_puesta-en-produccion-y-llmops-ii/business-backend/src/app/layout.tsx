import type { Metadata } from "next";
import { AntdRegistry } from "@ant-design/nextjs-registry";

import { AppShell } from "@/components/app-shell";
import { currentPrimaryModel } from "@/lib/estimator/config";
import { pingEstimator } from "@/lib/estimator/client";

import "./globals.css";

export const metadata: Metadata = {
  title: "Estimator — backend de negocio",
  description: "Punto de entrada público del sistema de estimación.",
};

/** Read on every render: this layout is the one place that knows if we are up. */
export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const [model, online] = await Promise.all([currentPrimaryModel(), pingEstimator()]);

  return (
    <html lang="es">
      <body>
        <AntdRegistry>
          <AppShell model={model} online={online}>
            {children}
          </AppShell>
        </AntdRegistry>
      </body>
    </html>
  );
}
