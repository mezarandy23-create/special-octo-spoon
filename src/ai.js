// La IA (Claude) SOLO interpreta el mensaje y devuelve datos estructurados.
// Las cuentas, el PDF y el borrador los hace el programa, así que los totales siempre cuadran.

import Anthropic from '@anthropic-ai/sdk';
import { DAY_KEYS, esLong, esWeekday } from './format.js';

const DEFAULT_MODEL = 'claude-opus-5-5';
const FALLBACK_BETA = 'server-side-fallback-2026-07-01';

const str = { type: 'string' };
const num = { type: 'number' };

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [
    'accion', 'respuesta', 'proyecto', 'fecha_referencia', 'dias', 'nombres_trabajadores', 'manejo',
    'gasolina', 'materiales', 'comida', 'otros_gastos', 'po', 'tarifa', 'notas', 'numero_siguiente',
  ],
  properties: {
    accion: { type: 'string', enum: ['crear', 'corregir', 'borrar', 'numero', 'preguntar', 'otro'] },
    respuesta: { type: 'string', description: 'Solo para "preguntar" y "otro": texto corto en español para contestar. Vacío en los demás casos.' },
    proyecto: { type: 'string', description: 'Nombre del proyecto tal como aparece en la lista, o "" si no se menciona.' },
    fecha_referencia: { type: 'string', description: 'YYYY-MM-DD de cualquier día de la semana a facturar, solo si el mensaje la indica. Si no, "".' },
    dias: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['dia', 'personas', 'horas'],
        properties: {
          dia: { type: 'string', enum: DAY_KEYS },
          personas: { type: 'integer' },
          horas: { type: 'number', description: 'Horas que trabajó CADA persona de este grupo ese día.' },
        },
      },
    },
    nombres_trabajadores: { type: 'array', items: str },
    manejo: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['dia', 'horas', 'descripcion'],
        properties: {
          dia: { type: 'string', enum: DAY_KEYS },
          horas: num,
          descripcion: { type: 'string', description: 'En inglés: "outbound" (ida), "return" (regreso) u otro texto corto.' },
        },
      },
    },
    gasolina: num,
    materiales: num,
    comida: num,
    otros_gastos: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['descripcion', 'monto'],
        properties: { descripcion: { type: 'string', description: 'En inglés, corto.' }, monto: num },
      },
    },
    po: str,
    tarifa: num,
    notas: { type: 'array', items: str },
    numero_siguiente: { type: 'integer', description: 'Solo para accion "numero"; si no, 0.' },
  },
};

function systemPrompt(config) {
  const company = config.empresa?.nombreCorto || config.empresa?.nombre || 'la empresa';
  return `Eres el asistente de facturación de ${company}, una empresa de limpieza. Te escriben por WhatsApp en español informal (a veces con errores, abreviaturas o dictado por voz) para pedir el invoice semanal de horas trabajadas. Tu único trabajo es convertir el mensaje en datos con el formato pedido. El programa hace todas las cuentas, el PDF y el borrador del correo, así que nunca calcules totales.

Acciones:
- "crear": el mensaje describe el trabajo de una semana (días, personas, horas) para hacer un invoice nuevo.
- "corregir": hay un invoice anterior y el mensaje lo cambia ("el jueves fueron 9 horas", "quita la comida", "eran 4 personas", "agrégale los recibos", "es de la semana pasada", "inténtalo otra vez"). Devuelve los datos COMPLETOS ya corregidos, copiando del invoice anterior todo lo que no cambia (incluida su fecha_referencia, salvo que pidan otra semana).
- "borrar": pide borrar o cancelar el último invoice o borrador.
- "numero": indica cuál debe ser el número del próximo invoice (ej. "el siguiente invoice es el 60") -> numero_siguiente.
- "preguntar": falta un dato indispensable o algo es ambiguo (un día sin horas o sin cantidad de personas). Haz una pregunta corta en "respuesta". No inventes horas ni personas.
- "otro": saludos, dudas o algo que no es un invoice. Contesta breve en "respuesta"; si sirve, explica cómo pedir un invoice (ej. "10 horas el martes, 8 el jueves y 4 el viernes; 3 personas martes y jueves y 7 el viernes").

Cómo llenar los datos:
- dias: una entrada por cada grupo (día, personas, horas por persona). Ejemplo: "10 horas el martes, 8 el jueves y 4 el viernes, 3 personas martes y jueves y 7 personas el viernes" -> mar 3 personas 10 h; jue 3 personas 8 h; vie 7 personas 4 h. Si un mismo día hay grupos con horas distintas ("2 de 10 horas y 1 de 6 el lunes") usa varias entradas para ese día. "De lunes a viernes" = lun, mar, mie, jue, vie. Las horas pueden tener decimales ("7 y media" = 7.5).
- manejo: horas de manejo o viaje ("4 horas de ida el lunes y 4 de regreso el viernes"). No son horas de trabajo: nunca las pongas en "dias".
- gasolina, materiales (cleaning supplies, productos, químicos), comida (meals, comidas): montos en dólares; 0 si no se mencionan.
- otros_gastos: cualquier otro gasto con monto (descripción corta en inglés).
- fecha_referencia: solo si el mensaje indica fechas o una semana concreta ("semana del 2 de noviembre", "el 3, 5 y 6 de noviembre", "la semana pasada" = hoy menos 7 días). Si no, "" y el programa elige la semana más reciente.
- proyecto: el nombre exacto de la lista si se menciona o se deduce; "" si no se menciona. Si es un proyecto que no está en la lista, escríbelo tal cual.
- po: solo si menciona número de PO u orden de compra. tarifa: solo si menciona una tarifa por hora distinta; si no, 0.
- nombres_trabajadores: solo si da los nombres, en orden; si no, [].
- notas: notas extra en inglés que pidan agregar al invoice; normalmente [].
- Para "crear" y "corregir" deja "respuesta" vacío. Para acciones que no son "numero", numero_siguiente = 0.`;
}

