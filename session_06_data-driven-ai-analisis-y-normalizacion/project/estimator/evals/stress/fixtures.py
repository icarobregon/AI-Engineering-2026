"""Synthetic PDF fixture generator for the attachment-size stress scenario.

Produces in-memory PDF bytes at calibrated sizes using fpdf2.
The content is realistic-looking technical specification text so that
the text extractor (pypdf) produces meaningful tokens rather than garbage.

Calibration:
  fpdf2 output for plain text is roughly 1 byte per char of content after
  PDF structure overhead (~1.5 KB baseline). We aim for file sizes within
  ±20% of the target_kb value.
"""

from __future__ import annotations

_LOREM = (
    "El cliente requiere un sistema de gestión de proyectos software con soporte "
    "multi-tenant, autenticación OAuth2, integración con herramientas de CI/CD, "
    "panel de analíticas en tiempo real y exportación de informes en PDF y Excel. "
    "Los usuarios podrán gestionar sprints, asignar tareas, estimar horas y registrar "
    "el tiempo invertido. El sistema debe cumplir con GDPR y soportar hasta 10.000 "
    "usuarios concurrentes con auto-scaling horizontal. La interfaz será responsiva y "
    "accesible según WCAG 2.1 nivel AA. Se requieren tests unitarios y de integración "
    "con cobertura mínima del 80 por ciento, y despliegue continuo en Kubernetes. "
    "El backend usará Python con FastAPI y PostgreSQL. El frontend será React con "
    "TypeScript. La arquitectura seguirá principios de diseño orientado al dominio. "
    "Se implementará caché distribuida con Redis y mensajería asíncrona con Kafka. "
)

_LOREM_EXTENDED = _LOREM * 20  # ~3600 chars, reusable pool


def generate_pdf_bytes(target_kb: int) -> bytes:
    """Return PDF content approximately ``target_kb`` kilobytes in size.

    Returns an empty bytes object when ``target_kb == 0`` (no attachment).
    """
    if target_kb == 0:
        return b""

    from fpdf import FPDF

    # Empirical calibration: fpdf2 Helvetica output is ~0.63 bytes per char
    # of text content due to PDF stream encoding. Divide by 0.63 and subtract
    # ~1.5 KB of fixed PDF structure overhead to hit the target file size.
    target_content_chars = max(200, int(target_kb * 1024 / 0.63) - 1500)
    pool = _LOREM_EXTENDED
    # Extend pool if needed for very large targets.
    while len(pool) < target_content_chars:
        pool = pool + _LOREM_EXTENDED

    content = pool[:target_content_chars]

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", size=11)

    # Split into pages of ~2000 chars to keep pages readable.
    page_size = 2000
    for offset in range(0, len(content), page_size):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", size=12)
        pdf.cell(0, 8, f"Especificacion tecnica - pagina {offset // page_size + 1}", ln=True)
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, content[offset : offset + page_size])

    return bytes(pdf.output())


ATTACHMENT_SIZES_KB: list[int] = [0, 5, 20, 50, 100]
