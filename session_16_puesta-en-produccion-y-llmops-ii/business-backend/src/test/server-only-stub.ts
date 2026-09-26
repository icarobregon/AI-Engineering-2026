/**
 * El sustituto de `server-only` en la batería de tests.
 *
 * El paquete real lanza al importarse fuera de un React Server Component, que es
 * exactamente lo que queremos en el build —impide que el token de servicio acabe
 * en un bundle de navegador— y exactamente lo que estorba en Node. Vitest lo
 * redirige aquí; el build no.
 */
export {};
