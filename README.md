# 🧾 Bot de Invoices por WhatsApp

Tu jefa le escribe al bot por WhatsApp algo como:

> 10 horas el martes, 8 el jueves y 4 el viernes. 3 personas martes y jueves y 7 personas el viernes

y el bot:

1. **Entiende el mensaje** con IA (Claude). La IA solo lee; **las cuentas las hace el programa**, así que el total siempre cuadra.
2. **Hace el PDF** con el mismo diseño de tus invoices (logo, tabla de horas, resumen, notas).
3. **Deja el correo como BORRADOR en Gmail** (`maaicleaning@gmail.com`), con el mismo texto bilingüe de siempre, el PDF adjunto y los recibos si se los mandaron.
4. **Le contesta por WhatsApp** con un resumen y el PDF para que lo revise.

**Nunca envía nada por su cuenta.** Ella abre Gmail → Borradores, revisa y le da *Enviar*.

```
 WhatsApp de tu jefa ──► Bot (en tu computadora) ──► IA entiende el mensaje
                                │
                                ├─► el programa calcula y hace el PDF
                                ├─► borrador en Gmail (con PDF y recibos)
                                └─► responde en WhatsApp: resumen + PDF
```

Todo es **open source** y gratis; lo único que se paga es la IA (unos **3–5 centavos por invoice**).

---

## ✅ Lo que necesitas (junta esto primero)

| # | Qué | Para qué | Costo |
|---|-----|----------|-------|
| 1 | Una computadora que se quede prendida (Windows, Mac o un servidor) | Ahí corre el bot | $0 (o ~$5/mes un servidor) |
| 2 | **Node.js 22 o más nuevo** | Para correr el programa | Gratis |
| 3 | **Un número de WhatsApp para el bot** (recomendado: uno aparte, ver abajo) | Es "el contacto" al que tu jefa le escribe | $0–15/mes |
| 4 | **Clave de Claude (Anthropic)** con saldo | La IA que entiende los mensajes | $5 alcanzan para cientos de invoices |
| 5 | **Contraseña de aplicación** de `maaicleaning@gmail.com` | Para guardar los borradores | Gratis |

> **¿Por qué un número aparte?** El bot se conecta como si fuera "WhatsApp Web" de ese número. Si usas el número personal de alguien, el bot vería todos sus chats. Opciones: un chip prepago barato, una eSIM, o **el teléfono fijo del negocio** (WhatsApp Business deja verificar un número fijo con llamada). Con ese número instalas WhatsApp (o WhatsApp Business) en cualquier teléfono viejo.

---

## 🚀 Instalación paso a paso (~45 minutos)

### Paso 1 — Instala Node.js
Entra a <https://nodejs.org>, descarga la versión **LTS** e instálala (siguiente, siguiente, finalizar).
Para comprobar, abre una terminal (**Windows:** busca "PowerShell"; **Mac:** busca "Terminal") y escribe:
```
node --version
```
Debe salir `v22...` o más alto.

### Paso 2 — Descarga el bot
Descarga el ZIP de este repositorio (botón verde **Code → Download ZIP**, en la rama donde está el código), descomprímelo en una carpeta fácil (ej. `Documentos/bot-invoices`) y en la terminal entra a esa carpeta:
```
cd Documentos/bot-invoices
npm install
```
(`npm install` descarga las librerías; tarda 1–2 minutos.)

### Paso 3 — Clave de la IA (Anthropic)
1. Entra a <https://console.anthropic.com> y crea una cuenta.
2. **Billing** → agrega saldo (con $5 sobra para empezar).
3. **API Keys** → *Create Key* → copia la clave (empieza con `sk-ant-...`). Solo se muestra una vez.

### Paso 4 — Contraseña de aplicación de Gmail
Con la cuenta **maaicleaning@gmail.com**:
1. Ve a <https://myaccount.google.com/security> y activa **Verificación en 2 pasos** (si no está activa).
2. Ve a <https://myaccount.google.com/apppasswords>, escribe un nombre (ej. "Bot invoices") y dale **Crear**.
3. Copia las **16 letras** que te da. Esa es la contraseña que usa el bot (no es tu contraseña normal y la puedes borrar cuando quieras).

### Paso 5 — Llena tus datos
En la carpeta del bot:

**Windows (PowerShell):**
```
copy .env.example .env
copy config.example.json config.json
notepad .env
```
**Mac:**
```
cp .env.example .env
cp config.example.json config.json
open -e .env
```

En **`.env`** llena:
```
ANTHROPIC_API_KEY=sk-ant-...tu clave...
GMAIL_USER=maaicleaning@gmail.com
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
CODIGO_ACCESO=inventa-un-codigo
```

En **`config.json`** pon los datos del proyecto (nombre, dirección, PO, supervisor) y sobre todo los **correos a los que va el invoice** (`"para"`). Si tienes varios proyectos, agrega uno por cada uno; el primero es el predeterminado. `"siguienteNumero": 51` es el número del próximo invoice.

> Los archivos `.env` y `config.json` **no se suben a GitHub** (están en `.gitignore`), así tus contraseñas y los datos de tus clientes quedan solo en tu computadora.

