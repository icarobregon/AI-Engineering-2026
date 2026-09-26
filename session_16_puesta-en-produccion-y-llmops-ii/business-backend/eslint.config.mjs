/**
 * El script `lint` de este proyecto llevaba roto desde que existe: era el
 * `next lint` que dejaba create-next-app, Next 16 lo elimino y ESLint no estaba
 * ni instalado, asi que la orden fallaba con «no such directory: .../lint».
 *
 * `eslint-config-next/core-web-vitals` ya trae dentro `next/typescript`, asi
 * que extenderlo una sola vez es todo lo que hace falta. Desde la 16 exporta
 * config PLANA —un array de bloques—, de modo que aqui no hay FlatCompat ni
 * `@eslint/eslintrc`: eso solo era necesario mientras el paquete publicaba el
 * formato viejo.
 *
 * ESLint se queda en la 9 a proposito. La 10 instala sin quejarse, pero
 * eslint-plugin-react, -import y -jsx-a11y —que entran por este config— declaran
 * como peer hasta la 9, y arrancar con una combinacion que sus propios autores
 * no soportan es pedir un fallo raro mas adelante.
 */
import next from "eslint-config-next/core-web-vitals";

const config = [
  {
    /*
      La config plana NO lee el .gitignore (a diferencia de Prettier 3), asi que
      lo que no es codigo escrito hay que nombrarlo aqui. src/generated es el
      cliente de Prisma: lo reescribe `prisma generate` en cada build y lintarlo
      son miles de avisos sobre codigo que nadie va a tocar.
    */
    ignores: ["src/generated/**", ".next/**", "next-env.d.ts"],
  },
  ...next,
];

export default config;
