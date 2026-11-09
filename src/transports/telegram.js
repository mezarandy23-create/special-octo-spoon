// Plan B (más fácil y 100% oficial): bot de Telegram.
// Se crea en 1 minuto con @BotFather y no hay riesgo de bloqueo. No necesita URL pública.

const API = 'https://api.telegram.org';

export async function startTelegram({ bot, token, log }) {
  const call = async (method, body) => {
    const res = await fetch(`${API}/bot${token}/${method}`, {
      method: 'POST',
      ...(body instanceof FormData ? { body } : { headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) }),
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(`Telegram ${method}: ${json.description || res.status}`);
    return json.result;
  };

  const me = await call('getMe');
  log.info(`✅ Telegram conectado como @${me.username}. Esperando mensajes...`);

  const download = async (fileId) => {
    const f = await call('getFile', { file_id: fileId });
    const res = await fetch(`${API}/file/bot${token}/${f.file_path}`);
    if (!res.ok) throw new Error(`No pude descargar el archivo de Telegram (${res.status})`);
    return Buffer.from(await res.arrayBuffer());
  };

  const send = async (chatId, r) => {
    if (r.document) {
      const form = new FormData();
      form.append('chat_id', String(chatId));
      form.append('caption', r.caption || '');
      form.append('document', new Blob([r.document], { type: r.mimetype || 'application/pdf' }), r.filename);
      await call('sendDocument', form);
    } else if (r.text) {
      // En Telegram mandamos texto simple (sin los * de negritas de WhatsApp).
      await call('sendMessage', { chat_id: chatId, text: r.text.replace(/\*/g, '') });
    }
  };

  const onMessage = async (m) => {
    if (!m || m.chat?.type !== 'private') return;
    const chat = { key: `tg:${m.chat.id}`, altKeys: [], phones: [], name: [m.from?.first_name, m.from?.last_name].filter(Boolean).join(' ') };
    const attachments = [];
    if (m.photo?.length) {
      attachments.push({ filename: 'recibo.jpg', contentType: 'image/jpeg', content: await download(m.photo[m.photo.length - 1].file_id) });
    } else if (m.document && /^image\/|^application\/pdf$/.test(m.document.mime_type || '')) {
      attachments.push({ filename: m.document.file_name || 'recibo', contentType: m.document.mime_type, content: await download(m.document.file_id) });
    }
    const text = m.text || m.caption || '';
    if (!text && !attachments.length) return;

    const typing = setInterval(() => call('sendChatAction', { chat_id: m.chat.id, action: 'typing' }).catch(() => {}), 4500);
    call('sendChatAction', { chat_id: m.chat.id, action: 'typing' }).catch(() => {});
    try {
      const replies = await bot.handle(chat, { id: `tg:${m.chat.id}:${m.message_id}`, text, attachments });
      for (const r of replies) await send(m.chat.id, r);
    } finally {
      clearInterval(typing);
    }
  };

  let offset = 0;
  (async function loop() {
    for (;;) {
      try {
        const updates = await call('getUpdates', { offset, timeout: 50, allowed_updates: ['message'] });
        for (const u of updates) {
          offset = u.update_id + 1;
          onMessage(u.message).catch((err) => log.error('Error con un mensaje de Telegram:', err));
        }
      } catch (err) {
        log.warn(`Telegram: ${err.message}. Reintento en 5s...`);
        await new Promise((r) => setTimeout(r, 5000));
      }
    }
  })();
}
