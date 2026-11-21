# Plantilla SRS modular en LaTeX

## Compilación

Desde la raíz del proyecto:

```bash
pdflatex main.tex
pdflatex main.tex
```

También puede compilarse con `latexmk -pdf main.tex`.

## Estructura

- `main.tex`: punto de entrada; importa todas las secciones.
- `config/`: paquetes, datos del documento y comandos reutilizables.
- `secciones/`: las cuatro secciones principales del documento.
- `modulos/`: descripción y requisitos funcionales independientes por módulo.
- `anexos/`: reservado para material complementario.

## Agregar un módulo

1. Copia `modulos/requisitos-modulo-02.tex` y renómbralo.
2. Cambia el nombre del módulo y el prefijo de sus requisitos.
3. Agrega el comando `\input{modulos/nombre-del-archivo}` en
   `secciones/03-requerimientos-especificos.tex`.
4. Agrega su descripción en `modulos/descripcion-modulos.tex`.
5. Incorpora sus identificadores en la tabla de trazabilidad de
   `secciones/04-verificacion-trazabilidad.tex`.

Los identificadores deben ser únicos dentro del documento. Sustituye los textos entre
corchetes por el contenido del proyecto.
