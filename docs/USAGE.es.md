# ModelCrate: guía rápida

1. Abre **Explorar modelos** para buscar por nombre o pegar una URL de búsqueda de Hugging Face. Ollama, LM Studio y Jan son filtros del catálogo; las instalaciones se realizan con Ollama.
2. Abre una ficha, revisa archivos y tamaños y pulsa **Elegir este modelo**. También puedes pegar directamente la URL del repositorio en la ventana principal.
3. Al salir del campo URL o pulsar Enter se consultan las variantes. Se propone una selección según la memoria disponible. Puedes cambiarla.
4. Ajusta nombre, contexto, salida, temperatura y opciones avanzadas. Si cambias contexto o prioridad, pulsa **Usar recomendación** para aplicar el consejo actualizado.
5. Pulsa **Descargar y configurar**. La barra muestra el archivo/capa actual. Al terminar aparece una confirmación con el destino realmente actualizado.

Selecciona un modelo instalado para cambiar ajustes, probar una llamada de herramienta o desinstalarlo. Desinstalar requiere confirmación; cuando la integración de OpenCode está activa, también se comprueba su modelo predeterminado.

El gestor sigue el tema del escritorio, claro u oscuro. No cambia tu tema global.

## Si algo falla

- **Ollama no responde:** comprueba que esté iniciado y disponible en `127.0.0.1:11434`, luego pulsa Actualizar. Puedes explorar el catálogo sin Ollama.
- **OpenCode desactivado:** lee el aviso de la ventana. Se admite únicamente una configuración existente con formato `providers`. El programa no convierte configuraciones ajenas.
- **Descarga cancelada:** Ollama conserva y administra los bloques que puedan reutilizarse. Repite la descarga si quieres continuar.
- **Modelo creado, registro pendiente:** el mensaje distingue el fallo de OpenCode. Corrige su configuración, reinicia ModelCrate y selecciona el modelo instalado para volver a guardar.
- **No hay recomendación:** faltan datos o ninguna variante entra en el presupuesto estimado. No se elige un archivo silenciosamente; puedes seleccionar uno manualmente.
- **Apenas se libera espacio:** otra referencia puede compartir los mismos pesos. No es una segunda descarga.

Los respaldos y registros quedan por defecto en `~/.local/state/modelcrate`. No incluyen los pesos. El instalador solo añade el lanzador, el ícono y la entrada del menú; desinstalar ModelCrate no elimina tus modelos.
