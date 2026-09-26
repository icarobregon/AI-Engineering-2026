/**
 * Prettier no estaba configurado, y sus valores por defecto no son los de este
 * código: pasarlo a 80 columnas reescribía ficheros enteros que nadie había
 * tocado.
 *
 * Los 100 no son una preferencia, son una medida. Formateando los 99 ficheros
 * escritos a mano con cada ancho y contando cuántas líneas se moverían:
 *
 *     80 -> 2229     95 ->  725     102 ->  646     110 ->  857
 *     90 -> 1164    100 ->  575     105 ->  742
 *
 * El mínimo está en 100 y sube a los dos lados, así que es el ancho con el que
 * el código ya está escrito.
 *
 * Todo lo demás se queda en los valores por defecto de Prettier 3 a propósito:
 * se midieron igual las comillas, el punto y coma, las comas finales, los
 * paréntesis de la flecha, el corchete de cierre en JSX y la tabulación, y
 * cambiar cualquiera de ellos empeora el ajuste. Lo escrito ya sigue esas
 * reglas; sólo discrepaba en el ancho.
 *
 * La versión va fijada en devDependencies, no delegada a `npx`. Sin eso, estos
 * números sólo valdrían para la versión que se bajase ese día: los defaults que
 * aquí se dan por buenos son los de Prettier 3, y un cambio de mayor en el
 * formateador reescribiría el proyecto entero sin que nadie lo hubiera pedido.
 */
const config = {
  printWidth: 100,
};

export default config;
