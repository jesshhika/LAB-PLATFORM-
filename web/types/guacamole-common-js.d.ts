declare module "guacamole-common-js" {
  export interface Tunnel {
    connect(data?: string): void;
    disconnect(): void;
  }

  export interface Status {
    code: number;
    message?: string;
  }

  export interface MouseState {
    x: number;
    y: number;
    left: boolean;
    middle: boolean;
    right: boolean;
    up: boolean;
    down: boolean;
    deltaY: number;
    deltaX: number;
  }

  export interface InputStream {}

  export interface StringReader {
    ontext: (text: string) => void;
    onend: () => void;
  }

  export interface StringWriter {
    sendText(text: string): void;
    sendEnd(): void;
  }

  export interface Display {
    getElement(): HTMLElement;
    getWidth(): number;
    getHeight(): number;
    scale(scale: number): void;
  }

  export class Client {
    static readonly State: { CONNECTED: number; DISCONNECTED: number };
    constructor(tunnel: Tunnel);
    connect(data?: string): void;
    disconnect(): void;
    getDisplay(): Display;
    sendSize(width: number, height: number): void;
    sendMouseState(state: MouseState, applyDisplayScale?: boolean): void;
    sendKeyEvent(pressed: number, keysym: number): void;
    createClipboardStream(mimetype: string): unknown;
    onstatechange: (state: number) => void;
    onerror: (status: Status) => void;
    onclipboard: (stream: InputStream, mimetype: string) => void;
  }

  export class WebSocketTunnel implements Tunnel {
    constructor(url: string);
    connect(data?: string): void;
    disconnect(): void;
  }

  export class Mouse {
    constructor(element: HTMLElement);
    onmousedown: (state: MouseState) => void;
    onmouseup: (state: MouseState) => void;
    onmousemove: (state: MouseState) => void;
  }

  export class Keyboard {
    constructor(element: HTMLElement);
    onkeydown: (keysym: number) => void;
    onkeyup: (keysym: number) => void;
    reset(): void;
  }

  export class StringReader {
    constructor(stream: InputStream);
    ontext: (text: string) => void;
    onend: () => void;
  }

  export class StringWriter {
    constructor(stream: unknown);
    sendText(text: string): void;
    sendEnd(): void;
  }

  const Guacamole: {
    Client: typeof Client;
    WebSocketTunnel: typeof WebSocketTunnel;
    Mouse: typeof Mouse;
    Keyboard: typeof Keyboard;
    StringReader: typeof StringReader;
    StringWriter: typeof StringWriter;
  };

  export default Guacamole;
}