function userPrompt({ text, today, config, previous, pendingReceipts, pendingQuestion }) {
  const projects = (config.proyectos || []).map((p, i) => `${p.nombre}${i === 0 ? ' (predeterminado)' : ''}`).join(', ') || '(ninguno)';
  const lines = [
    `Hoy es ${esWeekday(today)} ${esLong(today)} (${today}).`,
    `Proyectos: ${projects}.`,
    previous
      ? `Invoice anterior de este chat: ${previous.number}, semana que empieza ${previous.data.fecha_referencia}. Datos: ${JSON.stringify(previous.data)}`
      : 'Invoice anterior de este chat: ninguno.',
    `Recibos (fotos o PDF) guardados esperando invoice: ${pendingReceipts}.`,
  ];
  if (pendingQuestion) {
    lines.push(`Contexto: antes te escribieron «${pendingQuestion.userText}» y tú preguntaste «${pendingQuestion.question}». El mensaje nuevo probablemente es la respuesta; combínalos.`);
  }
  lines.push('', 'Mensaje:', '"""', text.slice(0, 4000), '"""');
  return lines.join('\n');
}

export class InvoiceAI {
  constructor({ apiKey, model, effort, fallback, logger } = {}) {
    this.client = new Anthropic(apiKey ? { apiKey } : {});
    this.model = model || DEFAULT_MODEL;
    this.effort = effort || 'medium';
    this.useFallback = fallback !== 'off';
    this.logger = logger;
  }

  async request(params) {
    if (this.useFallback) {
      try {
        return await this.client.beta.messages.create({ ...params, betas: [FALLBACK_BETA], fallbacks: 'default' });
      } catch (err) {
        // Si la cuenta no acepta el "fallback" automático, se reintenta sin él.
        if (!(err instanceof Anthropic.BadRequestError)) throw err;
        this.logger?.warn?.(`La API rechazó el respaldo automático (fallbacks); sigo sin él. Detalle: ${err.message}`);
        this.useFallback = false;
      }
    }
    return this.client.messages.create(params);
  }

  /** Devuelve el objeto con "accion" y los datos, o lanza un Error con mensaje en español. */
  async interpret({ text, today, config, previous = null, pendingReceipts = 0, pendingQuestion = null }) {
    let response;
    try {
      response = await this.request({
        model: this.model,
        max_tokens: 16000,
        system: systemPrompt(config),
        output_config: { effort: this.effort, format: { type: 'json_schema', schema: SCHEMA } },
        messages: [{ role: 'user', content: userPrompt({ text, today, config, previous, pendingReceipts, pendingQuestion }) }],
      });
    } catch (err) {
      if (err instanceof Anthropic.AuthenticationError) throw new Error('La clave de Anthropic (ANTHROPIC_API_KEY) no es válida.');
      if (err instanceof Anthropic.PermissionDeniedError) throw new Error('La clave de Anthropic no tiene permiso para este modelo.');
      if (err instanceof Anthropic.RateLimitError) throw new Error('La IA está saturada o se acabó el límite. Intenta en un minuto.');
      if (err instanceof Anthropic.BadRequestError) throw new Error(`La IA rechazó la solicitud: ${err.message}. Si dice algo de "credit balance", hay que recargar saldo en console.anthropic.com.`);
      if (err instanceof Anthropic.APIConnectionError) throw new Error('No hay conexión con la IA (¿internet?).');
      if (err instanceof Anthropic.APIError) throw new Error(`Error de la IA (${err.status}): ${err.message}`);
      throw err;
    }

    if (response.stop_reason === 'refusal') throw new Error('La IA no quiso procesar ese mensaje. Escríbelo de otra forma.');
    if (response.stop_reason === 'max_tokens') throw new Error('La respuesta de la IA quedó incompleta. Intenta con un mensaje más corto.');
    const block = response.content.find((b) => b.type === 'text');
    if (!block) throw new Error('La IA no devolvió datos.');
    try {
      return JSON.parse(block.text);
    } catch {
      throw new Error('La IA devolvió datos con formato inválido. Intenta otra vez.');
    }
  }
}
