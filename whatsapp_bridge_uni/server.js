const express    = require("express");
const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode     = require("qrcode-terminal");
const path       = require("path");
const fs         = require("fs");

const PORT     = 5766;   // UNI bridge — different port from personal (5765)
const LOG_FILE = path.join(__dirname, "bridge.log");

const app = express();
app.use(express.json());
const messages = [];
let connected  = false;

function log(msg) {
    const line = `[${new Date().toISOString()}] ${msg}\n`;
    fs.appendFileSync(LOG_FILE, line);
    console.log(msg);
}

const BUNDLED_CHROME = "C:\\Users\\samai\\.cache\\puppeteer\\chrome\\win64-146.0.7680.31\\chrome-win64\\chrome.exe";

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: path.join(__dirname, "auth_data_uni") }),
    puppeteer: {
        headless: true,
        executablePath: BUNDLED_CHROME,
        args: ["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage",
               "--no-first-run","--disable-gpu","--disable-extensions",
               "--disable-background-networking","--disable-sync"],
    },
    webVersionCache: {
        type: "remote",
        remotePath: "https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.3000.1023223821-alpha.html",
    },
});

client.on("qr", qr => { log("Scan QR with UNI WhatsApp:"); qrcode.generate(qr, { small: true }); });
client.on("ready", () => { connected = true; log(`UNI WhatsApp connected as: ${client.info?.pushname}`); });
client.on("disconnected", reason => {
    connected = false; log(`Disconnected: ${reason}. Reconnecting...`);
    setTimeout(() => client.initialize().catch(e => log(e.message)), 5000);
});

client.on("message", async msg => {
    if (msg.fromMe) return;
    let name = msg._data?.notifyName || msg.from.split("@")[0];
    try { const c = await msg.getContact(); name = c.pushname || c.name || name; } catch (_) {}
    const entry = { id: msg.id._serialized, from: msg.from, name,
                    text: msg.body || "[media]", timestamp: msg.timestamp, read: false };
    messages.unshift(entry);
    if (messages.length > 200) messages.pop();
    log(`[UNI] ${name}: ${entry.text.substring(0, 60)}`);
});

app.get("/status",       (req, res) => res.json({ connected, messageCount: messages.length }));
app.get("/messages",     (req, res) => {
    const n = parseInt(req.query.n) || 10;
    const unread = req.query.unread === "true";
    res.json((unread ? messages.filter(m => !m.read) : messages).slice(0, n));
});
app.get("/unread_count", (req, res) => res.json({ count: messages.filter(m => !m.read).length }));
app.post("/mark_read",   (req, res) => {
    const { chatId } = req.body;
    messages.forEach(m => { if (!chatId || m.from === chatId) m.read = true; });
    res.json({ ok: true });
});
app.post("/send", async (req, res) => {
    if (!connected) return res.status(503).json({ error: "Not connected" });
    try { await client.sendMessage(req.body.to, req.body.text); res.json({ ok: true }); }
    catch (e) { res.status(500).json({ error: e.message }); }
});

app.listen(PORT, () => {
    log(`UNI WhatsApp bridge on http://localhost:${PORT}`);
    client.initialize().catch(e => log(`Init error: ${e.message}`));
});
