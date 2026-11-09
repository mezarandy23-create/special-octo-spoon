// Dibuja el PDF del invoice con el mismo diseño que INV-2026-050 (tamaño carta).
// Las medidas salen del PDF original; las coordenadas aquí son desde arriba-izquierda.

import PDFDocument from 'pdfkit';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { enLong, enRange, enShort, enDayShort, hrs, money } from './format.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FONT_R = path.join(ROOT, 'assets/fonts/DejaVuSans.ttf');
const FONT_B = path.join(ROOT, 'assets/fonts/DejaVuSans-Bold.ttf');

const C = {
  page: '#FFFAF4',
  rule: '#F2E8DE',
  dark: '#241B18',
  gold: '#C5A184',
  cream: '#FFF7F0',
  border: '#DCC8B8',
  label: '#8C766B',
  text: '#332520',
  band: '#F4E9DF',
  totalAmt: '#F3D8C0',
};

const W = 612;
const H = 792;
const L = 40; // margen izquierdo
const R = 572; // margen derecho
const DAY_COLS = [187, 232, 277, 322, 367, 412, 457]; // inicio de cada columna Lun..Dom (45 de ancho)
const TOTAL_COL = [502, 572];
const SUM_COLS = { hours: [270, 330], ot: [330, 390], rate: [390, 460], amount: [460, 572] };

