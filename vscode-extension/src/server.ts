import * as vscode from 'vscode';
import { ChildProcess, spawn } from 'child_process';

export class ServerManager {
    private process: ChildProcess | undefined;
    private outputChannel: vscode.OutputChannel;

    constructor(private context: vscode.ExtensionContext) {
        this.outputChannel = vscode.window.createOutputChannel('ReIN Server');
    }

    async start(): Promise<void> {
        if (this.process) {
            vscode.window.showInformationMessage('ReIN server is already running.');
            return;
        }

        const config = vscode.workspace.getConfiguration('rein');
        const pythonPath = config.get<string>('pythonPath', 'python');
        const extraArgs = config.get<string[]>('serverArgs', []);

        const args = ['-m', 'rein', 'server', ...extraArgs];

        this.outputChannel.show(true);
        this.outputChannel.appendLine(`Starting ReIN server: ${pythonPath} ${args.join(' ')}`);

        try {
            this.process = spawn(pythonPath, args, {
                cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
                env: { ...process.env },
            });

            this.process.stdout?.on('data', (data: Buffer) => {
                this.outputChannel.append(data.toString());
            });

            this.process.stderr?.on('data', (data: Buffer) => {
                this.outputChannel.append(data.toString());
            });

            this.process.on('close', (code) => {
                this.outputChannel.appendLine(`\nServer exited with code ${code}`);
                this.process = undefined;
            });

            this.process.on('error', (err) => {
                vscode.window.showErrorMessage(`Failed to start ReIN server: ${err.message}`);
                this.process = undefined;
            });

            // Wait briefly for server to start
            await new Promise(resolve => setTimeout(resolve, 2000));
            vscode.window.showInformationMessage('ReIN server started.');
        } catch (err: any) {
            vscode.window.showErrorMessage(`Failed to start ReIN server: ${err.message}`);
        }
    }

    stop(): void {
        if (this.process) {
            this.process.kill();
            this.process = undefined;
            this.outputChannel.appendLine('\nServer stopped.');
            vscode.window.showInformationMessage('ReIN server stopped.');
        }
    }

    isRunning(): boolean {
        return this.process !== undefined;
    }
}
