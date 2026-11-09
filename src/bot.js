// El "cerebro" del bot: recibe un mensaje (de WhatsApp o Telegram) y devuelve las respuestas.
// No sabe nada de WhatsApp: los transportes (src/transports) solo entregan y mandan mensajes.

import fs from 'node:fs';
import path from 'node:path';
import { normalizeData, buildInvoice, dataForCorrections, formatNumber } from './invoice.js';
import { renderInvoicePdf } from './pdf.js';
import { buildEmailContent, composeRaw, newMessageId, pdfFileName, explainMailError } from './email.js';
import { DAY_KEYS, esDayLabel, esRangeShort, hrs, money, todayIn, plural } from './format.js';

const DAY = 24 * 60 * 60 * 1000;
const MIME = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.heic': 'image/heic', '.pdf': 'application/pdf', '.gif': 'image/gif' };

export function helpText(config) {
  const company = config.empresa?.nombreCorto || 'la empresa';
  return [
    `👋 Soy el bot de invoices de ${company}.`,
    '',
    'Mándame las horas como te salga, yo entiendo. Ejemplos:',
    '• "10 horas el martes, 8 el jueves y 4 el viernes. 3 personas martes y jueves y 7 el viernes"',
    '• "lunes a viernes 6 personas 10 horas, manejo 4 h de ida el lunes y 4 de regreso el viernes, gasolina 137, materiales 161.21, comida 600"',
    '',
    'Yo hago el PDF y dejo el correo como *BORRADOR* en Gmail para que lo revises y lo envíes tú. Nunca envío nada solo.',
    '',
    '📎 Mándame fotos o PDF de recibos y los adjunto al correo.',
    '✏️ Correcciones: "el jueves fueron 9 horas", "quita la comida".',
    '🗑️ "borra el último"',
    '🔢 "el siguiente invoice es el 60"',
    'ℹ️ "estado"',
  ].join('\n');
}

export class InvoiceBot {
  constructor({ config, store, ai, mailbox, logger = console, accessCode = '', allowedNumbers = [] }) {
    this.config = config;
    this.store = store;
    this.ai = ai;
    this.mailbox = mailbox;
    this.log = logger;
    this.accessCode = String(accessCode || '').trim().toLowerCase();
    this.allowedNumbers = allowedNumbers.map((n) => String(n).replace(/\D/g, '')).filter(Boolean);
    this.queues = new Map();
  }

  get tz() {
    return this.config.zonaHoraria || 'America/New_York';
  }

  isAuthorized(chat) {
    const keys = [chat.key, ...(chat.altKeys || [])];
    return this.store.isAuthorized(keys) || (chat.phones || []).some((p) => this.allowedNumbers.includes(p));
  }

  /** Procesa los mensajes de un mismo chat uno por uno (para que una corrección no se cruce con el invoice). */
  handle(chat, msg) {
    const all = [chat.key, ...(chat.altKeys || [])];
    const key = this.store.resolveKey(all);
    chat = { ...chat, key, altKeys: all.filter((k) => k !== key) };
    const prev = this.queues.get(chat.key) || Promise.resolve();
    const run = prev.then(() => this.process(chat, msg)).catch((err) => {
      this.log.error(`Error procesando mensaje de ${chat.key}:`, err);
      return [{ text: `❌ Hubo un problema: ${err.message}` }];
    });
    this.queues.set(chat.key, run.then(() => {}, () => {}));
    return run;
  }

