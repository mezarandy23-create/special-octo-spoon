// Arma el correo (igual al que mandan normalmente, en inglés y español) y lo guarda como BORRADOR.
// Nunca envía nada: el borrador se crea por IMAP en la carpeta "Borradores" de Gmail.

import { ImapFlow } from 'imapflow';
import MailComposer from 'nodemailer/lib/mail-composer';
import crypto from 'node:crypto';
import { enRange, esRange, money } from './format.js';

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

function joinList(items, and) {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} ${and} ${items[items.length - 1]}`;
}

export function pdfFileName(inv) {
  return `Invoice_${inv.number}.pdf`;
}

/** Texto del correo (asunto, HTML y texto plano). */
export function buildEmailContent(inv, config, { receiptsCount = 0 } = {}) {
  const e = config.empresa || {};
  const company = e.nombreCorto || e.nombre || '';
  const project = inv.project.nameForEmail;
  const weekEn = enRange(inv.firstDay, inv.lastDay, '–');
  const weekEs = esRange(inv.firstDay, inv.lastDay);
  const total = money(inv.totalCents);

  const kinds = inv.lines.map((l) => l.key);
  const en = [];
  const es = [];
  if (kinds.includes('gas')) { en.push('gas'); es.push('gasolina'); }
  if (kinds.includes('supplies')) { en.push('cleaning supplies'); es.push('materiales de limpieza'); }

  const receiptsEn = receiptsCount
    ? (en.length ? `Receipts for ${joinList(en, 'and')} are also attached for your reference. ` : 'Receipts are also attached for your reference. ')
    : '';
  const receiptsEs = receiptsCount
    ? (es.length ? `Adjunto también encontrarán los recibos de ${joinList(es, 'y')} para su referencia. ` : 'Adjunto también encontrarán los recibos para su referencia. ')
    : '';

  const template = config.correo?.asunto || 'Invoice {numero} - {empresa} - {proyecto} ({semana})';
  const subject = template
    .replaceAll('{numero}', inv.number)
    .replaceAll('{empresa}', company)
    .replaceAll('{proyecto}', project)
    .replaceAll('{semana}', weekEn)
    .replaceAll('{total}', total);

  const p = (html) => `<p style="margin:0 0 14px 0">${html}</p>`;
  const html = `<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.45;color:#222">
