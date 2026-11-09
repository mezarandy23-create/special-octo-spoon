// Punto de entrada: npm start

import { loadEnv, loadConfig, settings, makeLogger } from './config.js';
import { Store } from './store.js';
import { InvoiceAI } from './ai.js';
import { DraftMailbox, explainMailError } from './email.js';
import { InvoiceBot } from './bot.js';
import { startWhatsApp } from './transports/whatsapp.js';
import { startTelegram } from './transports/telegram.js';

const log = makeLogger();

async function main() {
  loadEnv();
  const config = loadConfig();
  const s = settings();

  log.info('🧾 Bot de invoices iniciando...');
  const store = new Store(s.dataDir, { firstNumber: Number(config.factura?.siguienteNumero) || 1 });

  if (!s.anthropicKey) log.warn('Falta ANTHROPIC_API_KEY en .env: el bot no podrá entender mensajes.');
  const ai = s.anthropicKey ? new InvoiceAI({ apiKey: s.anthropicKey, model: s.model, effort: s.effort, fallback: s.fallback, logger: log }) : null;

  const mailbox = new DraftMailbox({ host: s.imapHost, port: s.imapPort, user: s.gmailUser, pass: s.gmailPass, logger: log });
  if (!mailbox.enabled) {
    log.warn('Falta GMAIL_USER / GMAIL_APP_PASSWORD en .env: haré el PDF pero NO el borrador.');
  } else {
    try {
      const { draftsPath } = await mailbox.test();
      log.info(`✅ Correo OK (${s.gmailUser}). Los borradores irán a "${draftsPath}".`);
    } catch (err) {
      log.error(`El correo no funciona: ${explainMailError(err)}`);
    }
  }

  if (!s.accessCode && !s.allowedNumbers.length) {
    log.warn('No pusiste CODIGO_ACCESO ni NUMEROS_PERMITIDOS en .env: nadie podrá usar el bot.');
  }

  const bot = new InvoiceBot({ config, store, ai, mailbox, logger: log, accessCode: s.accessCode, allowedNumbers: s.allowedNumbers });
  log.info(`🔢 Próximo invoice: #${store.peekNextNumber()}`);

  if (s.telegramToken) {
    await startTelegram({ bot, token: s.telegramToken, log }).catch((err) => log.error(`Telegram no arrancó: ${err.message}`));
  }
  if (s.whatsapp) {
    await startWhatsApp({ bot, dataDir: s.dataDir, log, pairingNumber: s.pairingNumber, baileysLogLevel: s.baileysLogLevel });
  }
  if (!s.whatsapp && !s.telegramToken) log.warn('WhatsApp está apagado y no hay TELEGRAM_BOT_TOKEN: no hay por dónde recibir mensajes.');
}

main().catch((err) => {
  log.error(err.message);
  process.exit(1);
});
