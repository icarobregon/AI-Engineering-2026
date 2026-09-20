"use client";

import type { CSSProperties, ReactNode } from "react";
import { Collapse, ConfigProvider, theme } from "antd";

/**
 * Un `Collapse` que se ve como una `Card`.
 *
 * Existe porque esta pantalla está convirtiendo tarjetas en desplegables y el
 * cambio no puede notarse: una sección que se puede plegar no debería parecer
 * un componente distinto de las que no. Sin esto, cada conversión arrastraría su
 * propia copia de los mismos seis ajustes y la tercera ya no coincidiría.
 *
 * Los valores salen de los TOKENS del tema, no escritos a mano: la cabecera de
 * `Card` usa `fontSizeLG` + `fontWeightStrong` sobre `colorBgContainer` con el
 * borde en `colorBorderSecondary`, así que se piden por nombre. Cambiar el tema
 * mueve las dos cosas a la vez, que es justo lo que un color copiado no hace.
 */
/** Lo que mide `.ant-card-head`, medido en pantalla. */
const ALTO_CABECERA = 56;

export function CollapseCard({
  title,
  extra,
  children,
  defaultOpen = false,
  styles,
}: {
  title: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  /** Cerrado por defecto: se pliega lo que se consulta, no lo que se viene a ver. */
  defaultOpen?: boolean;
  /**
   * Con la misma forma que `Card`, para que convertir una sea cambiar la
   * etiqueta y nada más. El caso real es `{ body: { padding: 0 } }`: una tabla
   * que va a ras de los bordes, como ya hacen media docena de tarjetas.
   */
  styles?: { body?: CSSProperties };
}) {
  const { token } = theme.useToken();

  return (
    // El separador entre cabecera y cuerpo lo pinta `.ant-collapse-panel` con
    // `var(--ant-color-border)`, que es el gris fuerte. `Card` usa el suave para
    // lo mismo. No hay ranura semántica para el panel —`styles` sólo expone
    // root, header, title, body e icon— así que la vía es el token del
    // componente, que además queda acotado a este Collapse y no toca los
    // `ghost` de /grafo, la traza ACB ni el laboratorio.
    <ConfigProvider
      theme={{
        components: { Collapse: { colorBorder: token.colorBorderSecondary } },
      }}
    >
      <Collapse
        defaultActiveKey={defaultOpen ? ["contenido"] : undefined}
        // `expandIconPlacement` y no `expandIconPosition`: el segundo está
        // deprecado en antd 6 y avisa por consola en desarrollo.
        expandIconPlacement="end"
        styles={{
          root: {
            background: token.colorBgContainer,
            borderColor: token.colorBorderSecondary,
          },
          header: {
            // Exactamente lo que hace `Card`: alto fijo y centrado, en vez de
            // repartir el sobrante del renglón con una división que se queda a un
            // píxel y depende de `lineHeight`.
            minHeight: ALTO_CABECERA,
            padding: `0 ${token.paddingLG}px`,
            display: "flex",
            alignItems: "center",
          },
          title: {
            fontSize: token.fontSizeLG,
            fontWeight: token.fontWeightStrong,
          },
          body: {
            background: token.colorBgContainer,
            padding: token.paddingLG,
            ...styles?.body,
            // SIN borde superior. Lo dibuja ya `.ant-collapse-panel`, y ponerlo
            // aquí además pintaba DOS líneas pegadas —la suya en `colorBorder`
            // (#d9d9d9) y la mía en `colorBorderSecondary` (#f0f0f0)— que juntas
            // se leen como un filete el doble de grueso y más oscuro. Lo que hacía
            // falta no era otra línea, sino recolorear la suya: de eso se encarga
            // el `colorBorder` del ConfigProvider de abajo.
          },
        }}
        items={[{ key: "contenido", label: title, extra, children }]}
      />
    </ConfigProvider>
  );
}
