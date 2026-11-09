// Conexión con WhatsApp usando Baileys (open source, se conecta como "WhatsApp Web").
// La primera vez muestra un código QR: se escanea desde el teléfono del número del bot
// en WhatsApp > Dispositivos vinculados > Vincular un dispositivo.

import fs from 'node:fs';
import path from 'node:path';
import pino from 'pino';
import QRCode from 'qrcode';
import makeWASocket, {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  isJidBroadcast,
  isJidGroup,
  isJidNewsletter,
  isPnUser,
  jidNormalizedUser,
  normalizeMessageContent,
  useMultiFileAuthState,
} from 'baileys';

const MAX_AGE_SECONDS = 24 * 60 * 60; // ignora mensajes de hace más de 1 día (al reconectar)

export function extract(msg) {
  const content = normalizeMessageContent(msg.message) || {};
  const text = content.conversation
    || content.extendedTextMessage?.text
    || content.imageMessage?.caption
    || content.documentMessage?.caption
    || content.documentWithCaptionMessage?.message?.documentMessage?.caption
    || '';
  const image = content.imageMessage;
  const doc = content.documentMessage || content.documentWithCaptionMessage?.message?.documentMessage;
  let media = null;
  if (image) media = { contentType: image.mimetype || 'image/jpeg', filename: `recibo.${(image.mimetype || 'image/jpeg').split('/')[1].split(';')[0]}` };
  else if (doc) media = { contentType: doc.mimetype || 'application/octet-stream', filename: doc.fileName || 'recibo.pdf' };
  return { text, media, hasAudio: Boolean(content.audioMessage) };
}

/** WhatsApp a veces identifica al contacto por número (@s.whatsapp.net) y a veces por un ID privado (@lid). */
export function chatFromMessage(msg) {
  const alt = msg.key.remoteJidAlt ? jidNormalizedUser(msg.key.remoteJidAlt) : null;
  const main = jidNormalizedUser(msg.key.remoteJid);
  const pn = isPnUser(main) ? main : alt && isPnUser(alt) ? alt : null;
  const key = `wa:${pn || main}`;
  const altKeys = [main, alt].filter(Boolean).map((j) => `wa:${j}`).filter((k) => k !== key);
  const phones = pn ? [pn.split('@')[0].split(':')[0]] : [];
  return { key, altKeys, phones, name: msg.pushName || '' };
}

