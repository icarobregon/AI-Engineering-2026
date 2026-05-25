"""
Script de verificación del entorno de desarrollo

Este script comprueba que todas las herramientas y librerías necesarias
están correctamente instaladas y configuradas.
"""

import os
import sys
import platform
from dotenv import load_dotenv


def print_section(title):
    """Imprime un encabezado de sección"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def check_python():
    """Verifica la versión de Python"""
    print_section("🐍 Python")
    print(f"Versión: {sys.version}")
    print(f"Ejecutable: {sys.executable}")

    required_version = (3, 11)
    if sys.version_info >= required_version:
        print(f"✅ Python {required_version[0]}.{required_version[1]}+ detectado")
    else:
        print(f"⚠️  Se recomienda Python {required_version[0]}.{required_version[1]} o superior")


def check_system():
    """Verifica información del sistema"""
    print_section("💻 Sistema Operativo")
    print(f"Plataforma: {platform.system()} {platform.release()}")
    print(f"Arquitectura: {platform.machine()}")
    print(f"Procesador: {platform.processor()}")


def check_packages():
    """Verifica librerías Python instaladas"""
    print_section("📦 Librerías Python")

    packages = {
        "dotenv": "python-dotenv",
        "fastapi": "FastAPI",
    }

    for module_name, display_name in packages.items():
        try:
            module = __import__(module_name)
            version = getattr(module, "__version__", "desconocida")
            print(f"✅ {display_name:<25} — {version}")
        except ImportError:
            print(f"❌ {display_name:<25} — NO INSTALADA")


def check_env_variables():
    """Verifica variables de entorno"""
    print_section("🔑 Variables de Entorno")

    # Cargar .env
    load_dotenv()

    env_vars = {
        "OPENAI_API_KEY": "OpenAI API Key",
        "ANTHROPIC_API_KEY": "Anthropic API Key",
    }

    for var_name, display_name in env_vars.items():
        value = os.getenv(var_name)
        if value:
            masked = value[:10] + "..." + value[-4:] if len(value) > 14 else "***"
            print(f"✅ {display_name:<25} — {masked}")
        else:
            print(f"❌ {display_name:<25} — NO CONFIGURADA")


def check_docker():
    """Verifica si Docker está instalado"""
    print_section("🐳 Docker")

    import subprocess

    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"✅ Docker — {result.stdout.strip()}")
        else:
            print(f"❌ Docker — No accesible")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(f"❌ Docker — No instalado o no en PATH")

    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"✅ Docker Compose — {result.stdout.strip()}")
        else:
            print(f"❌ Docker Compose — No accesible")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(f"❌ Docker Compose — No instalado")


def main():
    """Función principal"""
    print("\n" + "=" * 60)
    print("  🚀 Verificador de Entorno — Máster AI Engineering 2026")
    print("=" * 60)

    check_system()
    check_docker()
    check_python()
    check_packages()
    check_env_variables()

    print_section("✨ Resumen")
    print("\nSi todos los puntos están ✅, tu entorno está listo para el máster.")
    print("Si hay ❌, sigue las instrucciones en sesion-00_introduccion/README.md para completar la configuración.")
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
