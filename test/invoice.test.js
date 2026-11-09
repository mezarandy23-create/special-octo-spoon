import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { normalizeData, buildInvoice, resolveWeekStart } from '../src/invoice.js';
import { renderInvoicePdf } from '../src/pdf.js';
import { buildEmailContent, composeRaw } from '../src/email.js';
import { money, enRange, esRange } from '../src/format.js';
import { InvoiceBot } from '../src/bot.js';
import { Store } from '../src/store.js';

const config = JSON.parse(fs.readFileSync(new URL('../config.example.json', import.meta.url), 'utf8'));
config.proyectos = [{ nombre: 'MAIN STREET PLAZA', alias: ['plaza'], direccion: '100 Main St, Atlanta, GA', po: '12345', para: ['pagos@cliente.com'], cc: [] }];
const inv050 = JSON.parse(fs.readFileSync(new URL('../ejemplos/semana-completa.json', import.meta.url), 'utf8'));

const userExample = {
  proyecto: '', fecha_referencia: '', nombres_trabajadores: [], manejo: [], gasolina: 0, materiales: 0, comida: 0,
  otros_gastos: [], po: '', tarifa: 0, notas: [],
  dias: [{ dia: 'mar', personas: 3, horas: 10 }, { dia: 'jue', personas: 3, horas: 8 }, { dia: 'vie', personas: 7, horas: 4 }],
};

test('reproduce exactamente las cuentas del INV-2026-050 original', () => {
  const { data } = normalizeData(inv050);
  const inv = buildInvoice({ data, config, today: '2026-10-05', number: 50 });
  assert.equal(inv.number, 'INV-2026-050');
  assert.equal(inv.date, '2026-10-02');
  assert.equal(inv.laborHours, 300);
  assert.equal(inv.drivingHours, 8);
  assert.equal(money(inv.totalCents), '$7,058.21');
  assert.deepEqual(inv.lines.map((l) => money(l.amountCents)), ['$6,000.00', '$160.00', '$137.00', '$161.21', '$600.00']);
  assert.deepEqual(inv.notes, [
    '6 workers x 10 hrs x 5 days (Mon, Sep 28 - Fri, Oct 2) = 300 labor hrs.',
    'Driving: 4 hrs outbound Monday + 4 hrs return Friday = 8 hrs at $20/hr.',
    'Meals: $600.00 | Gas: $137.00 | Supplies: $161.21 | PO #12345 | Status: PENDING PAYMENT.',
  ]);
  assert.equal(inv.drivingText.detail, 'Mon, Sep 28: 4 hrs outbound  |  Fri, Oct 2: 4 hrs return');
});

test('ejemplo del mensaje: 3 personas mar/jue, 7 el viernes', () => {
  const { data } = normalizeData(userExample);
  const inv = buildInvoice({ data, config, today: '2026-11-09', number: 51 });
  assert.equal(inv.weekStart, '2026-11-02'); // hoy es lunes 9 -> la semana pasada
  assert.equal(inv.number, 'INV-2026-051');
  assert.equal(inv.workers.length, 7);
  assert.deepEqual(inv.workers[0].hours, [0, 10, 0, 8, 4, 0, 0]);
  assert.deepEqual(inv.workers[6].hours, [0, 0, 0, 0, 4, 0, 0]);
  assert.deepEqual(inv.dayTotals, [0, 30, 0, 24, 28, 0, 0]);
  assert.equal(inv.laborHours, 82);
  assert.equal(money(inv.totalCents), '$1,640.00');
  assert.equal(inv.date, '2026-11-06');
});

test('elige la semana correcta según el día de hoy', () => {
  const { data } = normalizeData(userExample);
  assert.equal(resolveWeekStart(data, '2026-11-06'), '2026-11-02'); // viernes: esta semana
  assert.equal(resolveWeekStart(data, '2026-11-08'), '2026-11-02'); // domingo: esta semana
  assert.equal(resolveWeekStart(data, '2026-11-05'), '2026-10-26'); // jueves: el viernes no ha pasado -> semana anterior
  assert.equal(resolveWeekStart({ ...data, fecha_referencia: '2026-10-15' }, '2026-11-09'), '2026-10-12');
});

