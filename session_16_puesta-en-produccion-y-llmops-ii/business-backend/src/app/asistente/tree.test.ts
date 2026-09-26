/**
 * El lector del árbol de módulos y tareas.
 *
 * Es la pieza con más lógica de la aplicación y la que más silenciosamente puede
 * fallar: lo que salga de aquí es lo que se manda a buscar horas, así que una
 * tarea perdida no da error, sólo desaparece de la estimación.
 */

import { describe, expect, it } from "vitest";

import { leerArbol, leerArbolGuardado } from "./tree";

function form(pares: Record<string, string>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(pares)) fd.append(k, v);
  return fd;
}

describe("leerArbol", () => {
  it("reconstruye módulos y tareas con sus descripciones", () => {
    const { modules, sinNombre } = leerArbol(
      form({
        "modules[0][name]": "Backend",
        "modules[0][description]": "Pedidos y rutas",
        "modules[0][tasks][0][name]": "API de pedidos",
        "modules[0][tasks][0][description]": "CRUD y estados",
        "modules[0][tasks][1][name]": "Planificador de rutas",
        "modules[0][tasks][1][description]": "",
      }),
    );

    expect(sinNombre).toBe(0);
    expect(modules).toEqual([
      {
        name: "Backend",
        description: "Pedidos y rutas",
        tasks: [
          { name: "API de pedidos", description: "CRUD y estados" },
          // Una descripción vacía es null, no "": lo que viaja al servicio es un
          // campo ausente, no una cadena vacía.
          { name: "Planificador de rutas", description: null },
        ],
      },
    ]);
  });

  it("los índices con huecos son legales y se ordenan por número", () => {
    // Borrar la segunda tarea de tres deja 0 y 2. Y 10 va DESPUÉS de 2, que es
    // justo lo que un orden alfabético haría mal.
    const { modules } = leerArbol(
      form({
        "modules[2][name]": "Segundo",
        "modules[0][name]": "Primero",
        "modules[0][tasks][10][name]": "Décima",
        "modules[0][tasks][2][name]": "Tercera",
      }),
    );

    expect(modules.map((m) => m.name)).toEqual(["Primero", "Segundo"]);
    expect(modules[0].tasks.map((t) => t.name)).toEqual(["Tercera", "Décima"]);
  });

  it("cuenta las filas sin nombre en vez de tragárselas", () => {
    // La app de referencia las descarta con un filter_map y no dice nada: una
    // tarea con horas y tarifa a la que se le olvidó el nombre desaparece.
    const { modules, sinNombre } = leerArbol(
      form({
        "modules[0][name]": "Backend",
        "modules[0][tasks][0][name]": "API",
        "modules[0][tasks][1][name]": "   ",
        "modules[1][name]": "",
        "modules[1][tasks][0][name]": "Huérfana",
      }),
    );

    expect(modules).toHaveLength(1);
    expect(modules[0].tasks.map((t) => t.name)).toEqual(["API"]);
    // Una tarea en blanco y un módulo en blanco.
    expect(sinNombre).toBe(2);
  });

  it("recorta los espacios de alrededor", () => {
    const { modules } = leerArbol(
      form({ "modules[0][name]": "  Backend  ", "modules[0][tasks][0][name]": " API " }),
    );

    expect(modules[0].name).toBe("Backend");
    expect(modules[0].tasks[0].name).toBe("API");
  });

  it("ignora los campos del formulario que no son del árbol", () => {
    // El FormData lleva también run_id y los internos de la Server Action.
    const { modules } = leerArbol(
      form({
        run_id: "abc",
        $ACTION_KEY: "x",
        "hours[t0]": "40",
        "modules[0][name]": "Backend",
      }),
    );

    expect(modules).toEqual([{ name: "Backend", description: null, tasks: [] }]);
  });

  it("un módulo sin tareas es válido: puede ser el siguiente paso de alguien", () => {
    const { modules, sinNombre } = leerArbol(form({ "modules[0][name]": "Por decidir" }));

    expect(modules[0].tasks).toEqual([]);
    expect(sinNombre).toBe(0);
  });

  it("un formulario sin árbol devuelve vacío, no revienta", () => {
    expect(leerArbol(form({}))).toEqual({ modules: [], sinNombre: 0 });
  });
});

describe("leerArbolGuardado", () => {
  it("lee el árbol persistido y se queda sólo con nombre y descripción", () => {
    const guardado = [
      {
        name: "Backend",
        description: null,
        tasks: [{ name: "API", description: "CRUD", grounded: false, engineer_days: null }],
      },
    ];

    expect(leerArbolGuardado(guardado)).toEqual([
      { name: "Backend", description: null, tasks: [{ name: "API", description: "CRUD" }] },
    ]);
  });

  it("una columna vacía o con otra forma devuelve lista vacía, no lanza", () => {
    // Se lee de JSONB, que puede tener cualquier cosa si alguien la tocó a mano.
    expect(leerArbolGuardado(null)).toEqual([]);
    expect(leerArbolGuardado({ no: "es un array" })).toEqual([]);
    expect(leerArbolGuardado([{ falta: "el nombre" }])).toEqual([]);
  });
});
