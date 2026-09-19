/**
 * Number formatting, in one place and in Spanish.
 *
 * `useGrouping` is explicit on purpose: the es-ES default is `"min2"`, which only
 * groups from five digits up, so a phases table rendered "5000 €" next to
 * "35.750 €" — the same column, two conventions.
 */
const EUR = new Intl.NumberFormat("es-ES", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
  useGrouping: true,
});

const DECIMAL = new Intl.NumberFormat("es-ES", {
  maximumFractionDigits: 0,
  useGrouping: true,
});

export const eur = (value: number) => EUR.format(value);

export const hours = (value: number) => `${DECIMAL.format(value)} h`;

export const percent = (value: number | null | undefined) =>
  value == null ? "—" : `${Math.round(value * 100)} %`;

/**
 * Dólares, y dichos con todas las letras.
 *
 * La aplicación habla de dinero en dos monedas a la vez: el presupuesto que se
 * estima va en euros y lo que cuesta pedirlo va en dólares. En la pantalla de
 * conversación las dos llegan a aparecer bajo la misma etiqueta, "Coste", así
 * que un número sin divisa ahí se lee como euros. `US$` es lo que da es-ES y
 * además distingue del dólar de cualquier otro sitio.
 */
const USD = new Intl.NumberFormat("es-ES", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

const USD_RATE = new Intl.NumberFormat("es-ES", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Lo que costó una llamada: céntimos de céntimo, así que cuatro decimales. */
export const usd = (value: number) => USD.format(value);

/** Tarifa por millón de tokens: entrada / salida, con una sola marca de divisa. */
export const usdPerMillion = (input: number, output: number) =>
  `${USD_RATE.format(input)} / ${USD_RATE.format(output)} US$`;