export function renderInvoicePdf(inv, config) {
  const empresa = config.empresa || {};
  const doc = new PDFDocument({
    size: 'LETTER',
    margin: 0,
    autoFirstPage: false,
    info: {
      Title: `${empresa.nombre || ''} - ${inv.number}`,
      Author: empresa.nombre || '',
      Subject: `Invoice for ${inv.project.name}`,
    },
  });
  doc.registerFont('R', FONT_R);
  doc.registerFont('B', FONT_B);

  const chunks = [];
  doc.on('data', (c) => chunks.push(c));
  const done = new Promise((resolve, reject) => {
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);
  });

  // ---------- helpers ----------
  const text = (str, x, y, { font = 'R', size = 7, color = C.text, align = 'left', maxWidth } = {}) => {
    let s = size;
    doc.font(font).fontSize(s);
    if (maxWidth) {
      while (s > 4 && doc.widthOfString(str) > maxWidth) doc.fontSize((s -= 0.2));
    }
    const w = doc.widthOfString(str);
    const left = align === 'right' ? x - w : align === 'center' ? x - w / 2 : x;
    doc.fillColor(color).text(str, left, y, { lineBreak: false, baseline: 'alphabetic' });
  };
  const box = (x, y, w, h, r, fill, stroke, lw = 0.75) => {
    doc.save().lineWidth(lw).roundedRect(x, y, w, h, r);
    if (fill && stroke) doc.fillAndStroke(fill, stroke);
    else if (fill) doc.fill(fill);
    else doc.stroke(stroke);
    doc.restore();
  };
  const rect = (x, y, w, h, fill) => doc.save().rect(x, y, w, h).fill(fill).restore();
  const line = (x1, y1, x2, y2, color, lw) => doc.save().lineWidth(lw).moveTo(x1, y1).lineTo(x2, y2).stroke(color).restore();
  const wrap = (str, font, size, width) => {
    doc.font(font).fontSize(size);
    const out = [];
    let cur = '';
    for (const word of String(str).split(/(\s+)/)) {
      const next = cur + word;
      if (cur && doc.widthOfString(next.trimEnd()) > width) {
        out.push(cur.trimEnd());
        cur = word.trimStart();
      } else cur = next;
    }
    if (cur.trim()) out.push(cur.trimEnd());
    return out;
  };
  const newPage = () => {
    doc.addPage({ size: 'LETTER', margin: 0 });
    rect(0, 0, W, H, C.page);
    for (let y = 43; y <= 747; y += 22) line(L, y, R, y, C.rule, 0.35);
  };

  // ---------- medir para que todo quepa en una hoja ----------
  const nRows = inv.workers.length;
  const drivingLines = inv.drivingText ? wrap(inv.drivingText.detail, 'R', 6.2, R - 117 - 10) : [];
  const drivingH = inv.drivingText ? 23 + 10 * (drivingLines.length - 1) : 0;
  const noteLines = inv.notes.flatMap((n) => wrap(`- ${n}`, 'R', 5.8, R - 54 - 14));
  const notesH = 38 + 14 * (noteLines.length - 1);
  const nSum = inv.lines.length + 1;

  const layout = (rowH, sRowH) => {
    const tableBottom = 334 + nRows * rowH + 19;
    const afterDriving = inv.drivingText ? tableBottom + 3 + drivingH : tableBottom;
    const summaryBottom = afterDriving + 29 + 22 + nSum * sRowH;
    return { tableBottom, afterDriving, summaryBottom, end: summaryBottom + 10 + 42 + 12 + notesH };
  };
  const LIMIT = 758;
  let rowH = 16;
  let sRowH = 16;
  let lay = layout(rowH, sRowH);
  if (lay.end > LIMIT) {
    rowH = Math.max(11, 16 - (lay.end - LIMIT) / Math.max(nRows, 1));
    lay = layout(rowH, sRowH);
  }
  if (lay.end > LIMIT) {
    sRowH = Math.max(12, 16 - (lay.end - LIMIT) / nSum);
    lay = layout(rowH, sRowH);
  }
  const splitPages = lay.end > LIMIT; // si de plano no cabe, el resumen pasa a la hoja 2 (con filas de tamaño normal)
  if (splitPages) {
    sRowH = 16;
    const room = LIMIT - 334 - 19 - (inv.drivingText ? 3 + drivingH : 0);
    rowH = Math.max(9, Math.min(16, room / Math.max(nRows, 1)));
  }

  newPage();

  // ---------- encabezado ----------
  box(L, 38, R - L, 92, 18, C.dark, C.gold, 0.9);
  const logo = empresa.logo ? path.resolve(ROOT, empresa.logo) : null;
  if (logo && fs.existsSync(logo)) doc.image(logo, 51, 49, { width: 67, height: 70 });
  text(empresa.nombre || '', 133, 71, { font: 'B', size: 16, color: C.cream, maxWidth: 300 });
  text(empresa.eslogan || '', 133, 92, { size: 10, color: C.gold, maxWidth: 232 });
  line(133, 102, 365, 102, C.gold, 0.65);
  text(empresa.ubicacion || '', 557, 73, { size: 7.2, color: C.cream, align: 'right' });
  text(empresa.telefono || '', 557, 90, { size: 7.2, color: C.cream, align: 'right' });
  text(empresa.email || '', 557, 107, { size: 7.2, color: C.cream, align: 'right' });
  text(empresa.servicios || '', 557, 122, { size: 6.1, color: C.gold, align: 'right' });

  // ---------- proyecto y datos del invoice ----------
  box(L, 146, 262, 76, 13, C.cream, C.border);
  box(310, 146, 262, 76, 13, C.cream, C.border);
  text('PROJECT', 55, 164, { font: 'B', size: 6.8, color: C.label });
  text(inv.project.name, 55, 186, { font: 'B', size: 12, color: C.text, maxWidth: 235 });
  text(inv.project.address, 55, 208, { size: 6.8, color: C.label, maxWidth: 235 });
  text('INVOICE DETAILS', 325, 164, { font: 'B', size: 6.8, color: C.label });
  text(inv.number, 557, 165, { font: 'B', size: 10.2, color: C.text, align: 'right' });
  text('Date', 325, 183, { size: 6.4, color: C.label });
  text(enLong(inv.date), 557, 183, { font: 'B', size: 7.2, color: C.text, align: 'right' });
  text('PO #', 325, 199, { size: 6.4, color: C.label });
  text(inv.project.po ? `#${inv.project.po}` : '-', 557, 199, { font: 'B', size: 7.2, color: C.text, align: 'right' });

  // ---------- banda servicio / tarifa / supervisor / enviado por ----------
  box(L, 235, R - L, 34, 11, C.band, C.border);
  const band = [
    ['SERVICE', inv.service, 55],
    ['RATE', `${money(inv.rateCents)}/hr`, 172],
    ['SUPERVISOR', inv.supervisor || '-', 289],
    ['SENT BY', inv.sentBy || '-', 422],
  ];
  for (const [lbl, val, x] of band) {
    text(lbl, x, 248, { font: 'B', size: 5.9, color: C.label });
    text(val, x, 262, { font: 'B', size: 7.8, color: C.text, maxWidth: 110 });
  }

  // ---------- tabla de horas ----------
  text('WEEKLY LABOR HOURS', L, 287, { font: 'B', size: 7.5, color: C.label });
  text(`Week: ${enRange(inv.weekStart, inv.weekEnd, '-')}`, R, 287, { size: 6.8, color: C.label, align: 'right' });

  box(L, 299, R - L, 35, 10, C.dark, null);
  text('JOB', 56, 313, { font: 'B', size: 5.2, color: C.cream, align: 'center' });
  text('WORKER NAME', 79, 313, { font: 'B', size: 5.6, color: C.cream });
  DAY_COLS.forEach((x, i) => {
    text(enDayShort(i).toUpperCase(), x + 22.5, 313, { font: 'B', size: 5.2, color: C.cream, align: 'center' });
    text(enShort(inv.dates[i]), x + 22.5, 326, { size: 4.9, color: C.gold, align: 'center' });
  });
  text('TOTAL', 537, 313, { font: 'B', size: 5.2, color: C.cream, align: 'center' });

  let y = 334;
  const fs1 = Math.min(6.2, rowH * 0.4);
  inv.workers.forEach((w, r) => {
    rect(L, y, R - L, rowH, r % 2 === 0 ? C.cream : C.page);
    const base = y + rowH / 2 + 3.3 * (rowH / 16);
    text('L', 56, base, { font: 'B', size: Math.min(6, fs1), align: 'center' });
    text(w.name, 79, base, { font: 'B', size: fs1, maxWidth: 104 });
    w.hours.forEach((h, d) => {
      if (h > 0) text(hrs(h), DAY_COLS[d] + 22.5, base, { font: 'B', size: fs1, align: 'center' });
    });
    text(hrs(w.total), 537, base, { font: 'B', size: fs1, align: 'center' });
    line(L, y + rowH, R, y + rowH, C.border, 0.55);
    y += rowH;
  });
  // fila de totales por día
  rect(L, y, 147, 19, C.dark);
  text('TOTAL HOURS PER DAY', 48, y + 13.2, { font: 'B', size: 5.7, color: C.gold });
  DAY_COLS.forEach((x, d) => {
    rect(x, y, 45, 19, C.band);
    if (inv.dayTotals[d] > 0) text(hrs(inv.dayTotals[d]), x + 22.5, y + 13.2, { font: 'B', size: 6.4, align: 'center' });
  });
  rect(TOTAL_COL[0], y, 70, 19, C.band);
  text(hrs(inv.laborHours), 537, y + 13.2, { font: 'B', size: 7, align: 'center' });
  const tableBottom = y + 19;
  for (const x of [L, 72, ...DAY_COLS, TOTAL_COL[0], R]) line(x, 334, x, tableBottom, C.border, 0.5);
  box(L, 299, R - L, tableBottom - 299, 10, null, C.border, 0.5);

  // ---------- manejo ----------
  y = tableBottom;
  if (inv.drivingText) {
    const top = y + 3;
    box(L, top, R - L, drivingH, 8, C.band, C.border);
    text('DRIVING', 51, top + 10, { font: 'B', size: 6.3, color: C.label });
    drivingLines.forEach((ln, i) => text(ln, 117, top + 10 + 10 * i, { size: 6.2 }));
    text(inv.drivingText.total, 117, top + 20 + 10 * (drivingLines.length - 1), { font: 'B', size: 5.9 });
    y = top + drivingH;
  }

  if (splitPages) {
    newPage();
    y = 30;
  }

  // ---------- resumen ----------
  text('SUMMARY', L, y + 19, { font: 'B', size: 7.5, color: C.label });
  const sTop = y + 29;
  box(L, sTop, R - L, 22, 10, C.dark, null);
  const hb = sTop + 14.5;
  text('DESCRIPTION', 50, hb, { font: 'B', size: 5.9, color: C.cream });
  text('HOURS', 300, hb, { font: 'B', size: 5.9, color: C.cream, align: 'center' });
  text('OT HOURS', 360, hb, { font: 'B', size: 5.9, color: C.cream, align: 'center' });
  text('RATE', 425, hb, { font: 'B', size: 5.9, color: C.cream, align: 'center' });
  text('AMOUNT', 516, hb, { font: 'B', size: 5.9, color: C.cream, align: 'center' });

  y = sTop + 22;
  const rows = [
    ...inv.lines.map((l) => ({ ...l, bold: false })),
    { desc: 'Subtotal', hours: null, rateCents: null, amountCents: inv.subtotalCents, bold: true },
  ];
  const fs2 = Math.min(6.2, sRowH * 0.4);
  rows.forEach((row, i) => {
    rect(L, y, R - L, sRowH, i % 2 === 0 ? C.cream : C.page);
    const base = y + sRowH / 2 + 3.2 * (sRowH / 16);
    const f = row.bold ? 'B' : 'R';
    text(row.desc, 50, base, { font: f, size: fs2, maxWidth: 214 });
    text(row.hours != null ? hrs(row.hours) : '-', 300, base, { font: f, size: Math.min(6.1, fs2), align: 'center' });
    text('-', 360, base, { font: f, size: Math.min(6.1, fs2), align: 'center' });
    text(row.rateCents != null ? money(row.rateCents) : '-', 425, base, { font: f, size: Math.min(6.1, fs2), align: 'center' });
    text(money(row.amountCents), 562, base, { font: 'B', size: fs2, align: 'right' });
    line(L, y + sRowH, R, y + sRowH, C.border, 0.55);
    y += sRowH;
  });
  for (const x of [L, SUM_COLS.hours[0], SUM_COLS.ot[0], SUM_COLS.rate[0], SUM_COLS.amount[0], R]) {
    line(x, sTop + 22, x, y, C.border, 0.55);
  }
  box(L, sTop, R - L, y - sTop, 10, null, C.border, 0.55);

  // ---------- total ----------
  const tTop = y + 10;
  box(L, tTop, R - L, 42, 14, C.dark, null);
  text('TOTAL DUE', 60, tTop + 26, { font: 'B', size: 8.6, color: C.gold });
  text(money(inv.totalCents), 552, tTop + 29.5, { font: 'B', size: 16, color: C.totalAmt, align: 'right' });

  // ---------- notas ----------
  const nTop = tTop + 42 + 12;
  box(L, nTop, R - L, notesH, 12, C.cream, C.border);
  text('NOTES', 54, nTop + 15, { font: 'B', size: 6.6, color: C.label });
  noteLines.forEach((ln, i) => text(ln, 54, nTop + 30 + 14 * i, { size: 5.8 }));

  // ---------- firma ----------
  const fy = Math.max(770, nTop + notesH + 14);
  text('Authorized signature: ______________________________', L, fy, { size: 5.9, color: C.label });
  text(`${empresa.nombreCorto || empresa.nombre || ''}     Date: __________________`, R, fy, { size: 5.9, color: C.label, align: 'right' });

  doc.end();
  return done;
}
