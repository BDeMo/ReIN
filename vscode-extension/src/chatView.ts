import * as vscode from 'vscode';
import WebSocket from 'ws';
import { ServerManager } from './server';

export class ChatViewProvider implements vscode.WebviewViewProvider {
    private webviewView?: vscode.WebviewView;
    private ws?: WebSocket;
    private pendingMessage?: string;

    constructor(
        private context: vscode.ExtensionContext,
        private serverManager: ServerManager
    ) {}

    resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ) {
        this.webviewView = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
        };

        webviewView.webview.html = this.getHtml();

        webviewView.webview.onDidReceiveMessage(async (msg) => {
            switch (msg.type) {
                case 'send':
                    await this.handleSend(msg.text);
                    break;
                case 'connect':
                    await this.connect();
                    break;
                case 'startServer':
                    await this.serverManager.start();
                    await this.connect();
                    break;
            }
        });

        // Auto-connect
        this.connect();

        // Send pending message if any
        if (this.pendingMessage) {
            const msg = this.pendingMessage;
            this.pendingMessage = undefined;
            setTimeout(() => this.handleSend(msg), 1000);
        }
    }

    async sendMessage(text: string) {
        if (this.webviewView && this.ws?.readyState === WebSocket.OPEN) {
            this.webviewView.webview.postMessage({ type: 'setInput', text });
            await this.handleSend(text);
        } else {
            this.pendingMessage = text;
            vscode.commands.executeCommand('rein.chatView.focus');
        }
    }

    private async connect() {
        const config = vscode.workspace.getConfiguration('rein');
        const url = config.get<string>('serverUrl', 'ws://localhost:8765/ws/chat');

        if (this.ws) {
            this.ws.close();
            this.ws = undefined;
        }

        try {
            this.ws = new WebSocket(url);

            this.ws.on('open', () => {
                this.postMessage({ type: 'status', status: 'connected' });
            });

            this.ws.on('message', (data: Buffer) => {
                try {
                    const event = JSON.parse(data.toString());
                    this.postMessage({ type: 'event', event });
                } catch {
                    // ignore parse errors
                }
            });

            this.ws.on('close', () => {
                this.postMessage({ type: 'status', status: 'disconnected' });
                this.ws = undefined;
            });

            this.ws.on('error', () => {
                this.postMessage({ type: 'status', status: 'error' });
                this.ws = undefined;
            });
        } catch {
            this.postMessage({ type: 'status', status: 'error' });
        }
    }

    private async handleSend(text: string) {
        if (!text.trim()) { return; }

        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            // Try auto-start
            const config = vscode.workspace.getConfiguration('rein');
            if (config.get<boolean>('autoStartServer', false)) {
                await this.serverManager.start();
                await this.connect();
                await new Promise(resolve => setTimeout(resolve, 1000));
            }

            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
                this.postMessage({ type: 'status', status: 'disconnected' });
                return;
            }
        }

        this.postMessage({ type: 'userMessage', text });
        this.ws.send(JSON.stringify({ type: 'message', content: text }));
    }

    private postMessage(msg: any) {
        this.webviewView?.webview.postMessage(msg);
    }

    private getHtml(): string {
        return /*html*/ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--vscode-foreground);
    background: var(--vscode-sideBar-background);
    display: flex;
    flex-direction: column;
    height: 100vh;
}

#status-bar {
    padding: 6px 12px;
    font-size: 11px;
    color: var(--vscode-descriptionForeground);
    border-bottom: 1px solid var(--vscode-panel-border);
    display: flex;
    align-items: center;
    gap: 6px;
}

#status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--vscode-charts-red);
}

#status-dot.connected { background: var(--vscode-charts-green); }

#messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
}

.message {
    margin-bottom: 12px;
    line-height: 1.5;
}

.message.user {
    background: var(--vscode-input-background);
    border: 1px solid var(--vscode-input-border);
    border-radius: 8px;
    padding: 8px 12px;
}

