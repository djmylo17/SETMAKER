# SETMAKER

App de escritorio para Windows que arma sets de DJ **antes del evento**, según el tipo de fiesta y la edad del público, con tendencias reales. Te dice qué temas ya tienes en tu biblioteca y cuáles te faltan.

Hecha para **Level Up Producciones** (Gran Concepción, Chile).

---

## Descargar y usar (sin instalar nada)

1. Ve a **Releases** (columna derecha de esta página) y descarga `SETMAKER-windows.zip` de la versión más nueva.
2. Descomprime el zip donde quieras, por ejemplo en tu disco portátil: `E:\SETMAKER\`.
3. Abre `SETMAKER.exe`.
   - La primera vez Windows puede mostrar **"Windows protegió su PC"**: pulsa **Más información → Ejecutar de todas formas**. Aparece porque la app no tiene firma comercial.
4. Todos tus datos quedan en la carpeta `SETMAKER\data\`. Si conectas el disco en otro PC, todo sigue ahí.

### Qué hay en `data\`

| Archivo | Qué es |
|---|---|
| `setmaker.db` | Base de datos (eventos, caché, biblioteca, aprendizaje) |
| `config.json` | Tus ajustes (rutas, país, etc.) |
| `keys.enc` | Claves de API, **cifradas** |
| `backups\` | Respaldos que crees desde Ajustes |
| `exports\` | Listas exportadas |
| `logs\setmaker.log` | Registro de errores (útil si algo falla) |

> **Nunca borres ni compartas `data\`**, y no lo subas a GitHub: ahí están tus claves. El archivo `.gitignore` ya lo excluye del repositorio.

---

## Actualizar a una versión nueva

Por ahora es manual. El botón automático llega en la Fase 6.

1. Crea un respaldo: **Ajustes → Crear respaldo ahora**.
2. Cierra SETMAKER.
3. Descarga el zip nuevo desde **Releases**.
4. Descomprímelo y **reemplaza todo menos la carpeta `data\`**.

---

## Publicar una versión nueva (para Milo)

Claude hace casi todo esto, pero así funciona:

1. Claude sube el código a la rama `main`. GitHub ejecuta las pruebas y arma el zip en Windows automáticamente (pestaña **Actions**, unos 5–8 minutos).
2. Si el número de versión de `app/__init__.py` (`__version__`) es nuevo, GitHub crea solo la **Release** `vX.Y.Z` con `SETMAKER-windows.zip` adjunto.
3. Si la versión no cambió, el zip igual queda descargable desde **Actions** (por 30 días), pero no se crea una Release nueva.

---

## Para desarrollo (no necesario para usar la app)

Requisitos: Python 3.12 en Windows.

```bat
pip install -r requirements-dev.txt
python run.py                         :: abrir la app desde el código
python -m pytest -q                   :: correr las pruebas
pyinstaller setmaker.spec --noconfirm :: armar la carpeta portable en dist\SETMAKER
```

### Estructura

```
app/
  main.py            arranque (logs, contraseña maestra, restauración pendiente)
  paths.py           rutas portables (data/ junto al .exe)
  config.py          ajustes en config.json
  backup.py          respaldo y restauración
  net.py             conexiones con mensajes de error en español
  db/                SQLite con migraciones numeradas
  security/          bóveda de claves cifrada
  sources/           fuentes externas (Deezer, Apple, Last.fm, YouTube, Spotify, Gemini)
  library/           VirtualDJ y escaneo de carpetas
  ui/                interfaz (PySide6), tema oscuro
tests/               pruebas automáticas
docs/                documentación (formato de intercambio con CrateDJ, etc.)
```

### Fases

1. **Base** ✅ — app portable, SQLite, ajustes, claves, empaquetado
2. Perfiles de evento, plantillas y taxonomía de géneros
3. Fuentes y motor de generación (con pruebas obligatorias anti-errores)
4. Biblioteca VirtualDJ y coincidencias
5. Salidas: Spotify, links de búsqueda, Excel/CSV/TXT, JSON para CrateDJ
6. Aprendizaje, actualizador automático y pulido

### Notas sobre las APIs (verificado en octubre 2026)

- **Spotify** (cambios de febrero 2026): solo se usa para **crear playlists** en tu cuenta. La API ya no entrega el contenido de playlists ajenas, ni recomendaciones, ni popularidad. Para usar una playlist curada de Spotify como fuente, cópiala a una playlist propia.
- **Gemini**: el modelo no está fijo en el código. La app consulta los modelos disponibles con tu clave y elige el Flash estable más nuevo.
- **Last.fm**: gratis para uso no comercial.
- **Apple Music RSS**: solo "más escuchados" por país. Se usa como señal de tendencia, nunca para decidir el género.
- **Deezer**: catálogo, charts y previews de 30 s sin clave.
