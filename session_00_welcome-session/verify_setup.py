"""Verifica que el entorno local cumple con lo definido en el README de la sesión 00.

Comprueba:
- Docker y Docker Compose instalados y daemon activo
- uv instalado y Python 3.11 disponible
- FastAPI importable desde el entorno actual
- Estructura mínima del proyecto (main.py, pyproject.toml, .python-version)
- Que la app FastAPI de main.py responde en el endpoint raíz

Uso:
    uv run python verify_setup.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

OK = "[OK]  "
FAIL = "[FAIL]"
WARN = "[WARN]"

ROOT = Path(__file__).resolve().parent


def run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"


def check(label: str, ok: bool, detail: str = "") -> bool:
    marker = OK if ok else FAIL
    suffix = f" — {detail}" if detail else ""
    print(f"{marker} {label}{suffix}")
    return ok


def check_docker() -> bool:
    if not shutil.which("docker"):
        return check("Docker CLI instalado", False, "binario `docker` no encontrado en PATH")
    code, out = run(["docker", "--version"])
    if not check("Docker CLI instalado", code == 0, out):
        return False

    code, out = run(["docker", "compose", "version"])
    check("Docker Compose plugin", code == 0, out)

    code, out = run(["docker", "info", "--format", "{{.ServerVersion}}"])
    return check(
        "Docker daemon activo",
        code == 0 and bool(out),
        f"server {out}" if code == 0 else "daemon no responde — ¿está Docker Desktop abierto?",
    )


def check_uv_and_python() -> bool:
    if not shutil.which("uv"):
        return check("uv instalado", False, "binario `uv` no encontrado en PATH")
    code, out = run(["uv", "--version"])
    check("uv instalado", code == 0, out)

    code, out = run(["uv", "python", "list", "--only-installed"])
    has_311 = code == 0 and bool(re.search(r"\bcpython-3\.11\.", out))
    check(
        "Python 3.11 disponible via uv",
        has_311,
        "ejecuta `uv python install 3.11`" if not has_311 else "",
    )

    pyver = sys.version_info
    current_ok = pyver.major == 3 and pyver.minor == 11
    check(
        "Intérprete actual es 3.11",
        current_ok,
        f"{pyver.major}.{pyver.minor}.{pyver.micro}",
    )
    return has_311 and current_ok


def check_fastapi() -> bool:
    try:
        import fastapi  # noqa: F401
    except ImportError as exc:
        return check("FastAPI importable", False, str(exc))

    try:
        version = metadata.version("fastapi")
    except metadata.PackageNotFoundError:
        version = "?"
    check("FastAPI importable", True, f"v{version}")

    try:
        import uvicorn  # noqa: F401
        uv_version = metadata.version("uvicorn")
        check("Uvicorn disponible", True, f"v{uv_version}")
    except ImportError:
        check("Uvicorn disponible", False, "no instalado")
        return False
    return True


def check_project_files() -> bool:
    expected = ["main.py", "pyproject.toml", ".python-version"]
    all_ok = True
    for name in expected:
        path = ROOT / name
        ok = path.is_file()
        check(f"Fichero presente: {name}", ok, "" if ok else f"falta {path}")
        all_ok = all_ok and ok
    return all_ok


def check_fastapi_app() -> bool:
    main_py = ROOT / "main.py"
    if not main_py.is_file():
        return check("App FastAPI ejecutable", False, "main.py no existe")

    sys.path.insert(0, str(ROOT))
    try:
        from fastapi.testclient import TestClient

        import main  # noqa: WPS433

        client = TestClient(main.app)
        response = client.get("/")
        ok = response.status_code == 200 and "mensaje" in response.json()
        return check(
            "Endpoint `/` responde 200",
            ok,
            f"status={response.status_code} body={response.json()}",
        )
    except Exception as exc:
        return check("App FastAPI ejecutable", False, repr(exc))
    finally:
        sys.path.pop(0)


def main() -> int:
    print("=== Verificación del entorno — Sesión 00 ===\n")

    sections = [
        ("Docker", check_docker),
        ("uv y Python", check_uv_and_python),
        ("FastAPI", check_fastapi),
        ("Ficheros del proyecto", check_project_files),
        ("App FastAPI funcional", check_fastapi_app),
    ]

    results: list[bool] = []
    for title, fn in sections:
        print(f"\n--- {title} ---")
        results.append(fn())

    print("\n=== Resumen ===")
    passed = sum(results)
    total = len(results)
    print(f"{passed}/{total} bloques superados")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