test('grupos con horas distintas el mismo día', () => {
  const { data } = normalizeData({ ...userExample, dias: [{ dia: 'lun', personas: 2, horas: 10 }, { dia: 'lun', personas: 1, horas: 6 }] });
  const inv = buildInvoice({ data, config, today: '2026-11-09', number: 1 });
  assert.deepEqual(inv.workers.map((w) => w.hours[0]), [10, 10, 6]);
  assert.equal(inv.laborHours, 26);
  assert.match(inv.notes[0], /2 workers x 10 hrs \+ 1 worker x 6 hrs = 26 labor hrs/);
});

test('descarta datos sin sentido de la IA', () => {
  const { data, warnings } = normalizeData({ dias: [{ dia: 'xx', personas: 3, horas: 8 }, { dia: 'lun', personas: 0, horas: 8 }, { dia: 'mar', personas: 2, horas: 30 }, { dia: 'mie', personas: 2, horas: 8 }], gasolina: -5 });
  assert.equal(data.dias.length, 1);
  assert.equal(warnings.length, 3);
  assert.equal(data.gasolina, 0);
});

test('genera el PDF (normal y con muchas personas)', async () => {
  const { data } = normalizeData(inv050);
  const pdf = await renderInvoicePdf(buildInvoice({ data, config, today: '2026-10-05', number: 50 }), config);
  assert.equal(pdf.subarray(0, 4).toString(), '%PDF');
  const big = normalizeData({ ...inv050, dias: ['lun', 'mar', 'mie', 'jue', 'vie', 'sab'].map((d) => ({ dia: d, personas: 30, horas: 9 })) }).data;
  const pdf2 = await renderInvoicePdf(buildInvoice({ data: big, config, today: '2026-10-05', number: 51 }), config);
  assert.equal(pdf2.subarray(0, 4).toString(), '%PDF');
});

test('el correo tiene el mismo texto que el original', async () => {
  const { data } = normalizeData(inv050);
  const inv = buildInvoice({ data, config, today: '2026-10-05', number: 50 });
  const c = buildEmailContent(inv, config, { receiptsCount: 2 });
  assert.match(c.text, /Please find attached Invoice INV-2026-050 from MAAI Multiservices LLC for services rendered at Main Street Plaza during the week of September 28–October 2, 2026\./);
  assert.match(c.text, /Total Amount Due: \$7,058\.21/);
  assert.match(c.text, /Receipts for gas and cleaning supplies are also attached for your reference\./);
  assert.match(c.text, /servicios prestados en Main Street Plaza durante la semana del 28 de septiembre al 2 de octubre de 2026\./);
  assert.match(c.text, /Total a cobrar: \$7,058\.21/);
  const raw = (await composeRaw({ from: 'a@b.com', to: ['x@y.com'], ...c, messageId: '<t@b.com>', attachments: [{ filename: 'Invoice_INV-2026-050.pdf', content: Buffer.from('%PDF'), contentType: 'application/pdf' }] })).toString();
  assert.match(raw, /filename=Invoice_INV-2026-050\.pdf/);
  assert.match(raw, /Message-ID: <t@b\.com>/i);
  const none = buildEmailContent(inv, config, { receiptsCount: 0 });
  assert.doesNotMatch(none.text, /Receipts/);
});

test('rangos de fechas en inglés y español', () => {
  assert.equal(enRange('2026-11-03', '2026-11-06', '–'), 'November 3–6, 2026');
  assert.equal(enRange('2026-12-28', '2027-01-01', '–'), 'December 28, 2026–January 1, 2027');
  assert.equal(esRange('2026-11-03', '2026-11-06'), 'del 3 al 6 de noviembre de 2026');
  assert.equal(esRange('2026-09-28', '2026-10-02'), 'del 28 de septiembre al 2 de octubre de 2026');
});

// ---------- flujo completo del bot con IA y Gmail de mentira ----------
function fakeEnv() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bot-'));
  const store = new Store(dir, { firstNumber: 51 });
  const drafts = new Map();
  const mailbox = {
    enabled: true,
    user: 'maaicleaning@gmail.com',
    async createDraft(raw) { const id = raw.toString().match(/Message-ID: (<[^>]+>)/i)[1]; drafts.set(id, raw.toString()); return { uid: drafts.size }; },
    async deleteDraft(id) { return drafts.delete(id); },
  };
  const queue = [];
  const ai = { async interpret(args) { const next = queue.shift(); return typeof next === 'function' ? next(args) : next; } };
  const bot = new InvoiceBot({ config, store, ai, mailbox, logger: { info() {}, warn() {}, error() {} }, accessCode: 'Clave123' });
  return { bot, store, drafts, queue };
}