  async process(chat, msg) {
    const text = (msg.text || '').trim();
    const attachments = msg.attachments || [];

    // --- Activación con código ---
    const act = text.match(/^activar\s+(\S+)$/i);
    if (act) {
      if (this.accessCode && act[1].toLowerCase() === this.accessCode) {
        this.store.authorize([chat.key, ...(chat.altKeys || [])], chat.name);
        this.log.info(`✅ Chat autorizado: ${chat.key} (${chat.name || 'sin nombre'})`);
        return [{ text: `✅ Listo, ya puedes pedirme invoices.\n\n${helpText(this.config)}` }];
      }
      this.log.warn(`Código de activación incorrecto desde ${chat.key} (${chat.name || ''})`);
      return [];
    }

    if (!this.isAuthorized(chat)) {
      this.log.info(`Mensaje ignorado de un chat no autorizado: ${chat.key} (${chat.name || 'sin nombre'}). Para autorizarlo, desde ese chat escribe: activar <CODIGO_ACCESO>`);
      return [];
    }
    if (msg.id && this.store.alreadyProcessed(msg.id)) return [];

    if (/^(ayuda|help|men[uú]|\?|\/start|\/ayuda)$/i.test(text)) return [{ text: helpText(this.config) }];
    if (/^(estado|status|ping)$/i.test(text)) return [{ text: this.statusText(chat) }];

    // --- Recibos (fotos / PDF) ---
    let saved = 0;
    for (const a of attachments) {
      if (!/^image\/|^application\/pdf$/.test(a.contentType || '')) continue;
      this.store.addPending(chat.key, a);
      saved++;
    }
    if (!text) {
      if (!saved) return [];
      const total = this.store.listPending(chat.key).length;
      const last = this.recentInvoice(chat);
      return [{
        text: `📎 Guardé ${total} ${plural(total, 'recibo', 'recibos')}. Se ${plural(total, 'adjuntará', 'adjuntarán')} al próximo invoice.`
          + (last ? `\nSi ${plural(total, 'es', 'son')} para el ${last.number} que ya hice, escribe: «agrégalos al último».` : ''),
      }];
    }

    // --- IA ---
    if (!this.ai) return [{ text: '❌ Falta configurar ANTHROPIC_API_KEY en el archivo .env.' }];
    const state = this.store.chat(chat.key);
    const previous = this.recentInvoice(chat);
    const pendingQuestion = state.pregunta && Date.now() - state.pregunta.at < 3 * 60 * 60 * 1000 ? state.pregunta : null;
    const result = await this.ai.interpret({
      text,
      today: todayIn(this.tz),
      config: this.config,
      previous,
      pendingReceipts: this.store.listPending(chat.key).length,
      pendingQuestion,
    });
    this.log.info(`IA (${chat.key}): ${result.accion}`);

    switch (result.accion) {
      case 'preguntar': {
        const userText = pendingQuestion ? `${pendingQuestion.userText}\n${text}` : text;
        this.store.updateChat(chat.key, { pregunta: { userText, question: result.respuesta, at: Date.now() } });
        return [{ text: `🤔 ${result.respuesta}` }];
      }
      case 'otro':
        return [{ text: result.respuesta || helpText(this.config) }];
      case 'numero':
        return [{ text: this.setNumber(result.numero_siguiente) }];
      case 'borrar':
        return [{ text: await this.deleteLast(chat) }];
      case 'corregir':
      case 'crear':
        return this.makeInvoice(chat, result, result.accion === 'corregir' ? previous : null);
      default:
        return [{ text: helpText(this.config) }];
    }
  }

  recentInvoice(chat) {
    const u = this.store.chat(chat.key).ultimo;
    return u && Date.now() - new Date(u.createdAt).getTime() < 14 * DAY ? u : null;
  }

  statusText(chat) {
    const today = todayIn(this.tz);
    const next = formatNumber(this.config, this.store.peekNextNumber(), today);
    const pending = this.store.listPending(chat.key).length;
    const last = this.recentInvoice(chat);
    return [
      '✅ Estoy funcionando.',
      `🔢 Próximo invoice: ${next}`,
      `📎 Recibos esperando: ${pending}`,
      last ? `🧾 Último: ${last.number} (${money(last.totalCents)})` : null,
      this.mailbox?.enabled ? `✉️ Borradores en: ${this.mailbox.user}` : '✉️ Correo NO configurado (solo hago el PDF).',
    ].filter(Boolean).join('\n');
  }

  setNumber(n) {
    if (!Number.isInteger(n) || n < 1 || n > 99999) return '🤔 ¿Qué número quieres para el siguiente invoice?';
    this.store.setNextNumber(n);
    return `🔢 Listo, el próximo invoice será ${formatNumber(this.config, n, todayIn(this.tz))}.`;
  }