.message.user::before {
    content: '❯ ';
    color: var(--vscode-charts-green);
    font-weight: bold;
}

.message.assistant {
    padding: 4px 0;
}

.message.assistant pre {
    background: var(--vscode-textCodeBlock-background);
    border-radius: 4px;
    padding: 8px;
    overflow-x: auto;
    margin: 4px 0;
}

.message.assistant code {
    font-family: var(--vscode-editor-font-family);
    font-size: var(--vscode-editor-font-size);
}

.message.assistant p { margin: 4px 0; }
.message.assistant ul, .message.assistant ol { padding-left: 20px; margin: 4px 0; }
.message.assistant h1, .message.assistant h2, .message.assistant h3 {
    margin: 8px 0 4px;
    color: var(--vscode-foreground);
}
.message.assistant h1 { font-size: 1.3em; }
.message.assistant h2 { font-size: 1.15em; }
.message.assistant h3 { font-size: 1.05em; }

.tool-call {
    margin: 6px 0;
    padding: 6px 10px;
    border-left: 3px solid var(--vscode-charts-yellow);
    background: var(--vscode-input-background);
    border-radius: 0 4px 4px 0;
    font-size: 12px;
}

.tool-call .tool-name {
    color: var(--vscode-charts-yellow);
    font-weight: bold;
}

.tool-result {
    margin: 4px 0;
    padding: 4px 10px;
    font-size: 11px;
    color: var(--vscode-descriptionForeground);
    border-left: 3px solid var(--vscode-charts-green);
}

.tool-result.error {
    border-left-color: var(--vscode-charts-red);
    color: var(--vscode-errorForeground);
}

.usage {
    font-size: 11px;
    color: var(--vscode-descriptionForeground);
    margin: 4px 0;
}

#input-area {
    border-top: 1px solid var(--vscode-panel-border);
    padding: 8px;
    display: flex;
    gap: 6px;
}

#input {
    flex: 1;
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border);
    border-radius: 4px;
    padding: 6px 10px;
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    outline: none;
    resize: none;
    min-height: 32px;
    max-height: 120px;
}

#input:focus {
    border-color: var(--vscode-focusBorder);
}

#send-btn {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    border-radius: 4px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 13px;
}

#send-btn:hover {
    background: var(--vscode-button-hoverBackground);
}

#send-btn:disabled {
    opacity: 0.5;
    cursor: default;
}

.connect-prompt {
    text-align: center;
    padding: 20px;
    color: var(--vscode-descriptionForeground);
}

.connect-prompt button {
    margin-top: 8px;
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
    cursor: pointer;
}
</style>
</head>
<body>
    <div id="status-bar">
        <span id="status-dot"></span>
        <span id="status-text">Disconnected</span>
    </div>
    <div id="messages">
        <div class="connect-prompt" id="connect-prompt">
            <p>Connect to ReIN server to start chatting.</p>
            <button onclick="tryConnect()">Connect</button>
            <button onclick="startServer()">Start Server</button>
        </div>
    </div>
    <div id="input-area">
        <textarea id="input" placeholder="Ask ReIN..." rows="1"></textarea>
        <button id="send-btn" onclick="send()">Send</button>
    </div>

<script>
const vscode = acquireVsCodeApi();
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const connectPrompt = document.getElementById('connect-prompt');
const sendBtn = document.getElementById('send-btn');

let currentAssistant = null;
let textBuffer = '';
let isStreaming = false;

function tryConnect() { vscode.postMessage({ type: 'connect' }); }
function startServer() { vscode.postMessage({ type: 'startServer' }); }

function send() {
    const text = inputEl.value.trim();
    if (!text || isStreaming) return;
    vscode.postMessage({ type: 'send', text });
    inputEl.value = '';
    inputEl.style.height = '32px';
}

inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
    }
});

