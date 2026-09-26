import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * La batería del BFF.
 *
 * Corre en Node, sin navegador y sin red: lo que se prueba es la lógica que esta
 * capa tiene de verdad —la taxonomía de errores, el mapeo de respuesta a fila,
 * los parseadores de formulario y los espejos zod—, no que Ant Design pinte.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      /**
       * `server-only` existe para REVENTAR si alguien lo importa desde un bundle
       * de cliente, y su export por defecto es justamente ese throw. En Node eso
       * haría imposible importar `lib/estimator/*` desde un test, así que aquí se
       * sustituye por el módulo vacío que el propio paquete sirve a React Server
       * Components. La protección sigue intacta donde importa: en el build.
       */
      "server-only": fileURLToPath(new URL("./src/test/server-only-stub.ts", import.meta.url)),
    },
  },
});
