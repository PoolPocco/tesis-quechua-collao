# Ejercicios gramaticales en quechua collao

Repositorio de la tesis **«Implementación de un sistema automatizado para la generación de ejercicios gramaticales en quechua collao mediante análisis morfosintáctico»**.

El proyecto reúne seis notebooks de procesamiento del corpus, anotación morfosintáctica, construcción de pares de oraciones, experimentación con LLM, evaluación y selección de ejercicios. En `prototype/` se encuentra una aplicación local de Streamlit que permite practicar con un banco de ejercicios ya preparado.

## Qué permite hacer el prototipo

- Elegir entre cuatro niveles y recorrer los ejercicios con **Anterior** y **Siguiente**.
- Leer una oración en quechua y el cambio gramatical solicitado, con traducciones al español cuando están disponibles.
- Completar los huecos de la oración transformada seleccionando una de cuatro alternativas.
- Pulsar **Verificar** para recibir retroalimentación; si la respuesta es incorrecta, consultar pistas y desplegar la oración de referencia.

El banco **`prototype/bank.jsonl` está incluido en el repositorio**. Para usar la aplicación no es necesario ejecutar los notebooks, reconstruir el banco, instalar un LLM ni configurar credenciales de servicios externos. Las alternativas y la retroalimentación se construyen mediante reglas locales. Es un prototipo de investigación cuyos ejercicios y reglas continúan en revisión.

## Instalación en Windows con PowerShell

Necesitas **Git y Python 3.12** instalados. Esta versión de Python y Streamlit 1.64.0 se utilizaron para verificar el prototipo. Los siguientes comandos usan el lanzador de Python para Windows (`py`).

Desde la carpeta donde quieras guardar el proyecto:

```powershell
git clone https://github.com/PoolPocco/tesis-quechua-collao.git
Set-Location tesis-quechua-collao
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r prototype\requirements.txt
Set-Location prototype
& ..\.venv\Scripts\python.exe -m streamlit run app.py
```

No hace falta activar el entorno virtual: los comandos llaman directamente a su ejecutable. Si `py` no está disponible, utiliza la ruta del ejecutable de Python 3.12 en el paso de creación del entorno.

**Ejecuta la aplicación desde `prototype/`**, porque busca `bank.jsonl` en el directorio actual.

Abre en tu navegador la **Local URL** que muestre Streamlit, normalmente `http://localhost:8501`. En el primer inicio puede aparecer una pregunta opcional de correo electrónico: puedes dejarla vacía y pulsar **Enter**. Para detener el servidor, pulsa **Ctrl+C** en la terminal.

En las siguientes sesiones basta con entrar en `prototype/` y ejecutar:

```powershell
& ..\.venv\Scripts\python.exe -m streamlit run app.py
```

## Archivos principales

| Ruta | Contenido |
|---|---|
| `notebooks/1_*.ipynb` a `notebooks/6_*.ipynb` | Etapas de investigación, en orden numérico. |
| `prototype/app.py` | Interfaz, enmascarado de oraciones, alternativas y retroalimentación. |
| `prototype/bank.jsonl` | Banco incluido que consume la aplicación. |
| `prototype/requirements.txt` | Dependencia directa necesaria para ejecutar la aplicación. |
| `prototype/build_bank.py` | Reconstrucción del banco a partir de resultados experimentales y metadatos. No es necesaria para usar la demo. |

Los notebooks y la reconstrucción del banco requieren datos intermedios, dependencias y rutas del entorno de investigación que no están todos incluidos aquí. Las instrucciones anteriores corresponden únicamente al prototipo con el banco publicado.
