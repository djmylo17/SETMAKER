# Formato de intercambio SETMAKER → CrateDJ

SETMAKER puede guardar un set como archivo **JSON para CrateDJ**. CrateDJ es una app
aparte (no comparte código con SETMAKER), así que este documento es el **contrato**:
todo lo que CrateDJ necesita para importar un set está descrito aquí.

- Nombre del formato: `setmaker-crate`
- Versión actual: `1`
- Codificación: UTF-8 **sin** BOM, JSON con sangría (se puede abrir con el Bloc de notas).
- Extensión sugerida: `.json` (ej. `2026-10-25 Cumple Sofía - set.json`).

## Reglas de compatibilidad

1. CrateDJ debe revisar que `format` sea `"setmaker-crate"`. Si no, no es un archivo de SETMAKER.
2. Si `version` es **mayor** que la que CrateDJ conoce, debe avisar ("este archivo es de una
   versión más nueva de SETMAKER") y puede intentar leer igual los campos conocidos.
3. SETMAKER puede **agregar campos nuevos** sin cambiar la versión. CrateDJ debe **ignorar**
   los campos que no conozca.
4. Solo se sube `version` cuando se quita o cambia el significado de un campo existente.
5. Los campos marcados "o `null`" pueden venir como `null`; CrateDJ no debe fallar por eso.

## Estructura general

```json
{
  "format": "setmaker-crate",
  "version": 1,
  "generated_at": "2026-10-22T18:30:00-03:00",
  "app_version": "0.1.0",
  "event": { ... },
  "blocks": [ ... ],
  "tracks": [ ... ]
}
```

| Campo | Tipo | Qué es |
|---|---|---|
| `format` | texto | Siempre `"setmaker-crate"`. |
| `version` | número entero | Versión del formato (hoy `1`). |
| `generated_at` | texto (fecha ISO 8601 con zona horaria) | Cuándo se creó el archivo. |
| `app_version` | texto | Versión de SETMAKER que lo creó (ej. `"0.1.0"`). |
| `event` | objeto | Datos del evento (ver abajo). |
| `blocks` | lista | Bloques del set en orden (ver abajo). Puede venir vacía. |
| `tracks` | lista | Temas del set en el orden en que se tocarían (ver abajo). |

## `event`

| Campo | Tipo | Qué es |
|---|---|---|
| `name` | texto | Nombre del evento (ej. `"Cumple Sofía"`). |
| `date` | texto | Fecha del evento tal como la escribió el DJ, normalmente `AAAA-MM-DD`. Puede venir vacío `""`. |
| `venue` | texto | Lugar del evento. Puede venir vacío. |
| `event_type` | texto | Código interno del tipo de evento. Valores actuales: `cumple_infantil`, `cumple_adolescente`, `quince`, `carrete_juvenil`, `urbana_adultos`, `matrimonio`, `cumple_adulto`, `empresa`, `familiar`, `despedida`, `otro`. Pueden aparecer nuevos. |
| `event_type_label` | texto | El mismo tipo en palabras para mostrar (ej. `"15 años"`). |

## `blocks[]`

Cada bloque es una parte de la noche (ej. "Recepción", "Baile fuerte", "Cierre").

| Campo | Tipo | Qué es |
|---|---|---|
| `index` | número entero | Posición del bloque, empieza en `0`. Es lo que usan los temas en `block_index`. |
| `name` | texto | Nombre del bloque. |
| `start` | texto | Hora de inicio `"HH:MM"` (ej. `"22:30"`). Puede venir vacío. |
| `minutes` | número entero | Duración planificada en minutos. |

Idea para CrateDJ: un bloque puede convertirse en una subcarpeta/crate dentro del crate del evento.

## `tracks[]`

| Campo | Tipo | Qué es |
|---|---|---|
| `position` | número entero | Posición del tema en el set completo, empieza en `1`. |
| `block_index` | número entero | A qué bloque pertenece (`blocks[].index`). Si `blocks` viene vacía, ignorarlo. |
| `artist` | texto | Artista tal como lo informó la fuente (puede incluir "feat."). |
| `title` | texto | Título del tema. |
| `genre_slug` | texto | Código del género principal en la taxonomía de SETMAKER (ej. `"reggaeton_actual"`, `"cumbia"`). `"otro"` si no se sabe. |
| `genre_name` | texto | Nombre del género para mostrar (ej. `"Reggaetón actual"`). |
| `year` | número entero o `null` | Año de lanzamiento. |
| `bpm` | número o `null` | BPM aproximado (puede tener un decimal). |
| `energy` | número entero o `null` | Energía de 1 (tranquilo) a 10 (máxima). |
| `status` | texto | Estado frente a la biblioteca del DJ: `"tengo"` (está el archivo), `"otra_version"` (hay un archivo pero de otra versión: remix, intro, etc.), `"falta"` (no lo tiene o no se revisó). |
| `local_path` | texto o `null` | Ruta completa del archivo que SETMAKER recomienda usar (ej. `"E:\\Musica\\Reggaeton\\Tema.mp3"`). `null` si el estado es `"falta"`. |
| `all_local_paths` | lista de textos | Todas las rutas de archivos encontrados para ese tema (la primera es `local_path`). Lista vacía si no hay. Sirve para que CrateDJ ofrezca elegir versión. |
| `isrc` | texto o `null` | Código ISRC (identificador internacional de la grabación), útil para emparejar. |
| `deezer_id` | número entero o `null` | ID del tema en Deezer. |
| `preview_url` | texto o `null` | URL de un adelanto de audio de ~30 s (puede caducar). |
| `link` | texto o `null` | Link a la página del tema (Deezer, YouTube, etc.). |
| `sources` | lista de textos | De qué fuentes salió el tema (ej. `["deezer", "lastfm", "apple"]`). |
| `reasons` | lista de textos | Por qué SETMAKER lo puso en el set, en palabras simples (ej. `"Top 10 en Chile"`). |

### Notas sobre rutas

- Las rutas son de **Windows** y absolutas (letra de unidad incluida). Si el disco portátil se
  conecta con otra letra en otro PC, CrateDJ puede intentar cambiar solo la letra de unidad y
  comprobar si el archivo existe.
- En JSON las barras invertidas vienen escapadas (`\\`); cualquier lector JSON las convierte bien.

## Ejemplo mínimo

```json
{
  "format": "setmaker-crate",
  "version": 1,
  "generated_at": "2026-10-22T18:30:00-03:00",
  "app_version": "0.1.0",
  "event": {
    "name": "Cumple Sofía",
    "date": "2026-10-25",
    "venue": "Aguas del Monte",
    "event_type": "quince",
    "event_type_label": "15 años"
  },
  "blocks": [
    {"index": 0, "name": "Recepción", "start": "21:00", "minutes": 60},
    {"index": 1, "name": "Baile", "start": "22:00", "minutes": 120}
  ],
  "tracks": [
    {
      "position": 1,
      "block_index": 0,
      "artist": "Bad Bunny",
      "title": "Tití Me Preguntó",
      "genre_slug": "reggaeton_actual",
      "genre_name": "Reggaetón actual",
      "year": 2022,
      "bpm": 107.0,
      "energy": 8,
      "status": "tengo",
      "local_path": "E:\\Musica\\Reggaeton\\Bad Bunny - Titi Me Pregunto (Intro).mp3",
      "all_local_paths": ["E:\\Musica\\Reggaeton\\Bad Bunny - Titi Me Pregunto (Intro).mp3"],
      "isrc": "QM6MZ2214828",
      "deezer_id": 1786563767,
      "preview_url": null,
      "link": "https://www.deezer.com/track/1786563767",
      "sources": ["deezer", "apple"],
      "reasons": ["Top en Chile", "Clásico de fiestas"]
    }
  ]
}
```