### Paso 6 — Prueba antes de conectar WhatsApp
```
npm run probar-correo
```
Debe decir ✅ y dejar un borrador de prueba en Gmail. Bórralo.

```
npm run probar -- "10 horas el martes, 8 el jueves y 4 el viernes. 3 personas martes y jueves y 7 personas el viernes"
```
Te muestra lo que entendió la IA, el resumen y guarda el PDF en la carpeta `salida/`. Ábrelo y revisa que se vea bien.
Si agregas `--borrador` al final, también crea el borrador en Gmail. (Las pruebas **no** gastan número de invoice.)

### Paso 7 — Conecta WhatsApp
```
npm start
```
Aparece un **código QR**. En el teléfono del **número del bot**: WhatsApp → **Configuración → Dispositivos vinculados → Vincular un dispositivo** → escanea el QR.
Cuando diga `✅ WhatsApp conectado`, ya está.

### Paso 8 — Activa a tu jefa
Desde el WhatsApp de tu jefa, mándale **una sola vez** al número del bot:
```
activar inventa-un-codigo
```
(el mismo código que pusiste en `CODIGO_ACCESO`). El bot contesta "✅ Listo". El bot **ignora** a cualquiera que no se haya activado.

### Paso 9 — Déjalo corriendo
- La ventana de la terminal debe quedar **abierta** y la computadora **sin suspenderse**:
  - **Windows:** Configuración → Sistema → Energía → Suspender: **Nunca**.
  - **Mac:** corre `caffeinate -i npm start` en lugar de `npm start`.
- Si apagas la computadora, al prenderla vuelve a correr `npm start` (ya no pide QR).
- *(Opcional, Mac/Linux/servidor)* para que arranque solo: `npm install -g pm2`, luego `pm2 start src/index.js --name invoices`, `pm2 save` y `pm2 startup`.

---

## 💬 Cómo lo usa tu jefa (mándale esto)

**Pedir un invoice** (como le salga, el bot entiende):
- `10 horas el martes, 8 el jueves y 4 el viernes. 3 personas martes y jueves y 7 el viernes`
- `lunes a viernes 6 personas 10 horas, manejo 4 horas de ida el lunes y 4 de regreso el viernes, gasolina 137, materiales 161.21, comida 600`
- `semana del 2 de noviembre, main street plaza, 5 personas 9 horas lunes a jueves`

**Recibos:** manda las fotos (o PDF) de los recibos antes o después; se adjuntan al correo.
**Corregir:** `el jueves fueron 9 horas`, `quita la comida`, `es de la semana pasada`, `agrégale los recibos`.
**Otros:** `borra el último` · `el siguiente invoice es el 60` · `estado` · `ayuda`

**Tip:** para no escribir, que use el **micrófono del teclado** (dictado). Las notas de voz todavía no se entienden.

El bot responde algo así:
```
✅ INV-2026-051 listo — borrador guardado en Gmail
📍 MAIN STREET PLAZA · PO #12345
📅 Semana 2–8 nov 2026

👷 Horas de trabajo
• Mar 3 nov: 3 personas × 10 h = 30 h
• Jue 5 nov: 3 personas × 8 h = 24 h
• Vie 6 nov: 7 personas × 4 h = 28 h
Total: 82 h × $20.00 = $1,640.00

💵 TOTAL: $1,640.00
✉️ Para: pagos@cliente.com
Revísalo en Gmail → Borradores y dale Enviar.
```
y le manda el PDF.

**¿Qué semana usa?** Si no dice fecha, usa la semana más reciente en la que esos días ya pasaron (ej. si escribe el lunes "martes, jueves y viernes", toma la semana pasada). El resumen siempre muestra las fechas; si está mal, basta con decir "es de la semana del 26 de octubre".

---

## 🧯 Trabas comunes y cómo resolverlas

| Problema | Solución |
|---|---|
| Windows: `npm : ... la ejecución de scripts está deshabilitada` | Usa la ventana **"Símbolo del sistema" (cmd)** en vez de PowerShell, o escribe `npm.cmd` en lugar de `npm`. |
| No aparece "Contraseñas de aplicación" en Google | Primero activa la **Verificación en 2 pasos**. Si es una cuenta de Google Workspace, el administrador puede tenerlo bloqueado. |
| `Gmail rechazó el usuario o la contraseña de aplicación` | Crea una contraseña de aplicación nueva y pégala en `GMAIL_APP_PASSWORD`. Revisa que `GMAIL_USER` sea el correo correcto. |
| El QR se ve deforme en la terminal | Abre la imagen `data/whatsapp-qr.png`, o en Windows usa "Terminal de Windows". El QR cambia cada ~20 s: escanea el más nuevo. |
| No puedo escanear (el bot está en un servidor sin pantalla) | Pon el número del bot en `WHATSAPP_NUMERO_BOT=17705551234` y reinicia: te da un **código de 8 letras** para *Vincular con número de teléfono*. |
| El bot no contesta | 1) ¿La terminal sigue abierta y la compu despierta? 2) ¿Tu jefa mandó `activar ...`? La terminal muestra "Mensaje ignorado de un chat no autorizado" si no. 3) Escríbele `estado`. |
| `WhatsApp cerró la sesión` | Se desvinculó el dispositivo. Corre `npm start` y escanea el QR otra vez. **El teléfono del bot debe tener internet al menos una vez cada 14 días** o WhatsApp desconecta los dispositivos vinculados. |
| `Hay OTRA copia del bot abierta` | Cierra la otra ventana/computadora donde lo tengas corriendo. Solo debe haber una. |
| `credit balance is too low` | Recarga saldo en console.anthropic.com → Billing. |
| El borrador sale sin destinatarios | Llena `"para"` del proyecto en `config.json` y reinicia el bot. |
| El número de invoice no es el que sigue | Escríbele al bot `el siguiente invoice es el 60`, o cambia `siguienteNumero` (solo funciona la primera vez; después manda el que está en `data/estado.json`). |
| `config.json tiene un error de formato` | Te faltó una coma o una comilla. Pega el contenido en <https://jsonlint.com> para ver dónde. |
| El borrador no aparece en el celular | Desliza para actualizar en Gmail → Borradores; a veces tarda unos segundos. |
| Cambié `.env` o `config.json` y no hace caso | Los cambios se leen al iniciar: cierra (Ctrl+C) y vuelve a correr `npm start`. |

