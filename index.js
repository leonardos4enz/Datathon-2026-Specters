const WEBHOOK_URL = 'https://n8n-n8n.ppnoc4.easypanel.host/webhook/b433705d-ac26-4c0a-a4f5-4a945a31efb9';

const USER = {
  id: 'USR-00001',
  nombre: 'User',
};

// Se genera una sola vez por sesión de chat
const SESSION_ID = Math.floor(1000000000 + Math.random() * 9000000000).toString();

const messagesEl = document.getElementById('messages');
const msgInput = document.getElementById('msgInput');
const sendBtn = document.getElementById('sendBtn');

function appendMessage(text, sender) {
  const div = document.createElement('div');
  div.classList.add('message', sender === 'bot' ? 'havi' : 'user');
  const bubble = document.createElement('div');
  bubble.classList.add('bubble');
  bubble.textContent = text;
  div.appendChild(bubble);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendTyping() {
  const div = document.createElement('div');
  div.classList.add('message', 'havi');
  div.id = 'typing';
  const bubble = document.createElement('div');
  bubble.classList.add('bubble');
  bubble.textContent = '...';
  div.appendChild(bubble);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('typing');
  if (el) el.remove();
}

async function sendMessage() {
  const text = msgInput.value.trim();
  if (!text) return;

  appendMessage(text, 'user');
  msgInput.value = '';
  sendBtn.disabled = true;
  appendTyping();

  try {
    const res = await fetch(WEBHOOK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: SESSION_ID,
        usuario_id: USER.id,
        nombre: USER.nombre,
        mensaje: text,
      }),
    });

    const data = await res.json();
    removeTyping();

    const reply = data.output ?? data.message ?? data.text ?? data.response ?? JSON.stringify(data);
    appendMessage(reply, 'bot');
  } catch (err) {
    removeTyping();
    appendMessage('No pude conectarme con HAVI. Intenta de nuevo.', 'bot');
  } finally {
    sendBtn.disabled = false;
    msgInput.focus();
  }
}

sendBtn.addEventListener('click', sendMessage);
msgInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMessage();
});

appendMessage('¡Hola! Soy HAVI, tu asistente financiero. ¿En qué te puedo ayudar hoy?', 'bot');