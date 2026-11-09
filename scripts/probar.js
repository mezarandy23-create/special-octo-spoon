// Prueba el bot SIN WhatsApp, desde la terminal.
//
//   npm run probar -- "10 horas el martes, 8 el jueves y 4 el viernes; 3 personas martes y jueves y 7 el viernes"
//   npm run probar -- "..." --borrador          (además crea el borrador en Gmail)
//   npm run probar -- --json ejemplos/semana-completa.json --hoy 2026-10-05   (sin IA: usa datos ya hechos)
//
// No gasta número de invoice (usa el siguiente, pero no lo marca como usado).

import fs from 'node:fs';
import path from 'node:path';
import { loadEnv, loadConfig, settings, makeLogger, ROOT } from '../src/config.js';
import { Store } from '../src/store.js';
import { InvoiceAI } from '../src/ai.js';
import { InvoiceBot } from '../src/bot.js';
import { DraftMailbox, buildEmailContent, composeRaw, newMessageId, pdfFileName, explainMailError } from '../src/email.js';
import { normalizeData, buildInvoice } from '../src/invoice.js';
import { renderInvoicePdf } from '../src/pdf.js';
import { todayIn, isISODate } from '../src/format.js';

const log = makeLogger();
function fail(msg) {
  console.error(`❌ ${msg}`);
  process.exit(1);
}
process.on('unhandledRejection', (err) => fail(err?.message || String(err)));
loadEnv();
const config = loadConfig();
const s = settings();

const args = process.argv.slice(2);
const flag = (name) => {
  const i = args.indexOf(name);
  if (i === -1) return null;
  const v = args[i + 1];
  args.splice(i, 2);
  return v;
};
const wantDraft = args.includes('--borrador');
if (wantDraft) args.splice(args.indexOf('--borrador'), 1);
const jsonFile = flag('--json');
const today = flag('--hoy') || todayIn(config.zonaHoraria || 'America/New_York');
if (!isISODate(today)) fail('--hoy debe ser una fecha YYYY-MM-DD');
const text = args.join(' ').trim();

let raw;
if (jsonFile) {
  raw = JSON.parse(fs.readFileSync(path.resolve(jsonFile), 'utf8'));
} else {
  if (!text) {
    console.log('Uso: npm run probar -- "10 horas el martes, 8 el jueves y 4 el viernes; 3 personas martes y jueves y 7 el viernes"');
    process.exit(1);
  }
  if (!s.anthropicKey) fail('Falta ANTHROPIC_API_KEY en el archivo .env');
  const ai = new InvoiceAI({ apiKey: s.anthropicKey, model: s.model, effort: s.effort, fallback: s.fallback, logger: log });
  log.info(`Preguntando a la IA (${s.model})...`);
  const t0 = Date.now();
  raw = await ai.interpret({ text, today, config });
  log.info(`La IA respondió en ${((Date.now() - t0) / 1000).toFixed(1)} s:`);
  console.log(JSON.stringify(raw, null, 2));
  if (raw.accion !== 'crear' && raw.accion !== 'corregir') {
    console.log(`\nLa IA no lo tomó como invoice (accion: ${raw.accion}). Respuesta: ${raw.respuesta}`);
    process.exit(0);
  }
}

const store = new Store(s.dataDir, { firstNumber: Number(config.factura?.siguienteNumero) || 1 });
const { data, warnings } = normalizeData(raw);
const inv = buildInvoice({ data, config, today, number: store.peekNextNumber() });
const pdf = await renderInvoicePdf(inv, config);
const outDir = path.join(ROOT, 'salida');
fs.mkdirSync(outDir, { recursive: true });
const pdfPath = path.join(outDir, pdfFileName(inv));
fs.writeFileSync(pdfPath, pdf);

let draft = { ok: false, note: 'ℹ️ Prueba sin --borrador: no creé el borrador en Gmail.' };
if (wantDraft) {
  const mailbox = new DraftMailbox({ host: s.imapHost, port: s.imapPort, user: s.gmailUser, pass: s.gmailPass });
  if (!mailbox.enabled) fail('Falta GMAIL_USER / GMAIL_APP_PASSWORD en el archivo .env');
  const content = buildEmailContent(inv, config, { receiptsCount: 0 });
  const rawMail = await composeRaw({
    from: { name: config.empresa?.nombreCorto || '', address: s.gmailUser },
    to: inv.project.to,
    cc: inv.project.cc,
    ...content,
    messageId: newMessageId(s.gmailUser),
    attachments: [{ filename: pdfFileName(inv), content: pdf, contentType: 'application/pdf' }],
  });
  try {
    await mailbox.createDraft(rawMail);
    draft = { ok: true };
  } catch (err) {
    draft = { ok: false, error: explainMailError(err) };
  }
}

const fakeBot = new InvoiceBot({ config, store, ai: null, mailbox: null });
console.log('\n' + fakeBot.summaryText(inv, data, { draft, isCorrection: false, receipts: 0, notes: warnings }));
console.log(`\n📄 PDF guardado en: ${pdfPath}`);
console.log('(Esto fue una prueba: el número de invoice NO se marcó como usado.)');
