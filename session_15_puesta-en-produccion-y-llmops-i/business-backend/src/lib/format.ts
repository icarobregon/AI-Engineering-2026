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
