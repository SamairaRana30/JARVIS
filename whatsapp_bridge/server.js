/**
 * whatsapp_bridge/server.js — Local WhatsApp bridge for Jarvis.
 *
 * Uses whatsapp-web.js (Puppeteer/real Chrome) — far more reliable than
 * Baileys since it runs actual WhatsApp Web in a headless browser.
 *
 * Setup:
 *   cd whatsapp_bridge
 *   npm install          (downloads Chromium automatically)
 *   node server.js
 *   → Scan the QR code with your WhatsApp phone
 *     (WhatsApp → Settings → Linked Devices → Link a Device)
 *
 * API:
 *   GET  /status          → { connected, messageCount }
 *   GET  /messages?n=10   → last N messages
 *   GET  /unread_count    → { count }
 *   POST /mark_read       → body: { "chatId": "..." }  (optional filter)
 *   POST /send            → body: { "to": "...", "text": "..." }
 */

const express    = require("express");
const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode     = require("qrcode-terminal");
const path       = require("path");
const fs         = require("fs");

const PORT      = process.env.BRIDGE_PORT || 5765;
const LOG_FILE  = path.join(__dirname, "bridge.log");

const app = express();
app.use(express.json());

// In-memory message store (last 200 messages)
const messages = [];
let connected  = false;

function log(msg) {
    const line = `[${new Date().toISOString()}] ${msg}\n`;
    fs.appendFileSync(LOG_FILE, line);
    console.log(msg);
}

// ---------------------------------------------------------------------------
// WhatsApp client
// ---------------------------------------------------------------------------

const BUNDLED_CHROME = "C:\\Users\\samai\\.cache\\puppeteer\\chrome\\win64-146.0.7680.31\\chrome-win64\\chrome.exe";

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: path.join(__dirname, "auth_data") }),
    puppeteer: {
        headless: true,
        executablePath: BUNDLED_CHROME,
        args: [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
        ],
    },
    webVersionCache: {
        type: "remote",
        remotePath: "https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.3000.1023223821-alpha.html",
    },
});

client.on("qr", (qr) => {
    log("Scan this QR code with WhatsApp (Settings → Linked Devices → Link a Device):");
    qrcode.generate(qr, { small: true });
});

client.on("ready", () => {
    connected = true;
    log(`WhatsApp connected as: ${client.info?.pushname || "unknown"}`);
});

client.on("disconnected", (reason) => {
    connected = false;
    log(`WhatsApp disconnected: ${reason}. Reinitializing...`);
    client.initialize().catch(err => log(`Reinit error: ${err.message}`));
});

client.on("message", async (msg) => {
    if (msg.fromMe) return;
    let name = msg._data?.notifyName || msg.from.split("@")[0];
    try {
        const contact = await msg.getContact();
        name = contact.pushname || contact.name || name;
    } catch (_) {}

    const entry = {
        id:        msg.id._serialized,
        from:      msg.from,
        name,
        text:      msg.body || "[media]",
        timestamp: msg.timestamp,
        read:      false,
    };
    messages.unshift(entry);
    if (messages.length > 200) messages.pop();
    log(`Message from ${name}: ${entry.text.substring(0, 60)}`);
});

// ---------------------------------------------------------------------------
// REST API
// ---------------------------------------------------------------------------

app.get("/status", (req, res) => {
    res.json({ connected, messageCount: messages.length });
});

app.get("/messages", (req, res) => {
    const n          = parseInt(req.query.n) || 10;
    const only_unread= req.query.unread === "true";
    let result = only_unread ? messages.filter(m => !m.read) : messages;
    res.json(result.slice(0, n));
});

app.get("/unread_count", (req, res) => {
    res.json({ count: messages.filter(m => !m.read).length });
});

app.post("/mark_read", (req, res) => {
    const { chatId } = req.body;
    messages.forEach(m => {
        if (!chatId || m.from === chatId) m.read = true;
    });
    res.json({ ok: true });
});

app.post("/send", async (req, res) => {
    const { to, text } = req.body;
    if (!connected) return res.status(503).json({ error: "Not connected" });
    try {
        await client.sendMessage(to, text);
        res.json({ ok: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

app.listen(PORT, () => {
    log(`Jarvis WhatsApp bridge on http://localhost:${PORT}`);
    log("Starting WhatsApp client (this may take 30-60 seconds first time)...");
    client.initialize().catch(err => log(`Init error: ${err.message}`));
});