### ⚠️ Sobre WhatsApp (léelo)
Este bot usa **Baileys**, una librería open source que se conecta como "WhatsApp Web". Funciona muy bien y es lo más fácil para tenerlo hoy, **pero no es la API oficial de Meta**: WhatsApp puede restringir números que usan automatización, sobre todo si mandan mensajes masivos. Para un bot que solo le contesta a tu jefa unas veces por semana el riesgo es bajo, pero por eso:
- usa **un número aparte**, nunca el WhatsApp principal del negocio;
- no lo uses para mandar mensajes a clientes ni a mucha gente.

Si algún día WhatsApp da problemas, cambia a **Telegram** (abajo) en 5 minutos sin tocar nada más, o migra a la **API oficial de WhatsApp (Cloud API)** de Meta (requiere cuenta de Meta Business, verificar el número y un servidor con dirección pública).

---

## ✈️ Plan B: Telegram (oficial, 5 minutos, sin riesgo)
1. En Telegram busca **@BotFather**, escríbele `/newbot`, ponle nombre y te da un **token**.
2. Pégalo en `.env`: `TELEGRAM_BOT_TOKEN=123456:ABC...` (si no quieres WhatsApp, pon `WHATSAPP=no`).
3. `npm start`. Tu jefa busca tu bot en Telegram, le da *Iniciar* y manda `activar tu-codigo`.

Funciona igual (mensajes, recibos, correcciones). Pueden estar los dos prendidos al mismo tiempo.

---

## 🤔 ¿Y otras opciones open source?
- **OpenClaw** (agente de IA general que se maneja por WhatsApp/Telegram): muy potente, pero le das acceso a toda tu computadora y la IA haría las cuentas del dinero. Para invoices es mejor algo cerrado y exacto como esto.
- **n8n** (automatizaciones con cajitas): sirve, pero su WhatsApp necesita la API oficial de Meta y el PDF con tu diseño hay que armarlo aparte.
- **Este bot**: hace una sola cosa, la hace exacta, con tu diseño, y nunca envía nada sin que ustedes lo revisen.

---

## 🔒 Seguridad
- Solo contesta a chats activados con tu `CODIGO_ACCESO` (o a `NUMEROS_PERMITIDOS`).
- Solo **crea borradores**; no puede enviar correos.
- La carpeta `data/` guarda la sesión de WhatsApp (es como tener ese WhatsApp abierto), el contador de invoices y una copia de cada PDF y recibo en `data/facturas/`. No la compartas.
- Si crees que alguien vio tus claves: borra la contraseña de aplicación en Google y la clave en console.anthropic.com, y crea nuevas.

---

## 🛠️ Para quien le sabe (detalles técnicos)
- `src/ai.js` — una sola llamada a Claude (`claude-opus-5-5`, salida JSON con esquema). Activa el respaldo automático de Anthropic (`fallbacks: "default"`): si el modelo rechaza un mensaje por error, la API reintenta con otro modelo. Se apaga con `CLAUDE_FALLBACK=off`. Para gastar menos puedes poner `CLAUDE_MODEL=claude-sonnet-5-5` o `CLAUDE_EFFORT=low`.
- `src/invoice.js` — todas las cuentas (en centavos), semana, filas de trabajadores, notas.
- `src/pdf.js` — el PDF (PDFKit) con las mismas medidas, colores y fuentes del invoice original. Si hay muchas personas, achica filas o pasa el resumen a una segunda hoja.
- `src/email.js` — arma el correo y lo guarda en Borradores por IMAP (sirve también con iCloud: `IMAP_HOST=imap.mail.me.com`).
- `src/bot.js` — la lógica (activación, recibos, crear/corregir/borrar).
- `src/transports/` — WhatsApp (Baileys) y Telegram.
- `npm test` — pruebas (reproduce al centavo el INV-2026-050: $7,058.21).
