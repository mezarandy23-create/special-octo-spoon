// Convierte los datos que entendió la IA en un invoice con todas las cuentas hechas.
// IMPORTANTE: la IA nunca suma ni multiplica; todas las cuentas se hacen aquí, en centavos.

import {
  DAY_KEYS, addDays, weekdayIndex, mondayOf, isISODate, year,
  enDayLabel, enWeekday, enDayShort, hrs, money, toCents, plural, titleCase,
} from './format.js';

const MAX_PEOPLE = 30; // máximo de personas por día (para que la tabla quepa en la hoja)

/** Limpia y valida lo que devolvió la IA (o un JSON de prueba). Devuelve { data, warnings }. */
export function normalizeData(raw = {}) {
  const warnings = [];
  const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
  const str = (v) => (typeof v === 'string' ? v.trim() : '');

  const dias = [];
  for (const e of Array.isArray(raw.dias) ? raw.dias : []) {
    const dia = DAY_KEYS.includes(e?.dia) ? e.dia : null;
    const personas = Math.round(num(e?.personas));
    const horas = Math.round(num(e?.horas) * 100) / 100;
    if (!dia || personas < 1 || personas > MAX_PEOPLE || horas <= 0 || horas > 24) {
      warnings.push(`Ignoré un dato que no tiene sentido: ${JSON.stringify(e)}`);
      continue;
    }
    dias.push({ dia, personas, horas });
  }

  const manejo = [];
  for (const e of Array.isArray(raw.manejo) ? raw.manejo : []) {
    const dia = DAY_KEYS.includes(e?.dia) ? e.dia : null;
    const horas = Math.round(num(e?.horas) * 100) / 100;
    if (!dia || horas <= 0 || horas > 24) {
      warnings.push(`Ignoré un dato de manejo que no tiene sentido: ${JSON.stringify(e)}`);
      continue;
    }
    manejo.push({ dia, horas, descripcion: str(e?.descripcion) });
  }

  const otros = [];
  for (const e of Array.isArray(raw.otros_gastos) ? raw.otros_gastos : []) {
    const monto = Math.round(num(e?.monto) * 100) / 100;
    if (monto > 0 && str(e?.descripcion)) otros.push({ descripcion: str(e.descripcion), monto });
  }

  const money2 = (v) => Math.max(0, Math.round(num(v) * 100) / 100);

  return {
    data: {
      proyecto: str(raw.proyecto),
      fecha_referencia: isISODate(raw.fecha_referencia) ? raw.fecha_referencia : '',
      dias,
      nombres_trabajadores: (Array.isArray(raw.nombres_trabajadores) ? raw.nombres_trabajadores : []).map(str).filter(Boolean),
      manejo,
      gasolina: money2(raw.gasolina),
      materiales: money2(raw.materiales),
      comida: money2(raw.comida),
      otros_gastos: otros,
      po: str(raw.po).replace(/^#/, ''),
      tarifa: money2(raw.tarifa),
      notas: (Array.isArray(raw.notas) ? raw.notas : []).map(str).filter(Boolean),
    },
    warnings,
  };
}

/** Busca el proyecto en config (por nombre o alias). Si no existe, crea uno "suelto" sin destinatarios. */
export function findProject(config, name) {
  const list = config.proyectos || [];
  const n = String(name || '').trim().toLowerCase();
  if (!n) return { ...list[0], encontrado: true };
  const hit = list.find((p) => p.nombre.toLowerCase() === n || (p.alias || []).some((a) => a.toLowerCase() === n));
  if (hit) return { ...hit, encontrado: true };
  const partial = list.find((p) => p.nombre.toLowerCase().includes(n) || n.includes(p.nombre.toLowerCase()));
  if (partial) return { ...partial, encontrado: true };
  return { nombre: name.toUpperCase(), direccion: '', po: '', para: [], cc: [], encontrado: false };
}

/**
 * Elige la semana (lunes) del invoice.
 * - Si el mensaje dio una fecha, se usa la semana de esa fecha.
 * - Si no, la semana más reciente en la que todos los días mencionados ya pasaron (o son hoy).
 *   Ej.: hoy lunes y dice "martes y jueves" -> la semana pasada.
 */
export function resolveWeekStart(data, today) {
  if (data.fecha_referencia) return mondayOf(data.fecha_referencia);
  const idxs = [...data.dias, ...data.manejo].map((e) => DAY_KEYS.indexOf(e.dia));
  const maxIdx = idxs.length ? Math.max(...idxs) : 0;
  const thisMonday = mondayOf(today);
  return maxIdx <= weekdayIndex(today) ? thisMonday : addDays(thisMonday, -7);
}

export function formatNumber(config, n, dateISO) {
  const prefix = config.factura?.prefijo || 'INV';
  return `${prefix}-${year(dateISO)}-${String(n).padStart(3, '0')}`;
}

/**
 * Construye el invoice completo.
 * @param {object} p
 * @param {object} p.data  datos normalizados (normalizeData)
 * @param {object} p.config config.json
 * @param {string} p.today 'YYYY-MM-DD'
 * @param {number} p.number número consecutivo (51 -> INV-2026-051)
 */
export function buildInvoice({ data, config, today, number }) {
  if (!data.dias.length) throw new Error('El invoice no tiene días con horas de trabajo.');

  const f = config.factura || {};
  const project = findProject(config, data.proyecto);
  const weekStart = resolveWeekStart(data, today);
  const dates = DAY_KEYS.map((_, i) => addDays(weekStart, i));

  const rateCents = toCents(data.tarifa || project.tarifaPorHora || f.tarifaPorHora || 0);
  const driveRateCents = toCents(project.tarifaManejo || f.tarifaManejo || data.tarifa || project.tarifaPorHora || f.tarifaPorHora || 0);

  // --- Filas de trabajadores: en cada día, el trabajador 1..N recibe las horas de los grupos de ese día.
  const slotsPerDay = DAY_KEYS.map((key) => {
    const slots = [];
    const groups = data.dias.filter((e) => e.dia === key).sort((a, b) => b.horas - a.horas);
    for (const g of groups) for (let i = 0; i < g.personas; i++) slots.push(g.horas);
    return slots;
  });
  const rowCount = Math.max(...slotsPerDay.map((s) => s.length));
  const workers = [];
  for (let r = 0; r < rowCount; r++) {
    const hours = slotsPerDay.map((s) => s[r] || 0);
    workers.push({
      name: data.nombres_trabajadores[r] || `Worker ${r + 1}`,
      hours,
      total: hours.reduce((a, b) => a + b, 0),
    });
  }
  const dayTotals = DAY_KEYS.map((_, d) => workers.reduce((a, w) => a + w.hours[d], 0));
  const laborHours = dayTotals.reduce((a, b) => a + b, 0);

  // --- Manejo
  const driving = data.manejo
    .map((e) => ({ dayIndex: DAY_KEYS.indexOf(e.dia), date: dates[DAY_KEYS.indexOf(e.dia)], hours: e.horas, desc: e.descripcion }))
    .sort((a, b) => a.dayIndex - b.dayIndex);
  const drivingHours = driving.reduce((a, e) => a + e.hours, 0);

  // --- Fechas
  const workedIdx = [
    ...dayTotals.map((t, i) => (t > 0 ? i : -1)),
    ...driving.map((e) => e.dayIndex),
  ].filter((i) => i >= 0);
  const firstDay = dates[Math.min(...workedIdx)];
  const lastDay = dates[Math.max(...workedIdx)];

  // --- Renglones del resumen (en centavos)
  const lines = [];
  const laborCents = Math.round(laborHours * rateCents);
  lines.push({ desc: 'Total Labor Hours', hours: laborHours, rateCents, amountCents: laborCents, key: 'labor' });
  if (drivingHours > 0) {
    lines.push({ desc: 'Driving Hours', hours: drivingHours, rateCents: driveRateCents, amountCents: Math.round(drivingHours * driveRateCents), key: 'driving' });
  }
  const expense = (desc, dollars, key) => {
    if (dollars > 0) lines.push({ desc, hours: null, rateCents: null, amountCents: toCents(dollars), key });
  };
  expense('Gas / Fuel', data.gasolina, 'gas');
  expense('Cleaning Supplies / Materials', data.materiales, 'supplies');
  expense('Meals', data.comida, 'meals');
  for (const o of data.otros_gastos) expense(o.descripcion, o.monto, 'other');
  const subtotalCents = lines.reduce((a, l) => a + l.amountCents, 0);

  const po = data.po || project.po || '';
  const invoice = {
    number: formatNumber(config, number, lastDay),
    numberInt: number,
    date: lastDay,
    weekStart,
    weekEnd: dates[6],
    dates,
    firstDay,
    lastDay,
    project: {
      name: project.nombre,
      nameForEmail: project.nombreEnCorreo || titleCase(project.nombre),
      address: project.direccion || '',
      po,
      to: project.para || [],
      cc: project.cc || [],
      known: project.encontrado,
    },
    service: project.servicio || f.servicio || 'Labor',
    rateCents,
    driveRateCents,
    supervisor: project.supervisor || f.supervisor || '',
    sentBy: project.enviadoPor || f.enviadoPor || '',
    status: f.estado || 'PENDING PAYMENT',
    workers,
    dayTotals,
    laborHours,
    driving,
    drivingHours,
    lines,
    subtotalCents,
    totalCents: subtotalCents,
    groups: data.dias,
  };
  invoice.notes = buildNotes(invoice, data);
  invoice.drivingText = buildDrivingText(invoice);
  return invoice;
}

function laborNote(inv) {
  const days = inv.dayTotals.map((t, i) => (t > 0 ? i : -1)).filter((i) => i >= 0);
  const allHours = inv.workers.flatMap((w) => days.map((d) => w.hours[d]));
  const uniform = allHours.every((h) => h === allHours[0]) && allHours[0] > 0;
  if (uniform) {
    const n = inv.workers.length;
    const range = days.length === 1
      ? enDayLabel(inv.dates[days[0]])
      : `${enDayLabel(inv.dates[days[0]])} - ${enDayLabel(inv.dates[days[days.length - 1]])}`;
    const consecutive = days.every((d, i) => i === 0 || d === days[i - 1] + 1);
    const which = consecutive ? range : days.map((d) => enDayShort(d)).join(', ');
    return `${n} ${plural(n, 'worker', 'workers')} x ${hrs(allHours[0])} hrs x ${days.length} ${plural(days.length, 'day', 'days')} (${which}) = ${hrs(inv.laborHours)} labor hrs.`;
  }
  const perDay = days.map((d) => {
    const key = DAY_KEYS[d];
    const groups = inv.groups.filter((g) => g.dia === key).sort((a, b) => b.horas - a.horas);
    const txt = groups.map((g) => `${g.personas} ${plural(g.personas, 'worker', 'workers')} x ${hrs(g.horas)} hrs`).join(' + ');
    return `${enDayLabel(inv.dates[d])}: ${txt}`;
  });
  return `${perDay.join(' | ')} = ${hrs(inv.laborHours)} labor hrs.`;
}

function buildNotes(inv, data) {
  const notes = [laborNote(inv)];
  if (inv.driving.length) {
    const parts = inv.driving.map((e) => `${hrs(e.hours)} hrs${e.desc ? ' ' + e.desc : ''} ${enWeekday(e.date)}`);
    notes.push(`Driving: ${parts.join(' + ')} = ${hrs(inv.drivingHours)} hrs at ${money(inv.driveRateCents).replace(/\.00$/, '')}/hr.`);
  }
  const bits = [];
  const amount = (key) => inv.lines.find((l) => l.key === key)?.amountCents;
  if (amount('meals')) bits.push(`Meals: ${money(amount('meals'))}`);
  if (amount('gas')) bits.push(`Gas: ${money(amount('gas'))}`);
  if (amount('supplies')) bits.push(`Supplies: ${money(amount('supplies'))}`);
  for (const l of inv.lines.filter((x) => x.key === 'other')) bits.push(`${l.desc}: ${money(l.amountCents)}`);
  if (inv.project.po) bits.push(`PO #${inv.project.po}`);
  bits.push(`Status: ${inv.status}.`);
  notes.push(bits.join(' | '));
  for (const n of data.notas) notes.push(n);
  return notes;
}

function buildDrivingText(inv) {
  if (!inv.driving.length) return null;
  return {
    detail: inv.driving.map((e) => `${enDayLabel(e.date)}: ${hrs(e.hours)} hrs${e.desc ? ' ' + e.desc : ''}`).join('  |  '),
    total: `${hrs(inv.drivingHours)} driving hrs total (separate from ${hrs(inv.laborHours)} labor hrs)`,
  };
}

/** Datos para guardar y poder corregir después (la semana queda fija). */
export function dataForCorrections(data, invoice) {
  return { ...data, fecha_referencia: invoice.weekStart, proyecto: invoice.project.name };
}