${p('To Whom It May Concern / A Quien Corresponda,')}
${p(`I hope this message finds you well. Please find attached Invoice <b>${esc(inv.number)}</b> from ${esc(company)} for services rendered at ${esc(project)} during the week of ${esc(weekEn)}.`)}
${p(`<b>Total Amount Due: ${total}</b>`)}
${p(`${esc(receiptsEn)}Please let us know if any additional documentation or information is required to process this invoice.`)}
<hr style="border:none;border-top:1px solid #999;margin:18px 0">
${p(`Esperamos que este mensaje les encuentre bien. Adjunto encontrarán la factura <b>${esc(inv.number)}</b> de ${esc(company)} por los servicios prestados en ${esc(project)} durante la semana ${esc(weekEs)}.`)}
${p(`<b>Total a cobrar: ${total}</b>`)}
${p(`${esc(receiptsEs)}Por favor, háganos saber si requieren documentación o información adicional para procesar esta factura.`)}
${p('Best regards / Saludos cordiales,')}
<p style="margin:0"><b>${esc(company)}</b><br>${esc(e.firma || 'Billing Department')}<br>${esc(e.telefono || '')}<br><a href="mailto:${esc(e.email || '')}">${esc(e.email || '')}</a></p>
</div>`;

  const text = [
    'To Whom It May Concern / A Quien Corresponda,',
    '',
    `I hope this message finds you well. Please find attached Invoice ${inv.number} from ${company} for services rendered at ${project} during the week of ${weekEn}.`,
    '',
    `Total Amount Due: ${total}`,
    '',
    `${receiptsEn}Please let us know if any additional documentation or information is required to process this invoice.`,
    '',
    '______________________________',
    '',
    `Esperamos que este mensaje les encuentre bien. Adjunto encontrarán la factura ${inv.number} de ${company} por los servicios prestados en ${project} durante la semana ${weekEs}.`,
    '',
    `Total a cobrar: ${total}`,
    '',
    `${receiptsEs}Por favor, háganos saber si requieren documentación o información adicional para procesar esta factura.`,
    '',
    'Best regards / Saludos cordiales,',
    '',
    company,
    e.firma || 'Billing Department',
    e.telefono || '',
    e.email || '',
  ].join('\n');

  return { subject, html, text };
}

/** Arma el correo completo (formato .eml) con el PDF y los recibos adjuntos. */
export async function composeRaw({ from, to, cc, subject, html, text, attachments, messageId }) {
  const mail = new MailComposer({
    from,
    to: to?.length ? to : undefined,
    cc: cc?.length ? cc : undefined,
    subject,
    html,
    text,
    messageId,
    date: new Date(),
    attachments: attachments.map((a) => ({ filename: a.filename, content: a.content, contentType: a.contentType })),
  });
  return mail.compile().build();
}

export function newMessageId(fromEmail) {
  const domain = String(fromEmail || 'invoice.local').split('@')[1] || 'invoice.local';
  return `<invoice-${crypto.randomUUID()}@${domain}>`;
}

/** Explica en español por qué falló el correo. */
export function explainMailError(err) {
  if (err?.authenticationFailed) {
    return 'Gmail rechazó el usuario o la contraseña de aplicación. Revisa GMAIL_USER y GMAIL_APP_PASSWORD en el archivo .env (la contraseña de aplicación son 16 letras; necesitas tener activada la verificación en 2 pasos).';
  }
  if (err?.code === 'ENOTFOUND' || err?.code === 'EAI_AGAIN') return 'No hay internet o el servidor IMAP no existe (revisa IMAP_HOST).';
  if (err?.code === 'ETIMEDOUT' || err?.code === 'ECONNREFUSED') return 'No pude conectarme al servidor de correo (¿firewall o sin internet?).';
  return err?.responseText || err?.message || String(err);
}

/** Borradores por IMAP (Gmail, iCloud, etc.). */
export class DraftMailbox {
  constructor({ host = 'imap.gmail.com', port = 993, user, pass, logger } = {}) {
    this.opts = { host, port: Number(port) || 993, secure: true, auth: { user, pass: String(pass || '').replace(/\s+/g, '') } };
    this.user = user;
    this.logger = logger;
  }

  get enabled() {
    return Boolean(this.opts.auth.user && this.opts.auth.pass);
  }

  async withClient(fn) {
    const client = new ImapFlow({ ...this.opts, logger: false });
    client.on('error', (err) => this.logger?.warn?.(`IMAP: ${err.message}`));
    await client.connect();
    try {
      return await fn(client);
    } finally {
      await client.logout().catch(() => {});
    }
  }

  /** Encuentra la carpeta de borradores sin importar el idioma ("[Gmail]/Drafts", "[Gmail]/Borradores", "Drafts"...). */
  async draftsPath(client) {
    const boxes = await client.list();
    const hit = boxes.find((b) => b.specialUse === '\\Drafts')
      || boxes.find((b) => /(^|\/)(drafts|borradores)$/i.test(b.path));
    if (!hit) throw new Error('No encontré la carpeta de Borradores en el correo.');
    return hit.path;
  }

  async createDraft(raw) {
    return this.withClient(async (client) => {
      const path = await this.draftsPath(client);
      const res = await client.append(path, raw, ['\\Draft', '\\Seen']);
      return { path, uid: res?.uid ?? null };
    });
  }

  /** Borra el borrador que tenga ese Message-ID. Devuelve true si lo encontró. */
  async deleteDraft(messageId) {
    if (!messageId) return false;
    return this.withClient(async (client) => {
      const path = await this.draftsPath(client);
      const lock = await client.getMailboxLock(path);
      try {
        const uids = await client.search({ header: { 'message-id': messageId } }, { uid: true });
        if (!uids || !uids.length) return false;
        await client.messageDelete(uids, { uid: true });
        return true;
      } finally {
        lock.release();
      }
    });
  }

  async test() {
    return this.withClient(async (client) => ({ draftsPath: await this.draftsPath(client) }));
  }
}
