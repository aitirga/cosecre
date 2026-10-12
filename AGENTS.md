# Instrucciones para agentes de Cosecre

## Desarrollo

- Usar `uv` para dependencias y gestión de proyectos Python.
- Consultar el `justfile` existente y los de proyectos hermanos antes de añadir comandos. Agrupar los comandos por flujo, con nombres claros para setup, dev, build, run, checks y las tareas de datos, base de datos o exportación aplicables. Añadir ayuda breve y respetar `NO_COLOR` y las salidas no interactivas.
- Usar mensajes de commit con tipo y verbo en infinitivo: `feat: añadir ...`, `docs: documentar ...`, `bugfix: corregir ...`, `refactor: reorganizar ...`.
- Usar `aitor.iraola@amphos21.com` como correo del autor de los commits.
- Crear ramas con prefijo correspondiente al trabajo: `feat/`, `bugfix/`, `docs/`, `refactor/`, etc.
- Preservar cambios locales ajenos a la tarea y añadir al commit únicamente sus archivos o fragmentos.

## Integración con Esfer@

Antes de operar Esfer@ o desarrollar su integración, leer
[Esfer@ para agentes y desarrollo de Cosecre](docs/integrations/esfera.md).
Es la referencia de cobertura, procesos de secretaría, casuísticas, contratos
actuales y diseño de exportación. Distingue código versionado, trabajo local,
observaciones anteriores y propuestas pendientes.

La guía no habilita operaciones remotas por sí sola. Aplicar la autorización de
la tarea concreta, verificar centro y entorno, y comprobar las capacidades en el
checkout actual. El importador de partidas recibe datos **desde** Esfer@; el
explorador local consulta datos. Ninguno constituye un exportador contable.
