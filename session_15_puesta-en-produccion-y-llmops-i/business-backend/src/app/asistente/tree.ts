/**
 * El árbol de módulos y tareas: leerlo de un formulario y de la BBDD.
 *
 * Vive aquí y no en `actions.ts` porque un módulo `"use server"` sólo puede
 * exportar funciones async. `leerArbol` es la pieza con más lógica de toda la
 * pantalla: índices con huecos, orden numérico y filas sin nombre.
 */

import { estimateTreeSchema } from "@/lib/estimator/contracts";

/** El árbol tal y como lo edita una persona en el paso 3. */
export type ModuloEditable = {
  name: string;
  description: string | null;
  tasks: { name: string; description: string | null }[];
};

/**
 * Lee el árbol del FormData.
 *
 * Los campos llegan como `modules[0][tasks][1][name]`. Los índices sólo tienen
 * que ser únicos: los huecos que dejan los borrados son legales, así que se
 * ordena por índice numérico en vez de asumir que son consecutivos.
 *
 * Lo que NO se hace es descartar en silencio las filas sin nombre. La app de
 * referencia las tira con un `filter_map`, así que una tarea con 99 h y 99 €/h a
 * la que se le olvidó el nombre desaparece sin decir nada.
 */
export function leerArbol(formData: FormData): { modules: ModuloEditable[]; sinNombre: number } {
  const porModulo = new Map<number, ModuloEditable>();
  let sinNombre = 0;

  const indices = (clave: string) => {
    const m = clave.match(/^modules\[(\d+)\]\[tasks\]\[(\d+)\]\[(\w+)\]$/);
    if (m) return { modulo: Number(m[1]), tarea: Number(m[2]), campo: m[3] };
    const n = clave.match(/^modules\[(\d+)\]\[(\w+)\]$/);
    if (n) return { modulo: Number(n[1]), tarea: null, campo: n[2] };
    return null;
  };

  const tareas = new Map<number, Map<number, { name: string; description: string | null }>>();

  for (const [clave, valor] of formData.entries()) {
    const ref = indices(clave);
    if (!ref) continue;
    const texto = String(valor).trim();

    if (ref.tarea === null) {
      const modulo = porModulo.get(ref.modulo) ?? { name: "", description: null, tasks: [] };
      if (ref.campo === "name") modulo.name = texto;
      if (ref.campo === "description") modulo.description = texto || null;
      porModulo.set(ref.modulo, modulo);
    } else {
      const delModulo = tareas.get(ref.modulo) ?? new Map();
      const tarea = delModulo.get(ref.tarea) ?? { name: "", description: null };
      if (ref.campo === "name") tarea.name = texto;
      if (ref.campo === "description") tarea.description = texto || null;
      delModulo.set(ref.tarea, tarea);
      tareas.set(ref.modulo, delModulo);
    }
  }

  const modules: ModuloEditable[] = [];
  for (const [indice, modulo] of [...porModulo.entries()].sort((a, b) => a[0] - b[0])) {
    const suyas = [...(tareas.get(indice)?.entries() ?? [])].sort((a, b) => a[0] - b[0]);
    const conNombre = suyas.map(([, t]) => t).filter((t) => t.name.length > 0);
    sinNombre += suyas.length - conNombre.length;
    if (modulo.name.length === 0) {
      sinNombre += 1;
      continue;
    }
    modules.push({ ...modulo, tasks: conNombre });
  }

  return { modules, sinNombre };
}

/** Lee el árbol revisado de la columna JSONB, tolerando que aún no exista. */
export function leerArbolGuardado(value: unknown): ModuloEditable[] {
  const parsed = estimateTreeSchema.shape.modules.safeParse(value);
  if (!parsed.success) return [];
  return parsed.data.map((m) => ({
    name: m.name,
    description: m.description,
    tasks: m.tasks.map((t) => ({ name: t.name, description: t.description })),
  }));
}