  async deleteLast(chat) {
    const last = this.recentInvoice(chat);
    if (!last) return 'No tengo un invoice reciente para borrar.';
    let note = '';
    if (this.mailbox?.enabled && last.messageId) {
      try {
        const found = await this.mailbox.deleteDraft(last.messageId);
        note = found ? 'Borré el borrador de Gmail.' : 'El borrador ya no estaba en Gmail (¿ya lo habías enviado o borrado?).';
      } catch (err) {
        note = `No pude borrar el borrador de Gmail: ${explainMailError(err)}. Bórralo a mano.`;
      }
    }
    this.store.rollbackNumber(last.numberInt);
    this.store.updateChat(chat.key, { ultimo: undefined });
    return `🗑️ Cancelé el ${last.number}. ${note}\n🔢 Próximo invoice: ${formatNumber(this.config, this.store.peekNextNumber(), todayIn(this.tz))}`;
  }

  async makeInvoice(chat, result, previous) {
    const { data, warnings } = normalizeData(result);
    if (!data.dias.length) {
      return [{ text: '🤔 No encontré días con horas de trabajo. Ejemplo: "10 horas el martes, 8 el jueves y 4 el viernes; 3 personas martes y jueves y 7 el viernes".' }];
    }
    const isCorrection = Boolean(previous);
    const number = isCorrection ? previous.numberInt : this.store.peekNextNumber();
    const inv = buildInvoice({ data, config: this.config, today: todayIn(this.tz), number });
    const pdf = await renderInvoicePdf(inv, this.config);

    // Copia de todo en data/facturas/<numero>/
    const dir = this.store.invoiceDir(inv.number);
    this.store.takePending(chat.key, inv.number);
    const receiptsDir = path.join(dir, 'recibos');
    const receipts = fs.existsSync(receiptsDir) ? fs.readdirSync(receiptsDir).sort().map((f) => path.join(receiptsDir, f)) : [];
    fs.writeFileSync(path.join(dir, pdfFileName(inv)), pdf);
    fs.writeFileSync(path.join(dir, 'datos.json'), JSON.stringify({ data, invoice: inv }, null, 2));

    // Borrador en Gmail
    const notes = [...warnings];
    let draft = { ok: false, skipped: true };
    let oldDraftGone = null;
    if (this.mailbox?.enabled) {
      if (isCorrection && previous.messageId) {
        try {
          oldDraftGone = await this.mailbox.deleteDraft(previous.messageId);
        } catch (err) {
          notes.push(`No pude borrar el borrador anterior (${explainMailError(err)}); bórralo a mano.`);
        }
      }
      const e = this.config.empresa || {};
      const from = { name: e.nombreCorto || e.nombre || '', address: this.mailbox.user };
      const content = buildEmailContent(inv, this.config, { receiptsCount: receipts.length });
      const messageId = newMessageId(this.mailbox.user);
      const raw = await composeRaw({
        from,
        to: inv.project.to,
        cc: inv.project.cc,
        ...content,
        messageId,
        attachments: [
          { filename: pdfFileName(inv), content: pdf, contentType: 'application/pdf' },
          ...receipts.map((f, i) => {
            const ext = path.extname(f).toLowerCase();
            return { filename: `Receipt_${i + 1}${ext}`, content: fs.readFileSync(f), contentType: MIME[ext] || 'application/octet-stream' };
          }),
        ],
      });
      try {
        await this.mailbox.createDraft(raw);
        draft = { ok: true, messageId };
      } catch (err) {
        this.log.error('No se pudo crear el borrador:', err);
        draft = { ok: false, error: explainMailError(err) };
      }
    }

    if (!isCorrection) this.store.commitNumber(number);
    const keepOldId = isCorrection && oldDraftGone === false && !draft.ok ? previous.messageId : null;
    this.store.updateChat(chat.key, {
      ultimo: {
        number: inv.number,
        numberInt: number,
        data: dataForCorrections(data, inv),
        messageId: draft.ok ? draft.messageId : keepOldId,
        totalCents: inv.totalCents,
        createdAt: new Date().toISOString(),
      },
      pregunta: undefined,
    });

    if (!inv.project.known) notes.push(`El proyecto «${inv.project.name}» no está en config.json: el invoice va sin dirección y el borrador sin destinatarios.`);
    else if (draft.ok && !inv.project.to.length) notes.push('El borrador no tiene destinatarios: agrega "para" al proyecto en config.json.');
    if (isCorrection && oldDraftGone === false) notes.push('El borrador anterior ya no estaba en Gmail (¿ya lo habías enviado?). Este es una versión nueva.');

    const summary = this.summaryText(inv, data, { draft, isCorrection, receipts: receipts.length, notes });
    return [
      { text: summary },
      { document: pdf, filename: pdfFileName(inv), mimetype: 'application/pdf', caption: inv.number },
    ];
  }