inputEl.addEventListener('input', () => {
    inputEl.style.height = '32px';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
});

function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addUserMessage(text) {
    const div = document.createElement('div');
    div.className = 'message user';
    div.textContent = text;
    messagesEl.appendChild(div);
    currentAssistant = null;
    textBuffer = '';
    scrollToBottom();
}

function ensureAssistantMessage() {
    if (!currentAssistant) {
        currentAssistant = document.createElement('div');
        currentAssistant.className = 'message assistant';
        messagesEl.appendChild(currentAssistant);
    }
    return currentAssistant;
}

function renderMarkdown(text) {
    // Simple markdown rendering
    let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // Code blocks
    html = html.replace(/\`\`\`(\w*)\n([\s\S]*?)\`\`\`/g, '<pre><code>$2</code></pre>');
    // Inline code
    html = html.replace(/\`([^\`]+)\`/g, '<code>$1</code>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    // Lists
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    // Paragraphs
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p><\/p>/g, '');

    return html;
}

function handleEvent(event) {
    const { type, data } = event;
    const el = ensureAssistantMessage();

    switch (type) {
        case 'text_delta':
            textBuffer += (data.text || '');
            // Re-render all accumulated text as markdown
            // Find or create the text content span
            let textEl = el.querySelector('.assistant-text');
            if (!textEl) {
                textEl = document.createElement('div');
                textEl.className = 'assistant-text';
                el.appendChild(textEl);
            }
            textEl.innerHTML = renderMarkdown(textBuffer);
            isStreaming = true;
            sendBtn.disabled = true;
            break;

        case 'tool_use': {
            const toolDiv = document.createElement('div');
            toolDiv.className = 'tool-call';
            const preview = JSON.stringify(data.input || {}).slice(0, 150);
            toolDiv.innerHTML = '<span class="tool-name">⚡ ' + (data.name || '?') + '</span> <span style="opacity:0.6">' + preview + '</span>';
            el.appendChild(toolDiv);
            break;
        }

        case 'tool_result': {
            const resultDiv = document.createElement('div');
            resultDiv.className = 'tool-result' + (data.is_error ? ' error' : '');
            const preview = (data.result || '').slice(0, 200);
            resultDiv.textContent = (data.is_error ? '✗ ' : '✓ ') + preview;
            el.appendChild(resultDiv);
            break;
        }

        case 'usage': {
            const usageDiv = document.createElement('div');
            usageDiv.className = 'usage';
            usageDiv.textContent = '[' + (data.input_tokens || 0) + ' in / ' + (data.output_tokens || 0) + ' out tokens]';
            el.appendChild(usageDiv);
            break;
        }

        case 'turn_complete':
            currentAssistant = null;
            textBuffer = '';
            isStreaming = false;
            sendBtn.disabled = false;
            break;

        case 'error': {
            const errDiv = document.createElement('div');
            errDiv.style.color = 'var(--vscode-errorForeground)';
            errDiv.textContent = 'Error: ' + (data.message || 'Unknown error');
            el.appendChild(errDiv);
            isStreaming = false;
            sendBtn.disabled = false;
            break;
        }
    }
    scrollToBottom();
}

window.addEventListener('message', (e) => {
    const msg = e.data;
    switch (msg.type) {
        case 'status':
            if (msg.status === 'connected') {
                statusDot.className = 'connected';
                statusText.textContent = 'Connected';
                connectPrompt.style.display = 'none';
            } else {
                statusDot.className = '';
                statusText.textContent = msg.status === 'error' ? 'Connection failed' : 'Disconnected';
                connectPrompt.style.display = 'block';
            }
            break;
        case 'event':
            handleEvent(msg.event);
            break;
        case 'userMessage':
            addUserMessage(msg.text);
            break;
        case 'setInput':
            inputEl.value = msg.text;
            break;
    }
});
</script>
</body>
</html>`;
    }
}