const chat = { key: 'wa:17705550000@s.whatsapp.net', altKeys: ['wa:123@lid'], phones: ['17705550000'], name: 'Jefa' };

test('bot: activar, crear, corregir y borrar', async () => {
  const { bot, store, drafts, queue } = fakeEnv();

  assert.deepEqual(await bot.handle(chat, { id: '1', text: 'hola' }), []); // no autorizado: silencio
  assert.deepEqual(await bot.handle(chat, { id: '2', text: 'activar mala' }), []);
  const act = await bot.handle(chat, { id: '3', text: 'activar clave123' });
  assert.match(act[0].text, /Listo/);

  // recibo antes del invoice
  const r = await bot.handle(chat, { id: '4', text: '', attachments: [{ filename: 'gas.jpg', contentType: 'image/jpeg', content: Buffer.from('jpg') }] });
  assert.match(r[0].text, /Guardé 1 recibo/);

  queue.push({ accion: 'crear', respuesta: '', ...userExample, numero_siguiente: 0 });
  const created = await bot.handle(chat, { id: '5', text: '10 horas el martes...' });
  assert.match(created[0].text, /INV-2026-051\* listo — borrador guardado en Gmail/);
  assert.match(created[0].text, /TOTAL: \$1,640\.00/);
  assert.match(created[0].text, /Recibos adjuntos: 1/);
  assert.equal(created[1].filename, 'Invoice_INV-2026-051.pdf');
  assert.equal(drafts.size, 1);
  assert.match([...drafts.values()][0], /filename=Receipt_1\.jpg/);
  assert.equal(store.peekNextNumber(), 52);

  // mismo mensaje repetido (WhatsApp lo reenvía): se ignora
  assert.deepEqual(await bot.handle(chat, { id: '5', text: '10 horas el martes...' }), []);

  // corrección: la IA recibe el invoice anterior y devuelve todo corregido
  queue.push(({ previous }) => {
    assert.equal(previous.number, 'INV-2026-051');
    assert.equal(previous.data.fecha_referencia, '2026-11-02');
    const d = structuredClone(previous.data);
    d.dias[1].horas = 9;
    return { accion: 'corregir', respuesta: '', numero_siguiente: 0, ...d };
  });
  const fixed = await bot.handle(chat, { id: '6', text: 'el jueves fueron 9 horas' });
  assert.match(fixed[0].text, /INV-2026-051\* corregido — reemplacé el borrador/);
  assert.match(fixed[0].text, /TOTAL: \$1,700\.00/);
  assert.equal(drafts.size, 1); // el viejo se borró, quedó solo el nuevo
  assert.match([...drafts.values()][0], /Receipt_1\.jpg/); // conserva el recibo
  assert.equal(store.peekNextNumber(), 52);

  // borrar
  queue.push({ accion: 'borrar', respuesta: '', ...userExample, numero_siguiente: 0 });
  const del = await bot.handle(chat, { id: '7', text: 'borra el último' });
  assert.match(del[0].text, /Cancelé el INV-2026-051/);
  assert.equal(drafts.size, 0);
  assert.equal(store.peekNextNumber(), 51);

  // el mismo chat llega con su ID alterno (@lid) y sigue autorizado
  queue.push({ accion: 'otro', respuesta: 'Hola 👋', ...userExample, numero_siguiente: 0 });
  const viaLid = await bot.handle({ key: 'wa:123@lid', altKeys: [], phones: [], name: 'Jefa' }, { id: '8', text: 'hola' });
  assert.equal(viaLid[0].text, 'Hola 👋');
});

test('bot: si Gmail falla igual entrega el PDF', async () => {
  const { bot, store, queue } = fakeEnv();
  store.authorize([chat.key]);
  bot.mailbox.createDraft = async () => { const e = new Error('auth'); e.authenticationFailed = true; throw e; };
  queue.push({ accion: 'crear', respuesta: '', ...userExample, numero_siguiente: 0 });
  const res = await bot.handle(chat, { id: '9', text: 'x' });
  assert.match(res[0].text, /No pude guardar el borrador en Gmail: Gmail rechazó/);
  assert.equal(res[1].document.subarray(0, 4).toString(), '%PDF');
});