  summaryText(inv, data, { draft, isCorrection, receipts, notes }) {
    const L = [];
    if (draft.ok) L.push(isCorrection ? `♻️ *${inv.number}* corregido — reemplacé el borrador en Gmail` : `✅ *${inv.number}* listo — borrador guardado en Gmail`);
    else L.push(isCorrection ? `♻️ *${inv.number}* corregido` : `✅ *${inv.number}* listo`);
    L.push(`📍 ${inv.project.name}${inv.project.po ? ` · PO #${inv.project.po}` : ''}`);
    L.push(`📅 Semana ${esRangeShort(inv.weekStart, inv.weekEnd)}`);
    L.push('', '👷 *Horas de trabajo*');
    const groups = [...data.dias].sort((a, b) => DAY_KEYS.indexOf(a.dia) - DAY_KEYS.indexOf(b.dia) || b.horas - a.horas);
    for (const g of groups) {
      const date = inv.dates[DAY_KEYS.indexOf(g.dia)];
      L.push(`• ${esDayLabel(date)}: ${g.personas} ${plural(g.personas, 'persona', 'personas')} × ${hrs(g.horas)} h = ${hrs(g.personas * g.horas)} h`);
    }
    const labor = inv.lines.find((l) => l.key === 'labor');
    L.push(`Total: ${hrs(inv.laborHours)} h × ${money(inv.rateCents)} = ${money(labor.amountCents)}`);
    L.push('');
    const drive = inv.lines.find((l) => l.key === 'driving');
    if (drive) {
      const detail = inv.driving.map((d) => `${esDayLabel(d.date)} ${hrs(d.hours)} h`).join(', ');
      L.push(`🚐 Manejo: ${hrs(inv.drivingHours)} h × ${money(inv.driveRateCents)} = ${money(drive.amountCents)} (${detail})`);
    }
    const icons = { gas: '⛽ Gasolina', supplies: '🧴 Materiales', meals: '🍽️ Comida' };
    for (const l of inv.lines) {
      if (icons[l.key]) L.push(`${icons[l.key]}: ${money(l.amountCents)}`);
      if (l.key === 'other') L.push(`➕ ${l.desc}: ${money(l.amountCents)}`);
    }
    if (receipts) L.push(`📎 Recibos adjuntos: ${receipts}`);
    L.push('', `💵 *TOTAL: ${money(inv.totalCents)}*`, '');
    if (draft.ok) {
      const to = [...inv.project.to, ...inv.project.cc];
      if (to.length) L.push(`✉️ Para: ${to.join(', ')}`);
      L.push('Revísalo en Gmail → Borradores y dale Enviar.');
    } else if (draft.note) {
      L.push(draft.note);
    } else if (draft.error) {
      L.push(`⚠️ No pude guardar el borrador en Gmail: ${draft.error}`);
      L.push('Te mando el PDF aquí. Cuando se arregle, escríbeme «inténtalo otra vez».');
    } else {
      L.push('ℹ️ El correo no está configurado: te mando solo el PDF.');
    }
    for (const n of notes) L.push(`⚠️ ${n}`);
    L.push('', '¿Algo mal? Escríbeme la corrección, ej.: "el jueves fueron 9 horas".');
    return L.join('\n');
  }
}
