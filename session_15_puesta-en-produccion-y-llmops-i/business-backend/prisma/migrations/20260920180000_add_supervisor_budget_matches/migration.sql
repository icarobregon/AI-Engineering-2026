-- Las referencias que respaldan cada componente, en la fila.
--
-- Ya viajaban dentro de review_payload, pero ese sólo existe si el run se paró
-- ante una persona: de las cuatro estimaciones validadas que hay, tres lo tienen
-- a NULL. Para ésas las referencias vivían únicamente en el checkpoint, y la
-- página degrada ese fetch a null cuando el servicio IA no responde.
--
-- Nullable y sin defecto: una ejecución en curso todavía no las tiene, y una que
-- murió antes de buscar no las tendrá nunca.
ALTER TABLE "supervisor_runs" ADD COLUMN "budget_matches" JSONB;
