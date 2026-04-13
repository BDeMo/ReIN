import * as vscode from 'vscode';
import { ChatViewProvider } from './chatView';
import { ServerManager } from './server';

let serverManager: ServerManager | undefined;

export function activate(context: vscode.ExtensionContext) {
    const serverMgr = new ServerManager(context);
    serverManager = serverMgr;

    const chatProvider = new ChatViewProvider(context, serverMgr);

    // Register webview provider
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('rein.chatView', chatProvider, {
            webviewOptions: { retainContextWhenHidden: true },
        })
    );

    // Commands
    context.subscriptions.push(
        vscode.commands.registerCommand('rein.startServer', () => serverMgr.start()),
        vscode.commands.registerCommand('rein.stopServer', () => serverMgr.stop()),
        vscode.commands.registerCommand('rein.openChat', () => {
            vscode.commands.executeCommand('rein.chatView.focus');
        }),
        vscode.commands.registerCommand('rein.askAboutFile', (uri?: vscode.Uri) => {
            const filePath = uri?.fsPath || vscode.window.activeTextEditor?.document.uri.fsPath;
            if (filePath) {
                chatProvider.sendMessage(`Read and explain this file: ${filePath}`);
            }
        }),
        vscode.commands.registerCommand('rein.askAboutSelection', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const selection = editor.document.getText(editor.selection);
                const filePath = editor.document.uri.fsPath;
                if (selection) {
                    chatProvider.sendMessage(
                        `Explain this code from ${filePath}:\n\`\`\`\n${selection}\n\`\`\``
                    );
                }
            }
        })
    );
}

export function deactivate() {
    serverManager?.stop();
}