export async function startWhatsApp({ bot, dataDir, log, pairingNumber = '', baileysLogLevel = 'error' }) {
  const authDir = path.join(dataDir, 'whatsapp-sesion');
  const qrFile = path.join(dataDir, 'whatsapp-qr.png');
  const logger = pino({ level: baileysLogLevel });
  let retries = 0;

  async function connect() {
    let pairingRequested = false;
    const { state, saveCreds } = await useMultiFileAuthState(authDir);
    let version;
    try {
      ({ version } = await fetchLatestBaileysVersion());
    } catch {
      /* si falla, Baileys usa su versión por defecto */
    }

    const sock = makeWASocket({
      auth: state,
      version,
      logger,
      browser: Browsers.macOS('Desktop'),
      markOnlineOnConnect: false, // así el teléfono sigue recibiendo notificaciones
      syncFullHistory: false,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (u) => {
      const { connection, lastDisconnect, qr } = u;
      if (qr) {
        if (pairingNumber && !state.creds.registered && !pairingRequested) {
          pairingRequested = true;
          try {
            const code = await sock.requestPairingCode(pairingNumber.replace(/\D/g, ''));
            log.info(`\n📱 Código para vincular WhatsApp: ${code}\n   En el teléfono del bot: WhatsApp > Dispositivos vinculados > Vincular un dispositivo > "Vincular con número de teléfono" y escribe ese código.\n`);
          } catch (err) {
            log.error('No pude pedir el código de vinculación:', err.message);
          }
        } else if (!pairingNumber) {
          const ascii = await QRCode.toString(qr, { type: 'terminal', small: true });
          await QRCode.toFile(qrFile, qr, { width: 400 }).catch(() => {});
          log.info(`\n📱 Escanea este QR con el WhatsApp del número del bot:\n   WhatsApp > Configuración > Dispositivos vinculados > Vincular un dispositivo\n   (Si el QR se ve mal aquí, abre la imagen: ${qrFile})\n\n${ascii}`);
        }
      }
      if (connection === 'open') {
        retries = 0;
        fs.rmSync(qrFile, { force: true });
        log.info(`✅ WhatsApp conectado como ${sock.user?.id ? jidNormalizedUser(sock.user.id).split('@')[0] : '(desconocido)'}. Esperando mensajes...`);
      }
      if (connection === 'close') {
        const code = lastDisconnect?.error?.output?.statusCode;
        if (code === DisconnectReason.loggedOut) {
          log.warn('⚠️ WhatsApp cerró la sesión (desvinculaste el dispositivo o expiró). Borro la sesión; reinicia el bot y escanea el QR otra vez.');
          fs.rmSync(authDir, { recursive: true, force: true });
          process.exit(1);
        }
        if (code === DisconnectReason.connectionReplaced) {
          log.error('⚠️ Hay OTRA copia del bot abierta con la misma sesión de WhatsApp (en otra ventana o computadora). Cierra una y vuelve a iniciar.');
          process.exit(1);
        }
        if (code === DisconnectReason.forbidden) {
          log.error('⛔ WhatsApp rechazó la conexión (403). Puede que el número esté restringido. Revisa el teléfono del bot; mientras tanto puedes usar Telegram (ver README).');
        }
        retries++;
        const wait = Math.min(60, 2 ** Math.min(retries, 6));
        if (code !== DisconnectReason.restartRequired) log.warn(`WhatsApp se desconectó (código ${code ?? '?'}). Reintento en ${wait}s...`);
        setTimeout(() => connect().catch((e) => log.error('Error reconectando WhatsApp:', e)), code === DisconnectReason.restartRequired ? 0 : wait * 1000);
      }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify') return;
      for (const msg of messages) {
        try {
          await onMessage(sock, msg);
        } catch (err) {
          log.error('Error con un mensaje de WhatsApp:', err);
        }
      }
    });
  }

  async function onMessage(sock, msg) {
    const jid = msg.key?.remoteJid;
    if (!jid || msg.key.fromMe || !msg.message) return;
    if (isJidGroup(jid) || isJidBroadcast(jid) || isJidNewsletter(jid)) return;
    const ts = Number(msg.messageTimestamp || 0);
    if (ts && Date.now() / 1000 - ts > MAX_AGE_SECONDS) return;

    const { text, media, hasAudio } = extract(msg);
    const attachments = [];
    if (media && /^image\/|^application\/pdf/.test(media.contentType)) {
      const content = await downloadMediaMessage(msg, 'buffer', {}, { logger, reuploadRequest: sock.updateMediaMessage });
      attachments.push({ ...media, content });
    }

    const chat = chatFromMessage(msg);
    if (hasAudio && !text && bot.isAuthorized(chat)) {
      await sock.sendMessage(jid, { text: '🎤 Todavía no entiendo notas de voz. Usa el micrófono del teclado para dictar el mensaje como texto 🙂' });
      return;
    }
    if (!text && !attachments.length) return;

    // "escribiendo..." mientras trabaja
    const typing = setInterval(() => sock.sendPresenceUpdate('composing', jid).catch(() => {}), 8000);
    sock.sendPresenceUpdate('composing', jid).catch(() => {});
    let replies;
    try {
      replies = await bot.handle(chat, { id: `wa:${msg.key.id}`, text, attachments });
    } finally {
      clearInterval(typing);
      sock.sendPresenceUpdate('paused', jid).catch(() => {});
    }
    for (const r of replies) {
      if (r.document) {
        await sock.sendMessage(jid, { document: r.document, mimetype: r.mimetype, fileName: r.filename, caption: r.caption });
      } else if (r.text) {
        await sock.sendMessage(jid, { text: r.text });
      }
    }
  }

  await connect();
}
